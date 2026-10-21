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

| Fix | RM/metre | Additive shade gain | Additive albedo gain |
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

## Important integration limits

The current engine reads **uncorrected `heat_hXX`** even if `heat_corr_hXX` later
appears. There are currently no corrected columns in the shared GeoJSON. Its
docstrings imply corrected-heat support, but the implementation does not use
those columns. The Planner explicitly labels this baseline and does not run a
correction or imply one has been applied. Coordinate with Persons 1 and 2 before
changing this behavior.

`engine._weather_radiation()` currently averages all weather rows by hour,
including design-day and forecast rows. Baseline heat comes from the design
day. These are actual engine projections, not fully design-day-calibrated
intervention estimates. Resolving the weather filter belongs to Person 2.
The app leaves this shared interface unchanged and discloses the limitation.

Phase 7 also confirmed that engine coordinate snapping can disagree with the
authoritative `places.node_id`, including the station. Walking demand and thus
benefits need re-baselining after Person 2 fixes this. See
[the integration QA handoff](integration_qa.md) for evidence and the suggested
resolver change. Current values remain real engine output, not validated
investment advice. Person 3 now rejects mismatched baseline heat/design weather
before invoking the engine and isolates Planner widget reruns using a Streamlit
fragment; neither change replaces the planning algorithm.

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

`st.cache_data` stores results in memory, returning copies. Keys include budget
or preview selections plus resolved input paths, file sizes and modification
times, including the engine source. No `engine.set_data_dir()`, monkey patch,
shared-state mutation or file write occurs. The standalone engine took about
10 seconds locally; uncached requests during headless software-rendered browser
QA sometimes took minutes. Subsequent unchanged calls reuse results. Restart after
teammates update source code so Python reloads their implementation. The preview
is held per Streamlit session and is hidden for different selections/inputs.

## Actual RM100,000 result

Computed through `engine.priorities(100000)` against the current repository:

| Rank | Link | Fix | Cost RM | Daily exposure saving (person·°C·min/day) |
|---:|---|---|---:|---:|
| 1 | L0027 | shade_trees | 4,896 | 332.71770 |
| 2 | L0026 | shade_trees | 7,216 | 469.58981 |
| 3 | L0111 | shade_trees | 1,968 | 127.34437 |
| 4 | L0777 | shade_trees | 22,144 | 1,432.88304 |
| 5 | L0112 | shade_trees | 6,560 | 424.48125 |
| 6 | L0789 | shade_trees | 6,464 | 405.98472 |
| 7 | L0107 | shade_trees | 2,144 | 132.51638 |
| 8 | L0787 | shade_trees | 11,168 | 576.49223 |
| 9 | L0108 | shade_trees | 7,680 | 373.18316 |
| 10 | L0202 | shade_trees | 4,624 | 210.61603 |
| 11 | L0203 | shade_trees | 9,728 | 443.09532 |
| 12 | L1081 | shade_trees | 4,528 | 206.02114 |
| 13 | L1072 | shade_trees | 6,832 | 310.52046 |
| 14 | L0543 | shade_trees | 3,632 | 116.31935 |

Selected spending **RM99,584**; remaining **RM416**; summed daily saving
**5,561.76496 person·°C·min/day**. Whole-network exposure reported by the engine:
**71,056.713 → 65,494.948 person·°C·min/day** (rounded independently).
These results change when shared inputs or engine assumptions change.

At **RM10,000**, the engine selects L0027, L0111, L0107 and L0502 (shade trees),
spending **RM9,904** and leaving **RM96**. At **RM0**, selection and spending are
zero while the real network remains visible.

## Browser/manual verification checklist

1. In Chrome and Edge, confirm all four tabs load and previous controls still work.
2. Open Planner at RM100,000; compare metrics/table against the result above.
3. Verify street tiles, grey network, green selected links and hover details.
   Pan/zoom; paths must remain bounded in width, with no solid viewport fill.
4. Set budget RM0: zero spending, no selections, network still visible. Set
   RM10,000: actual lower-budget selections and remaining funds must update.
5. Restore RM100,000; preview L0027 / Shade trees. Expect cost RM4,896,
   13:00 heat-index drop 3.4254°C and saving 332.718 person·°C·min/day.
   Check hourly chart/table, shade percentages, albedo and whole-network totals.
6. Select another link/fix. The previous preview must disappear; request a new
   preview. Budget metrics and original Heat Map must stay unchanged.
7. Return to Cool Route, Heat Map and Sensors; exercise a control in each.
8. Confirm `git diff -- engine.py heat_model data` is empty after using previews.

Automated tests cover real budgets, unit labels, rejected malformed allocations,
preview isolation and protected-file hashes, CRS transformation, invalid geometry,
literal-string serialization, bounded widths and four-tab Streamlit interactions.
Unit tests alone do not establish browser rendering success. Browser screenshots
and verification details are reported separately in the Phase 6 delivery.

### Phase 6 verification record

The complete suite passed **134 tests** (105 previous tests plus 29 Planner
tests) in 141.21 seconds, using the full command above. Windows required the
owning account to reset the existing pytest temporary directory; no application
test failed in the successful full run.

Headless Edge with software WebGL was exercised against the actual local app:
RM100,000 → RM0 → RM10,000 → RM100,000, selected-link hover, L0027 shade-tree
preview, hourly chart/table and all four tabs. No page exceptions were reported;
CARTO responses returned HTTP 200. The map, tooltip and preview screenshots were
inspected. The same budget, hover, preview and four-tab sequence also completed
in headless Chrome; no page exceptions were reported and CARTO returned HTTP 200.
Chrome's map and hourly preview screenshots were inspected as well. This verifies
desktop-size headless browser rendering, not a separate manual mobile-device test.
Protected-file hashes matched before and after the browser previews.

Local-only artifacts are under ignored `cache/`: `planner_browser_check.py`,
`planner-edge-*.png`, `planner-chrome-*.png`, server logs and separate browser
profiles. No QA helper or screenshot writes a shared data file. First uncached
budget calculations were slow under this headless setup, so a spinner remains
visible until real engine output is available; cached budget restoration was fast.
