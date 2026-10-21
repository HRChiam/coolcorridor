# Heat model data for the app and the sensor simulator

For Person 3 (web app and sensor simulator). This covers what the heat model gives you, for the simulator and for each app tab, and how to run the sensor correction once your readings exist. The interfaces below describe the merged implementation; historical main-branch numerical examples are not merged-model results.

## The imports

From the repo root:

```python
import engine                                # Person 2's module: the contract functions
from heat_model.heat import design_weather   # the weather of the modelled day
```

| Name | What it gives you |
|---|---|
| `engine.heat_at(hour)` | 1,491 real links, EPSG:4326 longitude/latitude, network fields including `unsafe` and `confidence`, `shade`, `heat_model` (baseline), `heat_score` and `heat` (same effective index), `hour`, `design_date`, `heat_source`, `sensor_source`, `correction_version`. Corrections require a validated active bundle; both heat interfaces agree. |
| `design_weather()` | The day we model, **6 Sep 2026**, indexed by hour: `air_temp_c`, `rh_pct`, `sw_wm2` (sunlight), `wind_ms`, `sun_elev_deg`, `sun_azim_deg` |
| `engine.HOURS` | `(7, 8, …, 19)`, for the 7am to 7pm slider |

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
at_1pm = sites.merge(engine.heat_at(13)[["link_id", "shade", "albedo"]], on="link_id")
```

Then follow the spec: air = `air` + `offset_c` + noise; surface = air + (1 − `shade`) × `sun` ÷ 1000 × 25 × (1 − `albedo`) + noise. Take `shade` from `engine.heat_at(hour)` for each reading's hour, because shade changes through the day (S05, the covered walkway, is always 1.0).

### `data/sensors_stream.csv`

One row per reading, exactly the columns in the data contract:

```
sensor_id,link_id,timestamp,air_temp_c,rh_pct,surface_temp_c,source
S03,L0375,2026-09-06T13:05:00+08:00,33.6,41,38.9,simulated
```

- `link_id` must be one of the IDs above; the correction stops if it doesn't recognise one.
- Timestamps must be timezone-aware. Correction accepts only 6 September 2026, 07:00–19:00 Asia/Kuala_Lumpur, on the five-minute schedule. Other dates are excluded and counted; invalid timestamps fail validation.
- Raw faults stay intact. The offline calibration excludes anomalies detected by the Dashboard residual rule before nearest-hour medians. Missing samples are never invented; zero-coverage hours explicitly retain baseline heat.

### Running the correction

The correction is an explicit offline operation; the app never runs it:

```powershell
.venv\Scripts\python.exe heat_model\sensor_correction.py
```

- It creates a separate immutable `data/corrections/v1-*` bundle and prints the synthetic pipeline check. It never writes corrected columns into the frozen network or changes raw sensor CSV.
- Use `python -B -m heat_model.sensor_correction --activate` only as an explicitly reviewed offline operation. An existing different pointer is refused; archive it and review a new version before activation.
- `data/corrections/current.json` selects the validated bundle. Input, implementation and output SHA-256 hashes must match. App reads never generate or apply corrections.
- Median calibration excludes detected residual anomalies, not configured fault IDs. The before/after check uses disjoint adjacent-hour windows of simulated air residuals; it is not field validation.

## Part 2: the app

### Heat Map tab

- **Colour:** `engine.heat_at(hour).heat_score`. Fix the colour scale to **26 to 44°C** for every hour. Over the day the heat runs from 26.4 to 43.1°C, so a fixed scale makes the map visibly heat up and cool down as the slider moves.
- **Slider:** `engine.HOURS`. Every hour is precomputed, so moving the slider only reads columns.
- **Toggles:** covered walkways = `covered`; trees = `canopy > 0`; shade = `shade`.
- **Optional confidence display:** draw links with `confidence == "low"` at reduced opacity. `confidence` is `high` (hand-tagged and within 150 m of a sensor, 49 links), `medium` (hand-tagged, 14) or `low` (values borrowed from other links, 1,428), so most of the map is faded and the checked main routes stand out.
- **Share of the network in shade** at the chosen hour: `(g.shade * g.length_m).sum() / g.length_m.sum()`. At 1pm it's 19.7%. This is the same definition as Person 1's shade-coverage result.
- **Unsafe links** (`unsafe == True`, 60 main-road links with no known footpath) are left out of routes by Person 2. Showing them on the map, e.g. as a dashed line, is optional.
- **Buildings layer** (optional): `data/buildings.geojson`, with `height_m`.
- **Drawing links with pydeck's PathLayer:**

```python
g = engine.heat_at(hour)
g["path"] = [list(map(list, geom.coords)) for geom in g.geometry]   # [[lon, lat], ...]
```

- **Sensor dots:** `lat`/`lon` from `data/sensor_links.csv`, with the newest values from your `latest_sensors()`.

### Sensors tab

Compare like with like. **The sensors measure air temperature; the heat score is not an air temperature** (it adds the effect of sun and wind). So plot each sensor's `air_temp_c` against the model's air temperature for that hour, `design_weather().air_temp_c`. The gap between the two lines is exactly what the correction uses. Keep the "Simulated data" banner on this tab.

### Cool Route and Planner tabs

These come from Person 2's `engine.py` (`route()`, `priorities()`, `apply_fix()`). For the from/to dropdowns, use `data/places.geojson`: 66 places with `place_id`, `name` and `kind` (home 34, shop 25, park 4, community 2, transit 1). The three Serasi Residences blocks have 0 households because the building opens in Feb 2027. Label them "(opens Feb 2027)" if you list them.

**Cool Route:**
- The engine supports `mode` (the existing comparison tab renders shortest and coolest): fastest → `"shortest"`, balanced → `"balanced"` (at most 10% longer), cooler → `"coolest"` (at most 25% longer). For example, `engine.route(origin_id, dest_id, hour, "balanced")`.
- Cards: `distance_m`, `extra_distance_pct`, `minutes_in_sun`, `heat_avoided`. Draw `result["geometry"]` (a GeoJSON FeatureCollection) in colour, and the shortest route in grey from `result["shortest"]["link_ids"]`.
- Every mode avoids unsafe roads. If a place can only be reached on one, `result["uses_unsafe"]` is `True` and `result["warning"]` holds a message to show. Today no trip needs one.

**Planner:**
- `engine.priorities(budget_rm, horizon_years=10)` returns the ranked fixes with `cost_rm` (building cost, which the budget covers), `upkeep_rm_per_year`, `cost_10y_rm` (build + 10 years of upkeep), `person_min_saved_day` (once fully working), `benefit_over_horizon` (allowing for time to take effect), `benefit_per_rm`, `weeks_to_effect` and `quick_win`; show the quick-win tag and a "10-year total cost" column per fix. Area totals are in `.attrs["area_before"]` and `.attrs["area_after"]`; money in `.attrs["spent_rm"]` (build), `.attrs["upkeep_rm_per_year"]` and `.attrs["cost_10y_rm"]`. Show it as "RM X to build, plus RM Y a year".
- **The "next 12 months / 10 years" toggle** sets `horizon_years=1` or `horizon_years=10`. Label the results "with our assumed costs".
- `engine.priorities(budget_rm, quick_wins_only=True)` ranks only fixes that work within months (sails, covered walkways, cool paving): "what helps this year".
- `engine.apply_fix(link_id, fix)` gives the before/after for one link; pass a list of link IDs for several at once.
- Budget-independent demand and candidates are content/version cached. Horizon and upkeep policy are cache keys; `use_cache=False` provides an equivalent uncached reference.

## Things to know

- Shared effective-heat caches validate input content, implementation hashes and the active correction version; stale or corrupt bundles fail explicitly.
- Don't edit `links.geojson` by hand. The heat model's scripts rewrite it.
- Link IDs are frozen. Everything (sensors, flows, fixes) is keyed by `link_id`.
- `data/coverage_map.html` and `data/tagging_map.html` are working maps on Person 1's machine only, not in the repo.
- Your rows in `docs/assumptions.md`: sensor offsets (including S08's grass value), noise levels, and the two faults.
