# Using the heat model in engine.py

For Person 2 (routing and planner). This is everything from the heat model that `route()`, `priorities()` and `apply_fix()` need, and how to call it. Every snippet here has been run against the current data.

> **Update, 20 Oct.** This guide was written before `engine.py` existed. Agreed since then:
> - **`engine.heat_at` (yours) is the one `heat_at` the app uses.** It now takes the sensor-corrected `heat_corr_hNN` columns when they exist, and so do routing, fixes and area totals (through `_heat`). It also passes through the `unsafe` and `confidence` columns once Person 1 adds them. `heat_model.heat.heat_at` below still works and gives the same values; the app just doesn't need it.
> - **Shade formula for fixes:** `s1 = s0 + (1 − s0) × shade_gain`, as in the `apply_fix` section below; it's now in `engine._calculate_fix`.
> - **`unsafe` column is ready** (boolean, in `links.geojson` and so in `engine.heat_at`): 60 main-road links with no known footpath, with the reason in `unsafe_reason`. Every place can still reach the LRT without them, so your 10× fallback is a safety net rather than something today's data needs. `confidence` (high / medium / low) is there too.
>
> **Changes Person 1 made to your code on 20 Oct** (to finish the revised plan before the freeze; please review, all 12 tests pass):
> - `route()` takes `mode="balanced"` (≤ 10% detour, from the same six λ searches as coolest).
> - Unsafe links are skipped by every route, walking demand and `route_summary`; if that leaves no path, they cost 10× and the route has `uses_unsafe=True` plus a `warning`. All path-finding goes through `_safe_path`.
> - `interventions.csv` has `weeks_to_effect`, `maintenance_rm_per_year` (RM per metre) and `quick_win`, with public cross-checks in `note`. Prices are unchanged.
> - `priorities()` returns `weeks_to_effect` and `quick_win`, and takes `quick_wins_only=True`. `apply_fix()` also returns them, plus yearly upkeep.
> - `route_summary()` takes `mode` and reports `trips_needing_unsafe_link_pct`.
> - `person2_results.py` prints coolest and balanced routes, all-day and at 1pm, the best quick wins, and with `--comfort-test` the 30 / 32 / 34°C test. It was run with `--embed-flow`, so `flow_day` is in `links.geojson` and `priorities.csv` is current.
> - Four new tests: balanced route, unsafe links skipped, the 10× fallback, and the exact budget search.
> - **`priorities()` now finds the best mix exactly** (`_best_mix`: at most one fix per link, most person-minutes saved within the budget, RM 10 steps with costs rounded up). Picking fixes one by one by benefit per RM locked busy links into trees; the exact search picks sails there and saves 6.7% more at RM 100k, 39.6% more at RM 250k, in ≤ 0.11 s. RM 100k now buys 4 sails + 3 trees (−8.6% area-wide heat).
> - **`priorities()` counts time to take effect and upkeep** over `horizon_years` (default 10; the app's toggle uses 1 and 10). Benefit = full daily benefit × `effect_share(w, H)` = 1 − w/(2H), or H/(2w) once the fix needs longer than the horizon (the 1 − w/(2H) formula alone goes negative for trees over 12 months). The budget covers building costs only; upkeep is shown alongside: new columns `upkeep_rm_per_year` and `cost_10y_rm` (build + 10 × upkeep), totals in `.attrs`, plus `benefit_over_horizon`; `benefit_per_rm` = benefit over the horizon per RM of build cost. With our assumed costs, RM 100k builds 5 sails + 1 cool paving in both views (−8.2% over 12 months, −8.5% over 10 years), plus RM 12,614 a year upkeep.
> - `fix_options(horizon_years, upkeep_scale)` lists every candidate fix with its 10-year value (benefit ÷ 10-year total cost); `person2_results.py` uses it for the upkeep sensitivity check (×0.5, ×1, ×2). Sails beat trees on every link at all three levels; the best 10-year value is sails, except covered walkways at ×2.
> - `route_summary()` also reports `trips_with_heat_exposure_pct` and `exposed_trips_with_cooler_route_pct` (the denominator is trips that can be improved), and takes `max_detour` for a sensitivity check. `person2_results.py` prints the 30% detour check and the planner at RM 50k / 100k / 250k with the extra heat removed per extra ringgit.

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
- **`heat_model.heat.heat_at` reads the file once and caches it** (restart after a re-run). `engine.heat_at` reads it on every call.
- **Some links are gated-estate streets** (`private = True` in `links.geojson`). They are included on purpose: residents walk their own estate's streets.
- **Link IDs are frozen.** Don't re-pull the area; your flows and fixes are keyed by `link_id`.

## Your rows in `docs/assumptions.md`

Fill these in as you set them: walking speed, trips per household by hour and destination, cost per metre of each fix, the `shade_gain` and `albedo_gain` you choose, and the comfort-line test at 30 and 34°C.
