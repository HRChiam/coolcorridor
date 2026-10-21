# Township Cooling Investment Planner

Phase 6 adds the fourth **Planner** tab. The three existing tabs and their
independent controls are preserved. All planner data access is read-only.

## Run and verify

From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open http://127.0.0.1:8501 and select **Planner**. Stop with Ctrl+C. Dependencies
are already in `requirements-person3-lock.txt`; no new package is required.
CARTO basemap tiles need internet access; engine calculations use local files.

```powershell
.venv\Scripts\python.exe -B -m pytest tests/test_planner.py -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

## Sources and actual contracts

- `engine.priorities(budget_rm)` accepts a finite, nonnegative RM amount. It
  returns a DataFrame with `rank`, `link_id`, `fix`, `cost_rm`, `heat_drop`,
  `person_min_saved_day`, `benefit_per_rm`. Attributes include `budget_rm`,
  `spent_rm`, `area_before`, `area_after`, and `data_label`.
- `engine.apply_fix(link_id, fix)` accepts one real link ID and one intervention
  name. It returns cost, benefit, 13:00 heat reduction, whole-network exposure
  before/after and hourly heat/shade plus albedo for that link. This function
  computes an independent scenario without applying persistent changes.
- `data/links.geojson`: 1,491 real walking links; baseline `heat_h07`–`heat_h19`,
  hourly shade, length, canopy, coverage, albedo and actual geometry.
- `data/places.geojson`: homes, household estimates and destinations used by
  the engine's `walking_demand()` to assign assumed shortest-path trips.
- `data/weather.csv`: solar radiation inputs used by the existing engine.
- `data/interventions.csv`: supported fixes, costs, gains and assumption notes.
  The app reads the available types from this file, not a fake shortlist.

`data/priorities.csv` is an existing saved output, **not** the live planner's
source. No export, sensor correction, simulator or shared-output script runs.

## Selection and budget checks

The engine evaluates every link/fix pair with positive benefit. It sorts by
benefit per RM descending, benefit descending, cost ascending, then link ID.
It scans this order, accepting a candidate if it fits the remaining budget and
its link has not already received a fix. This is a greedy heuristic, not a
guaranteed optimal allocation. Ranks indicate **selection order**.

Only budget-selected recommendations are returned. There is no public interface
for an unfunded ranked shortlist; the app does not invent one. “Selected within
budget (proposal)” means proposed spending, never installed or contracted works.
The app independently sums actual row costs, checks the budget and engine spent
metadata, and derives the remaining amount. An invalid allocation is rejected
with an error rather than presented as funded. Zero budgets and budgets that
cannot buy a beneficial fix produce no manufactured recommendations.

## Units and assumptions

Daily benefit is the sum across links/hours of:

`assumed walkers × walking minutes × reduction in max(heat index − 32°C, 0)`

The unit is **person·°C·minutes/day**, abbreviated `person·°C·min/day` in the UI.
Despite its name, engine field `person_min_saved_day` has this exposure unit:
it is not person-minutes, ordinary minutes or a medical benefit. Benefit/RM
has units person·°C·minutes/day/RM. Ordinary route exposure has °C·minutes;
the planner also weights by assumed daily walkers.

`heat_drop` means reduction in the **13:00 modelled heat index**, not daily
average cooling or measured air-temperature change. The preview displays every
hour from 07:00 through 19:00, with local-hour labels Asia/Kuala_Lumpur.
The heat index includes sun, shade, albedo and wind; it is not measured air
temperature. Benefits are prominently **MODELLED / SIMULATED** estimates.

Actual intervention assumptions from the current CSV:

| Fix | RM/metre | Gain on remaining sunlight | Additive albedo gain |
|---|---:|---:|---:|
| shade_trees | 160 | 0.35 | 0 |
| shade_sail | 350 | 0.75 | 0 |
| covered_walkway | 1,000 | 1.00 | 0 |
| cool_paving | 120 | 0 | 0.30 |

Cost is link length times the unit price; gains cap at 1. Covered walkway
forces full shade. The existing engine recomputes the solar-term difference
and holds walking demand fixed. Prices need contractor quotations; planting,
land ownership, access, tree maturation and construction feasibility need review.
The engine uses 72 m/min walking speed, assumed household trip rates and hourly
trip weights. These inputs are not observed pedestrian counts.

## Shared heat, weather and shade contract

The engine, Heat Map and Cool Route consume one validated effective heat bundle.
`heat_model` is the uncorrected export; effective `heat` includes offline
**SIMULATED** correction where available. Source/version metadata is preserved
in recommendations and previews and displayed honestly. No bundle means explicit
baseline fallback; invalid/incomplete bundles fail rather than mixing sources.

Weather uses exactly one design record per hour on **2026-09-06**,
Asia/Kuala_Lumpur; forecast rows cannot affect solar changes. All 66 place
resolutions use authoritative junction IDs, fixing demand and route endpoints.
Shade after a fix is `before + (1 − before) × gain`, capped at 1, with covered
walkway forcing full shade. Original CSV gains and costs are unchanged.
`apply_fix` adds the model solar-term difference to effective heat, retaining
its calibration offset and rounded original export. Demand stays fixed.
See [integration repair](full_integration_repair.md) for evidence and limitations.

## Map and preview isolation

The app transforms declared network CRS to EPSG:4326 and renders actual
LineString/MultiLineString coordinates in `[longitude, latitude]` order.
Grey paths show the network; green trees, orange sails, purple walkways and
blue paving show budget-selected investments. Tooltips identify rank, link,
fix, cost, daily benefit, benefit/RM and 13:00 heat-index reduction.

Path widths use `pydeck.types.String("pixels")` with a 10-pixel maximum, preserving
the previous map serialization fix. No growing markers or numeric CRS enums
are introduced. CARTO's existing light basemap and coordinate-fitted viewport
are reused. Invalid drawable geometries are reported and omitted, never
replaced with invented locations; missing source geometries stop planning with
a clear error because the shared demand engine also requires them.

Preview is a **separate single-link scenario**, not an addition to the budget
selection and not a combined intervention simulation. Press Preview after
choosing a link/fix. Changing either selection hides the previous result until
requested again. Its cost can exceed the selected budget; this does not allocate
funds. Before/after shade, heat and albedo are engine outputs, and the displayed
whole-network exposure has the engine's actual units.

`st.cache_data` stores presentation results in memory, returning copies. Keys
include selections, engine/file identity, content hashes, relevant modelling
assumptions and the active correction version. The engine additionally caches
budget-independent demand and candidate calculations. `use_cache=False` runs
the same repaired arithmetic for comparison. Previews do not change `DATA_DIR`,
cached tables or files. Changing Python code requires an app restart.

## Actual RM100,000 result

The repaired `engine.priorities(100000)` selects **15 shade-tree links**, spends
**RM99,920**, leaves **RM80**, and estimates **5,587.79224 person·°C·min/day**
exposure saving. Modelled whole-network exposure is **71,673.247 → 66,085.455**
(rounded). The full reproducible selection and before/after comparison are in
[final_results.md](final_results.md) and versioned `data/results/` outputs.

At **RM10,000**, four links cost **RM9,904**, leaving **RM96**; saving is
**594.03495 person·°C·min/day**. At RM0 there are no selections. These are
modelled outputs, not construction recommendations validated in the field.

## Browser/manual verification checklist

1. In Chrome and Edge, confirm all four tabs load and previous controls still work.
2. Open Planner at RM100,000; compare metrics/table against the result above.
3. Verify street tiles, grey network, green selected links and hover details.
   Pan/zoom; paths must remain bounded in width, with no solid viewport fill.
4. Set budget RM0: zero spending, no selections, network still visible. Set
   RM10,000: actual lower-budget selections and remaining funds must update.
5. Restore RM100,000; preview L0027 / Shade trees. Expect cost RM4,896,
   13:00 heat-index drop 3.4157°C and saving 364.838 person·°C·min/day.
   Check hourly chart/table, shade percentages, albedo and whole-network totals.
6. Select another link/fix. The previous preview must disappear; request a new
   preview. Budget metrics and original Heat Map must stay unchanged.
7. Return to Cool Route, Heat Map and Sensors; exercise a control in each.
8. Compare input checksums before/after previews; the repair itself intentionally
   changes engine/heat source and adds versioned outputs, but previews write nothing.

Automated tests cover real budgets, unit labels, rejected malformed allocations,
preview isolation and protected-file hashes, CRS transformation, invalid geometry,
literal-string serialization, bounded widths and four-tab Streamlit interactions.
Unit tests alone do not establish browser rendering success. Browser screenshots
and verification details are reported separately in the Phase 6 delivery.

### Verification records

The original Phase 6/7 results were historical, before the integration repairs.
Current complete test counts, actual Edge/Chrome verification, screenshots and
fresh/cached timings are recorded in [full_integration_repair.md](full_integration_repair.md).
Unit tests alone do not establish browser rendering success.
