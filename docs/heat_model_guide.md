# Using the heat model in engine.py

For Person 2 (routing and planner). This is everything from the heat model that `route()`, `priorities()` and `apply_fix()` need, and how to call it. Every snippet here has been run against the current data.

## The one import you need

From the repo root (where `engine.py` lives):

```python
from heat_model.heat import heat_at, heat_score, design_weather, COMFORT_C, HOURS
```

| Name | What it gives you |
|---|---|
| `heat_at(hour)` | GeoDataFrame, one row per walking link at that hour (7 to 19). Columns: `link_id`, `u`, `v`, `name`, `length_m`, `covered`, `canopy`, `surface`, `albedo`, `geometry`, `shade` (0 to 1), `heat_model` (°C), `heat` (°C, sensor-corrected once Person 3's sensors exist; until then equal to `heat_model`) |
| `heat_score(air_temp_c, shade, sw_wm2, albedo, wind_ms)` | The heat formula itself. Works on numbers or whole columns. Use it in `apply_fix` to get the "after" heat. |
| `design_weather()` | The weather of the day we model (6 Sep 2026), indexed by hour: `air_temp_c`, `sw_wm2` (sunlight), `wind_ms`, `rh_pct`, `sun_elev_deg`, `sun_azim_deg` |
| `COMFORT_C` | The comfort line, 32°C. Import it rather than typing 32, so the heat model and your exposure always agree. |
| `HOURS` | `range(7, 20)`: 7am to 7pm |

Always use `heat` for routing and planning, not `heat_model`.

## Files in `data/`

| File | Use it for |
|---|---|
| `links.geojson` | The walking network: 1,491 links. `u` and `v` are the junctions at each end. `flow_day` is yours to fill (see below). |
| `places.geojson` | 66 places: `place_id`, `name`, `kind` (home, transit, shop, park, community), `households` (homes only), `node_id` (the junction to route from or to) |
| `weather.csv` | Read it through `design_weather()` rather than directly. Its `forecast` rows are not used by the heat model. |

## Routing: `route(origin_id, dest_id, hour, mode)`

Build the graph from `heat_at(hour)`. Heat exposure on a link = walking minutes × degrees above the comfort line.

```python
import networkx as nx

WALK_M_PER_MIN = 72  # 1.2 m/s: your assumption, add it to the Assumptions table

def build_graph(hour):
    g = heat_at(hour)
    g["minutes"] = g.length_m / WALK_M_PER_MIN
    g["exposure"] = g.minutes * (g.heat - COMFORT_C).clip(lower=0)
    G = nx.Graph()
    # 17 pairs of junctions are joined by two links; adding longest first means the shortest one is kept
    for r in g.sort_values("length_m", ascending=False).itertuples():
        G.add_edge(r.u, r.v, link_id=r.link_id, length=r.length_m, exposure=r.exposure)
    return G
```

- Origin and destination: look up each place's `node_id` in `places.geojson`.
- Shortest: weight `length`. Coolest: weight `length + λ × exposure` for each λ in the plan, keeping the coolest route no more than 25% longer.
- **Minutes in sun** for a route = sum over its links of `minutes × (1 − shade)`.
- The graph is fully connected (1,034 junctions), so every place can reach every other.

## Walking demand and `flow_day`

- Homes are `places` rows with `kind == "home"`. **Multiply trips by `households`**, don't count home places equally. The three Serasi Residences blocks have `households = 0` because the building opens in Feb 2027. They generate no trips, which is intended. Total: 855 households.
- Write `flow_day` into `links.geojson` by `link_id`. The heat model's scripts read and rewrite that file but keep `flow_day` as you left it.

## `apply_fix(link_ids, fix)`

A fix changes shade, reflectivity, or both. This keeps the shade formula consistent: a fix blocks a share `shade_gain` of the sun that still gets through.

```python
def heat_after_fix(hour, link_ids, shade_gain=0.0, albedo_gain=0.0):
    g = heat_at(hour).set_index("link_id").loc[link_ids]
    w = design_weather().loc[hour]
    shade = g.shade + (1 - g.shade) * shade_gain
    albedo = (g.albedo + albedo_gain).clip(upper=1)
    after = heat_score(w.air_temp_c, shade, w.sw_wm2, albedo, w.wind_ms)
    return after + (g.heat - g.heat_model)  # keeps the sensor correction
```

Suggested `shade_gain` values for `interventions.csv`, consistent with the heat model's assumptions:

| Fix | `shade_gain` | `albedo_gain` | L0027 at 1pm (now 42.8°C) |
|---|---|---|---|
| Covered walkway | 1.0 (a roof blocks all direct sun) | 0 | 33.0°C |
| Shade trees along most of the link | 0.6 (canopy blocks 80%, over ~75% of the link) | 0 | 36.9°C |
| Shade sail | your figure (e.g. 0.9) | 0 | |
| Cool paving | 0 | e.g. +0.3 | 41.8°C |

Run it for every hour in `HOURS` to get the day's before and after.

## Things that will look odd

- **At 7am, 8am and 7pm, coolest = shortest.** Heat stays below 32°C everywhere, so exposure is zero. (At 7am every link reads 26.4°C: the sun is not up yet.) At 9am and 6pm only the most exposed links pass 32°C. Test routing at 1pm, where the spread is widest (33.0 to 42.8°C).
- **Heat differs between links only through shade and surface.** Air temperature, sunlight and wind are the same across the area in any given hour. That's why the covered walkways and tree-lined streets stand out.
- **`heat_at` reads the file once and caches it.** If the heat model is re-run while your app is open, restart it to pick up the new numbers.
- **Some links are gated-estate streets** (`private = True` in `links.geojson`). They are included on purpose: residents walk their own estate's streets.
- **Link IDs are frozen.** Don't re-pull the area; your flows and fixes are keyed by `link_id`.

## Your rows in `docs/assumptions.md`

Fill these in as you set them: walking speed, trips per household by hour and destination, cost per metre of each fix, the `shade_gain` and `albedo_gain` you choose, and the comfort-line test at 30 and 34°C.
