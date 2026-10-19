# Heat model data for the app and the sensor simulator

For Person 3 (web app and sensor simulator). This covers what the heat model gives you, for the simulator and for each app tab, and how to run the sensor correction once your readings exist. Every snippet here has been run against the current data.

## The import

From the repo root:

```python
from heat_model.heat import heat_at, design_weather, HOURS
```

| Name | What it gives you |
|---|---|
| `heat_at(hour)` | GeoDataFrame, one row per walking link (1,491) at that hour (7 to 19). Columns: `link_id`, `u`, `v`, `name`, `length_m`, `covered`, `canopy`, `surface`, `albedo`, `geometry` (LineString, longitude/latitude), `shade` (0 to 1), `heat_model` (°C), `heat` (°C, sensor-corrected once the correction has run; until then equal to `heat_model`) |
| `design_weather()` | The day we model, **6 Sep 2026**, indexed by hour: `air_temp_c`, `rh_pct`, `sw_wm2` (sunlight), `wind_ms`, `sun_elev_deg`, `sun_azim_deg` |
| `HOURS` | `range(7, 20)`, for the 7am to 7pm slider |

The app reads these files and never needs to download anything. It needs `geopandas` and `pandas` for this import, not `osmnx`, `pvlib` or `rasterio`.

## Part 1: the sensor simulator

### The 8 sensor sites: `data/sensor_links.csv`

| Sensor | Link | Site | Offset (°C) |
|---|---|---|---|
| S01 | L1448 | exposed asphalt | +1.5 |
| S02 | L0027 | exposed asphalt | +1.5 |
| S03 | L0375 | tree-lined | −1.0 |
| S04 | L0298 | tree-lined | −1.0 |
| S05 | L1242 | covered walkway | −0.5 |
| S06 | L1274 | LRT entrance | +1.0 |
| S07 | L1380 | park | −1.5 |
| S08 | L0924 | shops | **+0.5** |

The file also has each sensor's `lat`/`lon` (the middle of its link) and the reason it was chosen. **S08 needs one change to your spec:** people there walk on a grass verge, and the spec has no grass offset. The proposal is +0.5°C, between paver (+0.8) and park (−1.5). Change it if you disagree, and update `docs/assumptions.md` to match.

### Inputs, so the readings match the model

Use the same day and the same link values as the heat model. Otherwise the correction ends up fixing differences between two different days rather than local effects.

```python
import numpy as np, pandas as pd

sites = pd.read_csv("data/sensor_links.csv")   # sensor_id, link_id, offset_c, lat, lon, ...
w = design_weather()                             # hourly, 6 Sep 2026

# 5-minute steps, 7am to 7pm (145 readings per sensor), weather interpolated between hours
t = pd.date_range(f"{w.date.iloc[0]} 07:00", f"{w.date.iloc[0]} 19:00", freq="5min", tz="Asia/Kuala_Lumpur")
hh = t.hour + t.minute / 60
air = np.interp(hh, w.index, w.air_temp_c)
rh = np.interp(hh, w.index, w.rh_pct)
sun = np.interp(hh, w.index, w.sw_wm2)

# For each site's shade and reflectivity, use the model's values for that hour
at_1pm = sites.merge(heat_at(13)[["link_id", "shade", "albedo"]], on="link_id")
```

Then follow the spec: air = `air` + `offset_c` + noise; surface = air + (1 − `shade`) × `sun` ÷ 1000 × 25 × (1 − `albedo`) + noise. Take `shade` from `heat_at(hour)` for each reading's hour, because shade changes through the day (S05, the covered walkway, is always 1.0).

### `data/sensors_stream.csv`

One row per reading, exactly the columns in the data contract:

```
sensor_id,link_id,timestamp,air_temp_c,rh_pct,surface_temp_c,source
S03,L0375,2026-09-06T13:05:00+08:00,33.6,41,38.9,simulated
```

- `link_id` must be one of the IDs above; the correction stops if it doesn't recognise one.
- Timestamps: the correction only uses the hour of day, so the date part doesn't matter. Using 6 Sep 2026 keeps it consistent.
- The two faults are fine. The correction uses each sensor's median reading per hour, so a short spike is ignored, and a silent half-hour just leaves fewer readings that hour.

### Running the correction

The correction only uses your file, so whoever makes `sensors_stream.csv` can run it straight away:

```powershell
.venv\Scripts\python.exe heat_model\sensor_correction.py
```

- It prints the **Sensor correction** results number: the model's error against the sensors, before and after correction, in °C.
- It writes the corrected heat into `data/links.geojson` (after that, `heat_at()` returns corrected `heat`) and per-sensor errors to `data/sensor_validation.csv`.
- **Only one person runs it and commits those two files.** If two people do, git will report a conflict on `links.geojson`.
- Report it honestly: the simulator adds a fixed offset per site, so the correction is bound to learn it. The drop in error shows the method works; it isn't evidence of real-world accuracy.

## Part 2: the app

### Heat Map tab

- **Colour:** `heat_at(hour).heat`. Fix the colour scale to **26 to 44°C** for every hour. Over the day the heat runs from 26.4 to 43.1°C, so a fixed scale makes the map visibly heat up and cool down as the slider moves.
- **Slider:** `HOURS`. Every hour is precomputed, so moving the slider only reads columns.
- **Toggles:** covered walkways = `covered`; trees = `canopy > 0`; shade = `shade`.
- **Buildings layer** (optional): `data/buildings.geojson`, with `height_m`.
- **Drawing links with pydeck's PathLayer:**

```python
g = heat_at(hour)
g["path"] = [list(map(list, geom.coords)) for geom in g.geometry]   # [[lon, lat], ...]
```

- **Sensor dots:** `lat`/`lon` from `data/sensor_links.csv`, with the newest values from your `latest_sensors()`.

### Sensors tab

Compare like with like. **The sensors measure air temperature; the heat score is not an air temperature** (it adds the effect of sun and wind). So plot each sensor's `air_temp_c` against the model's air temperature for that hour, `design_weather().air_temp_c`. The gap between the two lines is exactly what the correction uses. Keep the "Simulated data" banner on this tab.

### Cool Route and Planner tabs

These come from Person 2's `engine.py` (`route()`, `priorities()`, `apply_fix()`). For the from/to dropdowns, use `data/places.geojson`: 66 places with `place_id`, `name` and `kind` (home 34, shop 25, park 4, community 2, transit 1). The three Serasi Residences blocks have 0 households because the building opens in Feb 2027. Label them "(opens Feb 2027)" if you list them.

## Things to know

- `heat_at` reads `links.geojson` once and caches it. After the heat model or the correction re-runs, restart the app.
- Don't edit `links.geojson` by hand. The heat model's scripts rewrite it.
- Link IDs are frozen. Everything (sensors, flows, fixes) is keyed by `link_id`.
- `data/coverage_map.html` and `data/tagging_map.html` are working maps on Person 1's machine only, not in the repo.
- Your rows in `docs/assumptions.md`: sensor offsets (including S08's grass value), noise levels, and the two faults.
