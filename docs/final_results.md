# Recomputed integration results

> Merge update: numerical results and packaging below describe the pre-merge release. See [merge resolution](merge_resolution.md) for the current `a64cdcf` integration, recalculated Planner and routing results, active correction bundle and deployment snapshot. Previous browser/cloud evidence does not verify this merged build.

Design day: **2026-09-06, Asia/Kuala_Lumpur**. Heat is a Celsius-labelled
modelled index, not measured air temperature. Calibration uses **SIMULATED** data.

Raw [results.json](../data/results/integration-2548cfb50721d28596d5/results.json) records all input/source hashes.
Output: `integration-2548cfb50721d28596d5`. Active correction: `v1-20260906-2487cdd6cca7ef71`.
Generated UTC: `2026-10-21T08:59:25.331706+00:00`. Earlier derived versions are archives.
Input/source hashes were checked unchanged throughout computation.

## Default real route at 14:00

99 Speedmart **P043** to Putra Heights LRT Station **P066**, using authoritative
station junction **8141631184**. Actual engine geometry is retained.

| Metric | Shortest | Coolest |
|---|---:|---:|
| Distance (m) | 824.5 | 826.3 |
| Walking time (min) | 11.451 | 11.476 |
| Sun exposure (min) | 9.684 | 8.466 |
| Heat exposure (°C·min) | 101.404 | 92.121 |

Coolest avoids **9.283 °C·min**, with **0.22%** extra distance.

## Before versus repaired

These differences combine corrected junctions/demand, strict weather, simulated
calibration and proportional shade; they do not isolate one bug's effect.

| Quantity | Before | Repaired |
|---|---:|---:|
| Shortest / coolest distance (m) | 796.5 / 797.7 | 824.5 / 826.3 |
| Shortest / coolest heat exposure (°C·min) | 100.914 / 94.132 | 101.404 / 92.121 |
| Heat avoided (°C·min) | 6.782 | 9.283 |
| RM100k selected links | 14 | 15 |
| Spending / remaining (RM) | 99,584 / 416 | 99,920 / 80 |
| Allocation saving (person·°C·min/day) | 5,561.76496 | 5,587.79224 |
| Area exposure before investment (person·°C·min/day) | 71,056.713 | 71,673.247 |
| Area exposure after investment (person·°C·min/day) | 65,494.948 | 66,085.455 |

## Demand and cooler-route availability

All **66 places** honor authoritative node IDs; all **1,034 junction coordinates**
resolve. The actual network has **1,491 links** and **855 assumed occupied
households**. Repaired demand totals **25,320.25 link traversals/day**, over
**294 used links**. Traversals count repeated walking links, not unique people.

With repaired demand fixed, baseline exposure is
**69,563.092 person·°C·min/day**, and effective
exposure is **71,673.247 person·°C·min/day**.
Calibration does not inherently cool the network: positive simulated offsets on
some busy roads increase the effective index before interventions.

The unsampled analysis covers **136 home/category pairs across all 13 hours**.
**47.61% of eligible assumed trips**, weighted by households, trip rates and hour
weights, have a cooler route within 25% extra distance. Categories use the nearest
reachable destination by walking distance, not every possible OD combination.
Zero-household places contribute zero weight. Among improved trips only, mean
heat avoided is **3.861 °C·min**, extra distance **1.89%**, and sun time avoided
**0.58 min**. Six penalty values are searched, not every possible path.

## Hottest walked links at 13:00

Rank effective heat, then `flow_day * length`, then link ID. The companion
[hottest_links_by_hour.csv](../data/results/integration-2548cfb50721d28596d5/hottest_links_by_hour.csv)
also includes links without assigned demand. Colors cap at 44; values do not.

| Rank | Link | Baseline index (°C) | Effective index (°C) | Traversals/day |
|---:|---|---:|---:|---:|
| 1 | L0027 | 42.78 | 44.39 | 511.85 |
| 2 | L0026 | 42.28 | 43.73 | 520.70 |
| 3 | L0789 | 42.11 | 43.55 | 511.85 |
| 4 | L0777 | 42.28 | 43.34 | 517.75 |
| 5 | L0020 | 42.28 | 43.28 | 79.65 |
| 6 | L0787 | 42.78 | 43.11 | 378.00 |
| 7 | L0023 | 42.78 | 43.06 | 18.90 |
| 8 | L1081 | 42.11 | 43.04 | 162.00 |
| 9 | L1078 | 42.11 | 42.83 | 162.00 |
| 10 | L0109 | 42.28 | 42.70 | 185.40 |

## RM100,000 allocation

All selected fixes are shade trees with the unchanged gain **0.35** on remaining
sunlight and assumed cost **RM160/m**. Greedy benefit/RM accepts one fix per link;
it is not guaranteed optimal. Prices and feasibility are unverified assumptions.
Daily savings have units **person·°C·min/day**, not walking minutes or health outcomes.

| Rank | Link | Cost RM | 13:00 index drop (°C) | Daily exposure saving |
|---:|---|---:|---:|---:|
| 1 | L0027 | 4,896.00 | 3.4157 | 364.83815 |
| 2 | L0026 | 7,216.00 | 3.2390 | 517.03321 |
| 3 | L0777 | 22,144.00 | 3.2390 | 1,564.08075 |
| 4 | L0789 | 6,464.00 | 3.1801 | 446.86101 |
| 5 | L0112 | 6,560.00 | 3.2390 | 444.77334 |
| 6 | L0787 | 11,168.00 | 3.4157 | 595.54072 |
| 7 | L0111 | 1,968.00 | 2.5102 | 103.40980 |
| 8 | L0107 | 2,144.00 | 2.5977 | 108.92685 |
| 9 | L1072 | 6,832.00 | 3.1801 | 333.22318 |
| 10 | L0108 | 7,680.00 | 2.5977 | 304.88930 |
| 11 | L1238 | 8,112.00 | 2.8907 | 304.32532 |
| 12 | L0186 | 10,528.00 | 2.5441 | 392.70770 |
| 13 | L1073 | 2,976.00 | 3.1801 | 89.97161 |
| 14 | L0502 | 896.00 | 2.8730 | 16.86015 |
| 15 | L1407 | 336.00 | 3.1801 | 0.35115 |

Sum of rounded row benefits: **5,587.79224 person·°C·min/day**. Whole-network totals are rounded
independently to three decimals. At RM10,000, four links cost RM9,904, leaving
RM96, with saving **594.03495 person·°C·min/day**. RM0 selects nothing.

Read-only L0027 / trees preview: cost **RM4,896**, 13:00 index drop **3.4157°C**,
saving **364.838 person·°C·min/day**. Full 13-hour before/after values are in JSON; the preview
retains the effective correction offset and writes no files.

## Correction validation

The bundle contains **19,383 link-hours**, **104 sensor-hours**, and **one excluded
detected S01 spike**. The original **1,154-reading CSV** still contains the 13:05
+8°C injected fault and S02's six missing 12:00–12:25 samples. Config and raw
readings are unchanged.

Across **96 previous-hour validation observations**, simulated air-residual MAE
is **1.061823°C before** and **0.162615°C after**. This compares previous-hour
calibration with the next-hour median air residual, using disjoint adjacent
windows. It demonstrates synthetic offset recovery, not heat-index/field accuracy.
It never compares measured air directly with the heat index.
See [the repair report](full_integration_repair.md) for assumptions and provenance.

## Actual backend performance

Fresh Python subprocess per budget: one cold engine-cache call, one warm call,
and the same repaired scalar algorithm with reuse disabled. Interpreter startup
is excluded; operating-system caches are not flushed. Output values and metadata
agree within the report's numerical comparison tolerance.

| Budget RM | Fresh (s) | Cached (s) | Uncached reference (s) | Outputs agree |
|---:|---:|---:|---:|---|
| 0 | 6.127341 | 0.034008 | 6.179330 | True |
| 10,000 | 5.980668 | 0.026404 | 5.939165 | True |
| 100,000 | 5.998514 | 0.023951 | 7.453226 | True |

Cold caching has population overhead and is not guaranteed faster for a single
budget. Repeated budgets reuse independent work. Historical 57--95 s values were
browser end-to-end interactions, which are not directly comparable with backend
timings. Current browser results are recorded in full_integration_repair.md.

## Reproduce

```powershell
.venv\Scripts\python.exe -B integration_results.py
```

The default new versioned directory refuses overwrite. For an identical repeat,
pass `--output` with a new unused path. Exports contain hourly effective heat,
demand, population exposure, hottest links, all place resolutions, priorities,
validation and benchmark CSVs. Canonical inputs are never replaced. Screenshots,
profiles and local QA helpers stay under ignored `cache/` and are not app inputs.
