# Full integration repair

> Official project brand: **COOLNEX**. See the [rebranding review](rebranding.md) for the active deployment snapshot and intentional compatibility/historical exceptions.

> Merge update: numerical results and packaging below describe the pre-merge release. See [merge resolution](merge_resolution.md) for the current `a64cdcf` integration, recalculated Planner and routing results, active correction bundle and deployment snapshot. Previous browser/cloud evidence does not verify this merged build.

This report supersedes the historical [Phase 7 audit](integration_qa.md).
The repair started from clean commit `277ad82` on `person3-app-simulator` and
works on the dedicated `integration-fixes-all-modules` branch. The user explicitly
authorized changes across all three people's Python modules and separately
versioned derived outputs. No commit, push, merge or deployment was performed.

## Baseline and safety

The actual baseline was **162 passed, 1 strict xfailed in 108.89 seconds**.
The expected failure was the station's incorrect place-to-junction resolution.
SHA-256 hashes of 34 original source/input files and the original default routes
and allocation were recorded under ignored `cache/full_integration_baseline/`.

The original network, places, weather, eight sensor mappings, raw sensor stream,
intervention CSV, legacy flow/priority/hottest-link outputs and simulator config
are preserved. New correction and results directories are additive. Earlier
derived versions created during this repair are retained as archives; the active
pointer and final results report identify the version to use. Viewing any tab or
preview never writes these files.

## Bugs, fixes and evidence

| Issue | Root cause | Repair | Regression evidence |
|---|---|---|---|
| 53/66 places disagreed with their junction IDs | Coordinate snapping used wrong graph coordinates and ignored exported `node_id` | One resolver honors valid IDs; invalid supplied IDs fail; absent IDs may use reliable geometry fallback | All 66 IDs checked, including P066 → `node:8141631184`; the old xfail now passes normally |
| Junctions had wrong coordinates | Undirected polyline order was assumed to match `u`/`v` | Intersect unordered endpoint sets across incident links and propagate resolved neighbors | All 1,034 real junctions resolve; reversed lines produce unchanged coordinates/routes; ambiguous fallback rejects explicitly |
| Planner mixed design and forecast weather | Grouping by hour before selecting a date | Shared strict reader selects `day=design`, date `2026-09-06`, exactly one finite record for each 07..19 hour | Duplicate/missing hours, date mismatches, nonfinite/negative radiation reject; extra forecast rows and inferred dtype changes cannot affect selected data |
| Corrections were absent and engine ignored them | Separate readers and an unsafe canonical-output workflow | Immutable offline correction plus shared effective-heat reader and validated active pointer | Complete 19,383 rows; hashes, source/code provenance, mappings, coverage and baseline agreement; all 13 hours agree between Heat Map and Engine |
| Shade gain had two meanings | Additive engine rule conflicted with proportional guide | User chose `after = before + (1-before)*gain`; current CSV gains/prices retained | Partial-shade tests verify the formula and preservation of the effective correction offset |
| Planner repeated expensive work | Repeated snapping, shortest paths, demand and candidate ranking per budget | Authoritative IDs plus content/version/assumption keyed demand, graph and candidate caches | Cached/uncached values and metadata agree at RM0/RM10k/RM100k; input/assumption changes invalidate; returned copies cannot poison caches |
| Newly published artifacts were unreadable from the normal Windows account | Python 3.13 private temporary-directory ACL survived directory rename | Publish from a unique staging directory with normal inherited workspace permissions | Normal-account reader and browser QA, plus staging regression coverage |

The orientation repair retains every real edge ID, geometry and topology.
It does not alter map coordinates to fit a desired result. An isolated edge
with two unresolved endpoint identities cannot support a trustworthy nearest-node
fallback, although authoritative IDs can still route over its topology.

## One effective-heat contract

`heat_model/effective.py` is shared by `heat_model.heat.heat_at()` and `engine.py`.
The public data carries:

| Field | Meaning |
|---|---|
| `link_id`, geometry | Frozen walking link; returned geometry normalized to EPSG:4326, longitude first |
| `heat_model` | Original uncorrected heat index from `heat_hXX` |
| `heat` | Validated effective index, or explicit baseline fallback |
| `heat_source` | `corrected` or `baseline` |
| `sensor_source` | `simulated` for corrected heat; absent for baseline |
| `hour`, `design_date`, `shade` | Selected local design hour/date and shade fraction |
| correction-version metadata | Exact active derived bundle |

`engine.heat_at()` retains the existing `heat_score` alias. Route exposure,
demand-weighted planning and intervention previews use the same effective values.
The Heat Map, Cool Route and Planner display their actual source/version; the
Sensors Dashboard continues to compare raw simulated **air** temperature with
design-day weather air temperature, separately from the heat index.

No bundle gives baseline-only operation. An invalid active bundle is an error,
not permission to mix baseline and corrected links. An hour with no usable
sensors has zero offset and baseline labels in columns and metadata. A corrected
bundle label does not mean every link changed: links outside sensor influence
retain zero correction. The fixed 26–44°C legend clips only colors; tooltips keep
the true index, including corrected values above 44°C.

## Offline correction

Run explicitly from the repository root:

```powershell
.venv\Scripts\python.exe -B -m heat_model.sensor_correction --activate
```

The process validates the existing eight mappings and simulated source, aware
timestamps, five-minute grid, finite air values and the 6 September 2026 replay
window. Other dates are excluded and counted. It preserves the raw S01 spike
and S02 six-sample outage without regenerating the CSV.

Before calibration, the existing Dashboard detector identifies air-minus-weather
residual departures strictly greater than 3°C from the preceding 30-minute median,
requiring three prior readings. The injected fault schedule does not decide
exclusion. It excludes the actual S01 13:05 sample. This is the documented causal
Dashboard rule, not an invented implementation of the Build Plan's underspecified
across-sensor 3-sigma suggestion.

Accepted samples are aggregated in `[hour-30min, hour+30min)` local windows.
The median air value minus design-hour weather gives each site's offset; minimum
one accepted sample retains Person 1's policy. S02 still contributes six noon
samples from 11:30–11:55. There are 104 valid sensor-hours.

Spatial influence retains the existing 150 m nearest-available-sensor rule:
distance from target **link geometry** to **sensor-link midpoint**, in local UTM,
with weight `max(0, 1-distance/150)`. Sensor sites are not relocated. The adjustment
is added to baseline heat and rounded to two decimals; sensor air never replaces
the heat index directly. This offline centred-window process can use later
samples and must not be described as live causal correction.

Each immutable version contains `corrected_heat.csv`, `sensor_offsets.csv`,
`sensor_validation.csv`, `rejected_samples.csv` and `manifest.json`. The manifest
records date/timezone, UTC generation time, simulation seed/source, all input
hashes, selected-design-weather hash, algorithm source hashes, parameters,
coverage and output hashes. `current.json` pins the manifest hash. Changed
implementations create new versions; a different active pointer is never silently
replaced. Earlier pointers were archived explicitly during this repair.

The 96 validation observations compare the previous hour's correction against
the next hour's median simulated air residual, using disjoint adjacent windows.
MAE is **1.061823°C before → 0.162615°C after**. This checks recovery of synthetic
offsets. It is not field validation, air-versus-heat comparison or evidence of
measured thermal comfort or health benefits.

## Scientific and operational limits

The user explicitly chose proportional shade gain. Trees remain 0.35 at RM160/m;
sails 0.75 at RM350/m; covered walkways 1 at RM1,000/m; paving adds 0.30 albedo at
RM120/m. Suggested tree gain 0.6 was not adopted. Prices remain unverified
assumptions. Solar changes use strict design-day radiation and retain the current
effective correction offset; demand is held fixed and each plan uses one fix per
link. Greedy benefit/RM ranking is not a guaranteed global optimum.

The route-share result evaluates each home's nearest reachable destination in
each category, weighted by households, assumed trip rates and hour weights.
It covers all 136 home/category pairs across 13 hours, including zero-household
places with zero demand weight. It is not all possible OD combinations or an
exhaustive search over all walking paths. Cooler alternatives use the existing
six penalty values and 25% maximum distance detour. Improved-trip averages
include only trips with lower exposure.

Demand, canopy/surface estimates, pedestrian speed, comfort threshold and eight
synthetic site offsets need real-world verification. Basemap tiles need internet.
The app never calls `set_data_dir()` during a preview; the engine's optional
global directory setter is not designed for concurrent per-session datasets.
Use one immutable shared bundle per running application.

Provenance hashes are byte-exact. Preserve source/artifact line endings when
packaging, or generate a reviewed new bundle on the target checkout before
activation. Git checkout normalization or editing numerical implementation code
can intentionally invalidate an existing bundle. Older canonical generation/
export scripts may overwrite data; use the new offline commands for this repair.

The Windows ACL behavior is documented in
[Python's `os.mkdir` reference](https://docs.python.org/3.13/library/os.html#os.mkdir).
Staging inherits the existing project's access policy rather than granting
additional system-wide access.

## Reproduce and review

```powershell
# New unused versioned report; includes real routes, all-day demand, exposure,
# hottest links, allocation, validation, and fresh/cached/reference timings.
.venv\Scripts\python.exe -B integration_results.py

# Required complete suite; run as the account owning its temporary directory.
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp

# App only reads the activated data.
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open http://127.0.0.1:8501. Repeating a report uses `--output` with a new unused
directory; existing reports are never overwritten. Model values, prior-versus-
repaired comparisons and benchmark evidence are in [final_results.md](final_results.md).

## Files changed

| Action | Files |
|---|---|
| Modified engine/model | `engine.py`, `heat_model/heat.py`, `heat_model/shade.py`, `heat_model/sensor_correction.py` |
| Created shared reader/report CLI | `heat_model/effective.py`, `integration_results.py` |
| Modified app | `app.py`, `app_data.py`, `heat_map.py`, `planner.py` |
| Modified existing tests | `tests/test_cool_route.py`, `tests/test_engine_person2.py`, `tests/test_heat_map.py`, `tests/test_integration_qa.py`, `tests/test_planner.py` |
| Created tests | `tests/test_effective_heat.py`, `tests/test_engine_integration_repair.py`, `tests/test_final_results.py` |
| Modified documentation | `README.md`, `docs/app_and_sensors_guide.md`, `docs/assumptions.md`, `docs/cool_route_app.md`, `docs/heat_map_app.md`, `docs/heat_model_guide.md`, `docs/integration_qa.md`, `docs/planner_app.md`, `docs/sensor_simulator.md`, `docs/sensors_dashboard.md` |
| Created documentation | `docs/full_integration_repair.md`, `docs/final_results.md` |

`cool_route.py`, `sensors_dashboard.py`, `simulate_sensors.py`, dependencies and
the simulator configuration are unchanged. No additional package was installed.

New correction artifacts live in these three directories:

- **Active:** `data/corrections/v1-20260906-2487cdd6cca7ef71/`.
- Archived: `data/corrections/v1-20260906-025b6463f5a40144/`.
- Archived: `data/corrections/v1-20260906-48d5e91fd7a36913/`.

Each contains exactly `corrected_heat.csv`, `sensor_offsets.csv`,
`sensor_validation.csv`, `rejected_samples.csv` and `manifest.json`.
The three pointer files are `data/corrections/current.json`,
`current.v1-20260906-025b6463f5a40144.archived.json` and
`current.v1-20260906-48d5e91fd7a36913.archived.json` in that same parent directory.
Archived versions record earlier implementation fingerprints; use only the
active pointer with the final implementation.

New result artifacts live in:

- **Final:** `data/results/integration-2548cfb50721d28596d5/`.
- Archived: `data/results/integration-156845bcd5e3a50beedf/`.
- Archived: `data/results/integration-ceac3f6ae7b8ad8f3c3c/`.

Each contains `results.json`, `effective_heat_by_hour.csv`,
`hottest_links_by_hour.csv`, `hottest_walked_links_by_hour.csv`,
`place_node_resolutions.csv`, `planner_benchmarks.csv`,
`population_exposure_by_hour.csv`, `priorities.csv`, `rejected_samples.csv`,
`sensor_offsets.csv`, `sensor_validation.csv` and `walking_demand.csv`.
These names enumerate all new data outputs without replacing any canonical file.

## Automated verification

The required complete suite passed **223 tests in 152.12 seconds**, with no
failures, skips or expected failures. This includes the former station xfail,
all previous valid checks, shared heat across 13 hours, corrected-bundle failure
cases, forecast isolation, all 66 place IDs, reversed line orientation,
proportional gains, source-preserving previews, cache equality/invalidation,
sensor faults and four-tab Streamlit interactions.

The initial restricted-account attempt could not reset the existing
account-owned pytest temporary directory. It produced setup permission errors;
the successful complete run used the owning Windows account and the exact
requested command. A separate normal-account reader check loaded all 1,491
corrected links successfully after the staging ACL fix.

After the final route-caption clarification, its real-engine Streamlit test
also passed separately (**1 passed in 13.52 seconds**). All 12 original data and
configuration files still match their baseline SHA-256 checksums. All 18 files
across active and archived correction versions were readable from the normal
Windows account; archived directory permissions were restored to inherit the
existing workspace policy, without changing file contents.

## Actual browser verification

Both installed **Chrome and Edge** completed the local app checks using headless
desktop browsers and software WebGL under the normal Windows account. This is
actual rendered browser verification, not a claim based on unit tests. It does
not cover physical mobile devices or every GPU/browser configuration.

| Scenario | Chrome | Edge |
|---|---|---|
| Heat 14:00 and 07:00, fixed scale, real paths, eight markers | Passed | Passed |
| Covered/canopy/shade overlays | Passed | Passed |
| Default P043→P066 and alternative P051→P066 routes | Passed | Passed |
| S01 13:05 spike and rendered history charts | Passed | Passed |
| S02 Missing at 12:10, full-day gap, Active recovery 12:30 | Passed | Passed |
| Planner RM0, RM10,000 and restored RM100,000 | Passed | Passed |
| Actual selected-link tooltip, L0027 preview and hourly chart/table | Passed | Passed |
| Repeated tab switching and cached budget restoration | Passed | Passed |
| Other three map canvases remain mounted during budget changes | Passed | Passed |

Screenshots were inspected for actual basemap streets, heat paths and bounded
markers, real orange/green routes, synthetic sensor faults, selected investments
and before/after charts. Both final runs returned **no page exceptions** and
HTTP **200** CARTO responses. The S01 screenshot capture waits for the lazy chart
to render; Chrome's fully rendered spike chart was captured in a separate
successful focused browser run as well.

Screenshots: ignored `cache/fullrepair-chrome-*.png` and
`cache/fullrepair-edge-*.png`; helper `cache/full_repair_browser_check.py` and
per-browser server logs are local QA artifacts. The helper's private server on
8502 and headless browser processes were stopped afterward; it does not stop
the user's existing app on 8501.
The final local record is `cache/full_integration_final_qa.json`, covering
17 screenshots per browser, test outcomes and the final checksum audit.

Observed end-to-end budget updates, including fixed automation settling waits:

| Budget transition | Chrome seconds | Edge seconds |
|---|---:|---:|
| RM100k → RM0 | 4.986 | 3.895 |
| RM0 → RM10k | 5.517 | 4.775 |
| RM10k → cached RM100k | 4.208 | 3.633 |

These follow initial application setup. They are not uncached startup timings or
precise backend latency. The isolated backend benchmark in final_results.md is
**5.981–6.127 s fresh**, **0.024–0.034 s cached**, with identical repaired
reference outputs. Historical browser timings were 57–95 s for new budgets;
the new browser sequence benefits from shared budget-independent engine work.

## Integration and deployment assessment

**PASS for the integrated local hackathon demonstration.** All six audited
software issues are repaired, all four tabs use the intended interfaces, and
there is no remaining shared-interface blocker for the current frozen dataset.
The shade decision is resolved; no further modelling decision is needed to run
this implementation. No canonical-output replacement is required.

Phase 8 deployment preparation can proceed after user review. Deployment itself
is **not authorized or performed**. Before publishing a target checkout, preserve
hashed artifact/source bytes or build and validate a new correction version on
that target; verify its Python dependencies, read permissions and CARTO access.
The current local evidence is not a deployment smoke test. Field calibration,
site/access feasibility, real pedestrian demand and construction quotations
remain separate scientific/team validation work. Do not market the model as
measured real-world cooling or health guidance.
