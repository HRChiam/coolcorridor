# Integration merge review: origin/main a64cdcf

This report supersedes pre-merge numerical examples in the integration and
deployment reports. The active merge combines `c5f9a76` (integrated deployment
release) with `a64cdcf` (main, "fix budget"). No merge commit, push or deployment
is authorized by this review.

## Resolution decisions

- `engine.py`: retain the shared validated effective-heat reader, authoritative
  place IDs, orientation-independent junction coordinates, strict design-day
  weather, correction-preserving intervention deltas and proportional shade
  gains. Incorporate main's balanced route (10% detour), unsafe-road exclusion
  with flagged 10x fallback, multiple-link previews, intervention metadata and
  multiple-choice budget optimizer. Expose unsafe-route warnings in the app.
- Planner: retain content/version caching and the uncached reference path.
  Cache assumptions now include routing safety and budget parameters plus the
  engine source hash; candidate keys include horizon and upkeep scale.
  Separate the incoming `person_min_saved_day` full-effect benefit from
  `benefit_over_horizon`, the daily benefit averaged over a linear effect ramp.
  Add 10-year / next-12-month selection and quick-win filtering. The build
  budget excludes upkeep; display yearly upkeep and 10-year total cost.
- `heat_model/heat.py`: retain strict weather and the common effective reader;
  incorporate main's separation of the offline results report and removal of
  stale embedded corrections when explicitly rebuilding baseline heat.
- `heat_model/sensor_correction.py`: retain the reviewed immutable-bundle
  implementation, detected-anomaly exclusion and raw-source protection. Main's
  scientific qualification is retained in documentation: the residual check is
  synthetic pipeline evidence, never field validation. Do not reinstate main's
  source-overwriting correction path or rename the immutable CSV contract.
- `heat_model/results.py`: retain the new teammate report and make it read the
  same effective heat and correction manifest. Optional offline tagging imports
  are deferred until that report needs them. No offline pipeline was run.
- Resolve the three guides into consistent instructions for validated bundles,
  safety-aware routing, proportional gains and horizon-aware planning. Unsafe
  and confidence fields pass through both heat interfaces; optional confidence
  styling is not a claim of new field validation.
- Preserve main's auto-merged network, tags, weather forecast update,
  intervention metadata, legacy result exports, pull-area safeguards,
  `link_flags.py`, CLI changes and NumPy dependency. The auto-merged Person 2
  tests retain balanced routing, safe/fallback routing, optimizer, horizon,
  upkeep sensitivity and non-mutating export coverage.

The optimizer is exact **for its rounded budget grid**, not for arbitrary real
costs: costs round up to RM10 steps, with coarser steps for very large budgets.
It cannot overspend. New lead-time and upkeep assumptions come explicitly from
main's intervention CSV: trees/sail/covered/paving take 260/4/22/2 weeks and
cost RM25/44/15/20 per metre per year to maintain. These are illustrative,
unverified assumptions. Gains, construction unit prices, heat coefficients,
sensor calibration and proportional shade semantics are unchanged.

## Frozen data and integrity

Main retains all 1,491 geometries and every baseline hourly heat value. It adds
safety, confidence, sidewalk and flow metadata, changing the network's byte
hash. Only forecast weather changes; selected 6 September design weather is
unchanged. No source datasets were regenerated or overwritten during resolution.

The previous correction version remains intact. A separate version
`data/corrections/v1-20260906-2c6bce708d14c832/` records the new source and heat
implementation hashes. Generation validated baseline/formula consistency,
then all four derived CSVs were checked **byte-for-byte equal** to version
`v1-20260906-2487cdd6cca7ef71`. They contain 19,383 link-hour rows, 104 sensor-hour
offsets, one rejected detected spike, and 96 held-out synthetic residual checks.
The previous pointer is preserved as
`data/corrections/current-before-merge-v1-20260906-2487cdd6cca7ef71.json`;
`current.json` activates the validated new version. No integrity checks were
bypassed and no manifest was merely re-signed around unvalidated results.

The new byte-preserving deployment snapshot is
`deployment/coolcorridor-f5d9e8d1e2f6a281ec6c.zip` (284,074 bytes), selected by
`deployment/package_manifest.json`. Its SHA-256 is
`2b4dbebc5f4274d07f877461259698b5f613dad8916b2a40650655d6610fa0ab`.
The old ZIP remains and its manifest and portable results summary are archived.
Production still uses `streamlit_app.py`; it never relies on ignored cache files.

## Recomputed results

Evidence: [new results JSON](../data/results/integration-7bc2cfed0119ae14be33/results.json)
and its accompanying CSV exports. Historical exports under `data/priorities.csv`
and `data/hottest_links_1pm.csv` were auto-merged from main and preserved; they
are not the current corrected-model result snapshot and the app does not use
them to calculate current recommendations.

| Quantity | Before this merge | Merged model |
|---|---:|---:|
| RM100,000 selected interventions | 15 trees | 5 sails + 1 cool paving |
| Build spending / remainder | RM99,920 / RM80 | RM99,818 / RM182 |
| Annual assumed upkeep | Not included in old view | RM12,614.40 |
| Build + 10 years upkeep | Not included in old view | RM225,962 |
| Area exposure before interventions | 71,673.247 | 76,573.962 |
| Area exposure after, 10-year average | Old full-effect view: 66,085.455 | 69,489.491 |
| Full-effect daily exposure avoided | 5,587.792 | 7,111.759 |
| 10-year-average daily exposure avoided | Not previously calculated | 7,084.471 |
| Next-12-month-average daily exposure avoided | Not previously calculated | 6,838.873 |
| Demand-weighted trips with a cooler route | 47.61% | 36.74% |
| Heat avoided per improved trip | 3.861 | 4.003 |

Exposure units are modelled person-degree-C-minutes/day above the assumed 32°C
comfort threshold; per-trip units are degree-C-minutes. These are not measured
cooling or health benefits. Before/after comparisons use fixed, safety-aware
demand. Avoiding unsafe roads changes demand from 25,320.25 to 26,611.70 link
traversals/day and changes the area baseline; this is not a change to the heat
formula. The optimizer and effect ramp explain the different intervention mix.

The 136 nearest-home/category OD pairs are evaluated across all 13 hours.
70.06% of trips have positive shortest-path heat exposure; 52.45% of those
exposed trips have a cooler candidate. No evaluated trip requires unsafe fallback.
The solver still searches six penalty candidates within a 25% coolest-route
detour cap, rather than claiming an exhaustive optimum over all paths.

The default P043 shop to P066 LRT at 14:00 is unchanged: shortest 824.5 m,
101.404 degree-C-minutes; coolest/balanced 826.3 m, 92.121 degree-C-minutes;
avoided 9.283. All 66 authoritative place nodes and 1,034 junction coordinates
remain resolved. Synthetic residual MAE remains 1.061823 → 0.162615°C over 96
held-out sensor-hours; sensors remain SIMULATED.

## Validation and review boundary

The exact requested full-suite command passed: **253 passed in 168.06 seconds**:

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

The previous release had 239 tests; main contributes seven additional tests and
this resolution adds seven regression cases. Existing cache mocks now accept
the horizon-aware API. Numerical fixtures were updated only after independent
merged-model recomputation; map tests check each selected fix's actual color.
No tests were removed, skipped or weakened to conceal a failure. The first full
run had 251 passes and two test-adapter failures, both corrected before this run.

Coverage includes all 66 place nodes and 1,034 junction coordinates, all 13 heat
hours, strict design weather, proportional shade, real build/upkeep costs,
safe/unsafe and balanced routes, exhaustive tiny-grid optimizer comparisons,
horizon cache separation/reference equivalence, unchanged correction CSV bytes,
all four Streamlit tabs, manifest corruption and isolated packaged first-run
startup without repository data or local cache.

Conflict-marker scan and `git diff --check` passed before staging. The resolved
files and required regression/documentation/artifact updates are staged for
review; the merge must remain uncommitted. Previous desktop/mobile
browser evidence describes the pre-merge build; automated Streamlit AppTest
checks do not constitute new Chrome, Edge, mobile or cloud visual verification.

To launch the reviewed packaged app locally:

```powershell
.venv\Scripts\python.exe -B deployment_package.py
.venv\Scripts\python.exe -B -m streamlit run streamlit_app.py --server.address 127.0.0.1
```

Check the two Planner horizons, quick-win filter, RM0/RM10k/RM100k budgets,
upkeep labels, S01 spike/S02 outage, and maps in all four tabs before a live demo.
Publishing, merging PR #2, committing this merge and pushing remain unauthorized.
