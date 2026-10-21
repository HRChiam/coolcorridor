# CoolCorridor: three-minute hackathon demo

Use the packaged entrypoint from [deployment_guide.md](deployment_guide.md).
The values below match the reviewed model and the new clean-environment checks.
Full numerical evidence: [final_results.md](final_results.md) and
`deployment/results_summary.json`. Sensors are **SIMULATED**; heat is a
**modelled index**. No field-accuracy or health claim is supported.

## Before judges arrive

Open the approved cloud URL or local packaged app 5–10 minutes early. Visit every
tab so the first real RM100,000 calculation finishes. Confirm version
`v1-20260906-2487cdd6cca7ef71`, 1,491 links, working CARTO streets and visible
orange/green paths. Keep a local browser/server ready if venue internet fails.
Basemap tiles need internet even for a local server; charts and model calculations
use local files. Do not regenerate any dataset during the demo.

Prepare Heat Map at 13:00; Cool Route stays at its independent 14:00 default,
99 Speedmart P043 → Putra Heights LRT Station P066. Sensors starts at S01/13:05.
Planner budget is RM100,000. Precompute the L0027 / Shade trees preview if desired.
Use a desktop display for tooltips and tables; small screens can pan/zoom maps
and scroll tables, with no mouse-hover guarantee on a physical phone.

## Timed sequence

| Time | Action | Suggested explanation |
|---|---|---|
| 0:00–0:15 | Introduce the pilot | “CoolCorridor compares walking heat exposure and helps prioritize illustrative cooling investments around Putra Heights LRT.” |
| 0:15–0:45 | Heat Map, 13:00; toggle shade/canopy/covered outlines | “These are real network links with modelled heat indices. L0027 reaches 44.39°C on the index. The color scale stays 26–44°C; hover retains values above the red endpoint. Shade varies along the network.” |
| 0:45–1:20 | Cool Route, default P043→P066 at 14:00 | “The shortest route is 824.5 m; the cooler route is 826.3 m—1.8 m extra—with 9.283 °C·min less modelled heat exposure. That is exposure, not an air-temperature drop.” |
| 1:20–2:05 | Sensors: S01/13:05; then S02/12:10 and 12:30 | “All readings are simulated. S01 contains an injected +8°C spike; the independent detector reports a 7.6825°C residual departure. S02 has a real gap in the simulated CSV: Missing at 12:10, Active again at 12:30.” |
| 2:05–2:50 | Planner, RM100,000; optional L0027 preview | “The actual greedy model proposes 15 shade-tree links, spending RM99,920 and leaving RM80. Estimated population-weighted exposure changes from 71,673.247 to 66,085.455 person·°C·min/day. The L0027 preview is read-only and separate from the selected plan.” |
| 2:50–3:00 | Close with evidence and limits | “We validated software consistency and recovery of synthetic sensor offsets. Costs, demand and intervention effects remain illustrative; this is not measured cooling or a health outcome.” |

If a calculation is still running, let the real result finish. Never substitute
a screenshot or hardcoded values as if they were a live computation. Static
screenshots can be shown explicitly as previously captured QA evidence if needed.

## Six results to have ready

| Requested category | Reviewed value / interpretation |
|---|---|
| Trips with a cooler route | **47.61%**, demand-weighted across all 136 nearest home/category pairs and 13 hours, with a 25% maximum distance detour |
| Average heat avoided per trip | **3.861 °C·min per improved eligible trip**, not per every trip. Exact mean across all eligible trips is not exported; it is marked missing in the summary rather than inferred from rounded results |
| Top ten hottest links, 13:00 | Full-network and walked-link top-ten tables are in `deployment/results_summary.json`; hottest walked link L0027 has index **44.39°C** |
| Area exposure before/after RM100k interventions | **71,673.247 → 66,085.455 person·°C·min/day**; summed row benefit **5,587.79224**, with totals rounded independently |
| Ranked fixes and costs | All 15 are current CSV shade-tree interventions; rank 1 L0027 costs **RM4,896**, rank 2 L0026 **RM7,216**, rank 3 L0777 **RM22,144**. Full list in final_results.md |
| Sensor correction residual metrics | Previous-hour validation MAE **1.061823 → 0.162615°C**, over **96 simulated sensor-hours**; not comparison of air directly against heat index and not field validation |

The app does not display the whole-day 47.61%/3.861 result as a live route query.
Describe those as the reproducible offline analysis, distinct from the live
default-route comparison. Route controls and sensor/map replay clocks are independent.

## Assumptions appendix

The original Software Build Plan document is not present in this checkout.
This appendix aligns with the six result categories supplied in the deployment
request, the inspected module guides and [assumptions.md](assumptions.md).
The team should cross-check the original plan's wording before final submission.
No missing numerical result is invented.

| Topic | Actual assumption / boundary |
|---|---|
| Replay | 6 September 2026, Asia/Kuala_Lumpur; model hours 07:00–19:00; sensor steps every five minutes |
| Heat formula | `T_air + (1-s)*R/1000*(8 + 4*(1-albedo)) - 0.5*wind`; simplified Celsius-labelled index, not air temperature |
| Comfort / speed | 32°C index threshold; walking speed 72 m/min |
| Trips | 855 assumed occupied households; one-way household rates: transit 0.9, shop 0.45, park 0.15, community 0.10; normalized assumed hour weights |
| Routes | Authoritative exported junction IDs; nearest reachable category destination; six penalty candidates; no more than 25% extra distance; no exhaustive optimum guarantee |
| Intervention shade | User-approved `after = before + (1-before)*gain`, capped at 1; covered walkway forces full shade |
| Gains / prices | Trees 0.35 at RM160/m; sail 0.75 at RM350/m; covered 1 at RM1,000/m; paving +0.30 albedo at RM120/m; unchanged assumptions, not quotations |
| Planner | Greedy benefit/RM; one fix per link; demand fixed during intervention previews; no installed works or guaranteed global optimum |
| Sensors | Eight existing sites; deterministic seed 20260906; synthetic offsets/noise; S01 spike and S02 outage preserved in the CSV |
| Detector | Air-minus-weather departure >3°C versus preceding 30-minute median, at least three prior samples; distinct from the configured +8°C injection |
| Correction | Offline median `[h-30min,h+30min)`; nearest available site within 150 m, linear decay to target link geometry; minimum one accepted reading; no live hardware |
| Validation | Previous-hour correction versus next-hour median simulated air residual, 96 observations; synthetic offset recovery only |
| Exposure units | °C·min per route; person·°C·min/day for assumed population demand; neither ordinary walking minutes nor health outcomes |
