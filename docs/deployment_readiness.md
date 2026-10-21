# Deployment readiness

Prepared **21 October 2026**, Asia/Kuala_Lumpur. **PARTIAL for online deployment**:
local packaging, clean installation and browser checks are available; actual
Linux/cloud execution and repository-owner authorization remain unverified.
No commit, push, merge or deployment has occurred. Branch:
`integration-fixes-all-modules`, still based on commit `277ad82`.

## Audit scope and preserved work

Inspected README, full repair/results/historical QA reports, all four app paths,
engine, effective-heat reader, correction manifests and CSVs, requirements,
configuration and existing/new tests. The checkout has no original Software
Build Plan document; six result categories are mapped explicitly in
[hackathon_demo.md](hackathon_demo.md), with missing denominator-specific values
reported as unavailable. The original uncommitted integration work is preserved.

`cache/deployment-preparation-baseline.json` records hashes of 112 pre-existing
files before this phase. Production model, engine, simulator, app modules,
original inputs, active correction and historical derived artifacts are unchanged.
Changes in this phase are deployment/configuration/test/documentation files only.
The package contains no ignored-cache or personal-file dependency.

## Required bytes and paths

- ZIP: `deployment/coolcorridor-7e60744e872603ce7e33.zip` -- **265,086 bytes**.
- ZIP SHA-256: `e472cbce07c56c5a7217f15f220dc86cfc4ad752c12680a5fc20f5f597d091a0`.
- Unpacked: **2,664,459 bytes**, **24 files**.
- Correction: `v1-20260906-2487cdd6cca7ef71`.
- Date/timezone: **2026-09-06, Asia/Kuala_Lumpur**.
- Source: **corrected model using SIMULATED sensors**; all 1,491 links and 13 hours
  (19,383 link-hours) validated, with no fallback hours in this version.

The following table enumerates every runtime file inside the ZIP. The outer
launcher/configuration files are listed afterward. All sizes are exact bytes.

| ZIP member | Bytes |
|---|---:|
| `app.py` | 10,801 |
| `app_data.py` | 1,972 |
| `config/sensor_simulation.json` | 283 |
| `cool_route.py` | 10,094 |
| `data/corrections/current.json` | 165 |
| `data/corrections/v1-20260906-2487cdd6cca7ef71/corrected_heat.csv` | 870,446 |
| `data/corrections/v1-20260906-2487cdd6cca7ef71/manifest.json` | 3,438 |
| `data/corrections/v1-20260906-2487cdd6cca7ef71/rejected_samples.csv` | 222 |
| `data/corrections/v1-20260906-2487cdd6cca7ef71/sensor_offsets.csv` | 5,489 |
| `data/corrections/v1-20260906-2487cdd6cca7ef71/sensor_validation.csv` | 6,703 |
| `data/interventions.csv` | 474 |
| `data/links.geojson` | 1,516,313 |
| `data/places.geojson` | 17,686 |
| `data/sensor_links.csv` | 1,372 |
| `data/sensors_stream.csv` | 77,386 |
| `data/weather.csv` | 1,467 |
| `engine.py` | 40,161 |
| `heat_map.py` | 11,889 |
| `heat_model/effective.py` | 15,716 |
| `heat_model/heat.py` | 4,509 |
| `heat_model/sensor_correction.py` | 18,141 |
| `planner.py` | 17,487 |
| `sensors_dashboard.py` | 20,461 |
| `simulate_sensors.py` | 11,784 |

Required outer files for Community Cloud:

Outer text-file sizes below describe this reviewed working tree. Git may
normalize their line endings without changing the packaged model; the ZIP and
its internal bytes must retain their exact recorded hashes.

| File | Bytes |
|---|---:|
| `streamlit_app.py` | 732 |
| `deployment_package.py` | 10,798 |
| `requirements.txt` | 109 |
| `requirements-person3-lock.txt` | 917 |
| `.streamlit/config.toml` | 110 |
| `deployment/package_manifest.json` | 4,203 |

The binary ZIP plus those six outer files total
**281,955 bytes**.
Keep `.gitattributes` in the release repository to protect the ZIP. Also include
`deployment_check.py` for smoke verification/Docker. `deployment/results_summary.json`
and the guides support review; historical results/corrections and buildings are
not required by the cloud runtime. Required artifacts are not ignored by Git.
No secrets file or API key is required. The allowlist excludes cache, personal
profiles, Git metadata and historical outputs; ignore rules protect `.env` and
`.streamlit/secrets.toml`.

## Dependency and environment checks

Fresh Windows Python **3.13.5** installation from the new standard
`requirements.txt` succeeded with binary wheels only. `pip check` passed in both
the original and fresh environment. All **45 exact Linux wheels**
resolved for CPython 3.13 x86_64 manylinux targets, totalling
**164,550,798 downloaded bytes** under ignored cache. This checks package
availability, not native Linux execution. Docker is absent and WSL reports it is
not installed; no system installation was attempted.

Key pins: Streamlit 1.66.0, pydeck 0.9.3, GeoPandas 1.2.0, Shapely 2.2.0,
pyproj 3.8.0, pyogrio 0.13.0, NetworkX 3.7, NumPy 2.5.4 and pandas 3.0.6.
The existing lock includes all transitive pins. Wheels supply the geospatial
native dependencies; an untested source GDAL build is not part of this plan.

The runtime uses pathlib/forward-slash archive paths and exact-case member names.
Its input paths are derived from extracted module locations, without absolute
Windows paths. Extraction writes temporary copies only; frozen source datasets
are read-only inputs. No persistent background sensor process is required.

## Clean packaged-runtime measurements

Measured locally in the new environment, not on cloud hardware:

| Check | Actual result |
|---|---:|
| Package verification/extraction | 0.306 s |
| Imports plus validated model ready | 7.989 s |
| Prepare 1,491 Heat Map links at 14:00 | 0.053 s |
| Both default real routes | 0.686 s |
| Load sensors and three fault replay states | 0.088 s |
| Fresh RM100,000 engine plan | 8.043 s |
| Repeated identical plan | 0.028 s |
| Four-tab AppTest after the preceding model calls | 2.443 s |
| Smoke-process peak working set | 198.67 MiB |

The AppTest timing above is warmed by preceding checks, not a cold UI startup.
Peak working set covers that one Python smoke process, excluding browsers and
other users; it is not a measured production-server or concurrency budget.
Backend checks ran while Linux wheels were downloading. Timings vary by host.
The earlier isolated backend benchmark is in final_results.md.

Reverified results: shortest **824.5 m**, coolest **826.3 m**, avoided
**9.283 degree-C-minutes**; **15 fixes**, **RM99,920 spent**, **RM80 left**,
**5,587.79224 person-degree-C-minutes/day** summed benefit. S01/13:05 is Anomaly;
S02/12:10 Missing, S02/12:30 Active. All match the reviewed model.

## Browser evidence

The actual **packaged entrypoint** ran in the fresh environment in headless
Chrome and Edge, at desktop size and **390 x 844** with touch/mobile emulation.
All four tabs were exercised, maps/charts captured, faults replayed, budgets
changed on desktop and mobile, previews displayed and tab isolation checked.
Neither final run reported page exceptions; CARTO responses returned HTTP 200.
Every mobile tab had document width 390 and viewport width 390 (no page overflow).
This is viewport emulation, not a physical-phone or cloud-network test.

| Browser timing | Chrome | Edge |
|---|---:|---:|
| Cold page through first RM100k result | 46.432 s | 33.804 s |
| Desktop budget RM0 | 4.340 s | 4.602 s |
| Desktop budget RM10k | 5.685 s | 5.408 s |
| Desktop restore RM100k | 3.762 s | 3.619 s |
| Mobile RM0 | 4.634 s | 3.914 s |
| Mobile restore RM100k | 4.410 s | 4.152 s |

Browser update timings include fixed automation settling waits; they are not
pure engine latency. Chrome cold startup overlapped the full suite; Edge did
not overlap it. Both used software WebGL and include front-end startup and
network/render work. Prewarm the app before a live three-minute demonstration;
cloud cold starts may be slower. Desktop hover and mobile pan/zoom have different
interaction affordances. Screenshots/helpers/logs remain under ignored cache:
`deployment-chrome-*.png`, `deployment-edge-*.png`, `deployment_browser_check.py`.

## Cloud-specific risks and approval gates

1. **No actual Linux/cloud execution yet.** Run the packaged smoke test on the
   real target and inspect native geospatial imports before distributing a URL.
   Do not launch normalized checkout `app.py` directly; use `streamlit_app.py`.
2. **Owner access unverified.** Git origin is `HRChiam/coolcorridor`; admin/private
   repository/organization access, app slot and app visibility need the owner's
   explicit action. No OAuth permission or repository setting was changed.
3. **Cold starts and quotas.** No multi-user load test or guaranteed cloud CPU/RAM
   allocation exists. Local memory/timings cannot certify hosted performance.
   Prewarm; use the local packaged app as fallback.
4. **Tiles and WebGL.** Browser access to CARTO and usable graphics are required
   for a basemap; model calculation itself does not require external services.
5. **Frozen release behavior.** Git changes to raw model files do not update the
   packaged snapshot. Review/rebuild a new package explicitly after changes;
   startup never regenerates models to bypass provenance.
6. **Scientific limits remain.** Sensors and calibration residuals are synthetic;
   costs, demand and intervention effects are illustrative, with no measured
   cooling or health claims. The exact all-eligible-trip mean is unavailable.

Recommended initial platform: Community Cloud, conditional on these gates.
An untested Docker alternative is prepared for an approved host if owner access
or measured hosting limits make Community Cloud unsuitable. No paid resources
were created. See deployment_guide.md for official sources, publishing steps,
private access, Python selection and container commands.

## Files changed during deployment preparation

Created: `requirements.txt`, `.gitattributes`, `.streamlit/config.toml`,
`deployment_package.py`, `streamlit_app.py`, `deployment_check.py`, `Dockerfile`,
`.dockerignore`, `tests/test_deployment.py`, `deployment/package_manifest.json`,
`deployment/coolcorridor-7e60744e872603ce7e33.zip`, `deployment/results_summary.json`,
`docs/deployment_guide.md`, `docs/hackathon_demo.md`, `docs/deployment_readiness.md`.
Modified: `.gitignore` and `README.md` only among pre-existing files.
Scientific/app implementation files and all old data/artifacts are preserved.

## Final automated and safety evidence

The exact requested complete command passed **239 tests in 130.16 seconds**,
including all 223 previous tests and 16 new deployment tests. No failure, skip
or expected failure remained in that final run. The deployment tests cover
byte-exact allowlist packaging, deterministic rebuilds, overwrite refusal,
missing/corrupt deployment artifacts, unsafe paths, extraction integrity,
corrupt internal correction provenance and first startup from a minimal checkout
with **no source data or cache directory**. The separate deployment-only run
passed 16 tests in 24.20 seconds.

An earlier full run exposed a Windows rename/sharing failure in the new
extraction code; bounded retries were added without altering model code. Another
run passed 238 tests and encountered the same kind of Windows filesystem failure
in the existing offline correction writer. That isolated test passed in 2.88
seconds on recheck, followed by the successful 239-test full run. Its numerical
code and reviewed artifacts were not changed. The deployment never invokes that
offline writer. Persistent filesystem errors are not hidden by the launcher.

Before/after comparison of all **112 pre-existing files** confirms only the
authorized `README.md` and `.gitignore` changed in this deployment phase. All
pre-existing app/model/test/data/result bytes remain intact. Git ignore checks
found no ignored required artifact. A limited allowlist scan found no private-key
or AWS-access-key pattern or absolute personal Windows path in the package;
this is not a comprehensive security audit. No app credentials are required.

Local evidence files: `cache/deployment-clean-check.json`,
`cache/deployment-linux-wheels.json`, `cache/deployment-safety-check.json` and
the per-browser screenshots/server logs. These are QA records, not deployment
inputs. Browser screenshots were visually inspected for actual maps, sensor
markers, route colors and preview charts, including mobile viewport layouts.
