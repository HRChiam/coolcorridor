# Using the heat model in engine.py

For Person 2 (routing and planner). This is everything from the heat model that `route()`, `priorities()` and `apply_fix()` need, and how to call it. Every snippet here has been run against the current data.

## The one import you need

From the repo root (where `engine.py` lives):

```python
from heat_model.heat import heat_at, heat_score, design_weather, COMFORT_C, HOURS
```

| Name | What it gives you |
|---|---|
| `heat_at(hour)` | GeoDataFrame, one row per walking link at that hour (7 to 19). Columns: `link_id`, `u`, `v`, `name`, `length_m`, `covered`, `canopy`, `surface`, `albedo`, `geometry`, `shade` (0 to 1), `heat_model` (°C), `heat` (°C, effective after a validated versioned SIMULATED correction; explicitly baseline when no bundle/usable hour exists) |
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
- `engine.walking_demand()` returns fresh per-link daily/hourly flow using authoritative place IDs. The live app uses this result, not the historical embedded `flow_day`. `integration_results.py` exports a separate versioned table; embedding flow into the frozen GeoJSON is an explicit operation requiring shared-output approval.

## `apply_fix(link_ids, fix)`

A fix changes shade, reflectivity, or both. This keeps the shade formula consistent: a fix blocks a share `shade_gain` of the sun that still gets through.

```python
def heat_after_fix(hour, link_ids, shade_gain=0.0, albedo_gain=0.0):
    g = heat_at(hour).set_index("link_id").loc[link_ids]
    w = design_weather().loc[hour]
    shade = g.shade + (1 - g.shade) * shade_gain
    albedo = (g.albedo + albedo_gain).clip(upper=1)
    old_solar = heat_score(0, g.shade, w.sw_wm2, g.albedo, 0)
    new_solar = heat_score(0, shade, w.sw_wm2, albedo, 0)
    return g.heat + new_solar - old_solar  # retains baseline rounding and correction
```

Current approved semantics: **gain is the fraction of remaining sunlight
blocked**, not an additive percentage of total shade. CSV values and prices
remain unchanged:

| Fix | Shade gain | Albedo gain | Estimated RM/m |
|---|---:|---:|---:|
| shade_trees | 0.35 | 0 | 160 |
| shade_sail | 0.75 | 0 | 350 |
| covered_walkway | 1.00 | 0 | 1,000 |
| cool_paving | 0 | 0.30 | 120 |

The earlier 0.6 tree and 0.9 sail values were suggestions, not adopted inputs.
Covered walkways force shade to 1. Gains and albedo cap at 1. The engine applies
the solar-term **difference** to effective heat, retaining the exported baseline
rounding and existing correction offset.

Run it for every hour in `HOURS` to get the day's before and after.

## Things that will look odd

- Baseline morning/evening heat often stays below the 32°C comfort line;
  correction offsets can change spatial values. Do not assume all morning links
  remain identical. Use actual effective heat to decide whether routes coincide.
- `heat_model/effective.py` is the shared reader for the heat interface and
  engine. `heat_model` preserves raw baseline heat; `heat` is effective;
  `heat_source`, `sensor_source`, `hour`, `design_date` and correction-version
  metadata identify the source. `engine.heat_at()` also retains `heat_score`.
- Caches use input content and correction versions. A changed active bundle,
  incomplete correction, bad hashes or mismatched baselines is rejected rather
  than silently mixed. App reads never apply corrections or regenerate data.
- **Some links are gated-estate streets** (`private = True` in `links.geojson`). They are included on purpose: residents walk their own estate's streets.
- **Link IDs are frozen.** Don't re-pull the area; your flows and fixes are keyed by `link_id`.

## Your rows in `docs/assumptions.md`

Fill these in as you set them: walking speed, trips per household by hour and destination, cost per metre of each fix, the `shade_gain` and `albedo_gain` you choose, and the comfort-line test at 30 and 34°C.

## Offline correction and reproducible reporting

Run `.venv\Scripts\python.exe -B -m heat_model.sensor_correction --activate`
explicitly to create/verify a separate version under `data/corrections/` and
activate it via a validated pointer. It never writes `links.geojson` or the raw
sensor CSV. See [repair details](full_integration_repair.md) for windows, outlier
policy, spatial weights, manifests and validation limitations.

`integration_results.py` exports fresh demand, all-hour effective heat, all 66
place resolutions, routing, priorities and benchmarks to a new version under
`data/results/`. Canonical legacy `priorities.csv`, flow columns and hottest-link
reports are retained as historical outputs, not live app inputs. Recomputed
figures are in [final_results.md](final_results.md).
