# COOLNEX rebranding review

Review date: **22 October 2026, Asia/Kuala_Lumpur**.
The official project name is **COOLNEX**. The former name appears in this review
only to explain intentional compatibility and historical exceptions.

## Git and scope

Started with a clean working tree. Local `main`, `origin/main` and GitHub's
read-only `ls-remote` result agreed on
`cc00c2430c88c9e09dfc1c58f6e7d6ecc4c85d5c` (merged PR #2).
Created `rebrand-coolnex` from that commit. No commit, push, merge, remote rename,
repository rename or deployment was performed.

This is a branding-only change. The visible Streamlit browser title and H1
are both exactly `COOLNEX`. All four existing tabs, layouts, CARTO maps,
SIMULATED labels and scientific limitations remain. Person 2's CLI help and
heading also use COOLNEX. Active Markdown headings and demo narration use the
new brand. Docker example tags and temporary example output names use lowercase
`coolnex` as technical identifiers, rather than uppercase Docker repository names.

The following inspected modules needed no edits: `streamlit_app.py`,
`cool_route.py`, `heat_map.py`, `sensors_dashboard.py`, `planner.py`,
`app_data.py`, `simulate_sensors.py`, Streamlit config, requirements and Docker
configuration. They contain no obsolete visible project branding that requires
a change. Technical compatibility tokens are explained below.

## Deployment and scientific integrity

The deployment entrypoint still verifies and extracts a byte-preserving ZIP.
An app-source edit alone would leave the cloud app running the previous title,
so a **new immutable snapshot** was built using the existing packaging process:

- Active package: `deployment/coolcorridor-c9a128054ca0eaff5c1d.zip`.
- Compressed size: **284,060 bytes**.
- SHA-256: `d40025a42e5a3ab8ef66c5de7165e57f4eab6ac808dee7b80708c0112fcf10ca`.
- Active selection: `deployment/package_manifest.json`.
- Previous selection preserved byte-for-byte in
  `deployment/archive/package_manifest-f5d9e8d1e2f6a281ec6c.json`.
- Existing ZIPs were not renamed, rewritten or deleted. The legacy filename
  prefix and extraction directory are preserved compatibility identifiers.

Only **`app.py` differs among the 24 runtime members**. The other 23 payloads
are byte-identical to the previous reviewed snapshot, including the complete
engine, heat implementation, data, configuration, correction pointer, correction
manifest and all corrected numerical outputs. The outer deployment manifest
records the changed application bytes; no correction manifest or correction
hash was edited. The correction version remains
`v1-20260906-2c6bce708d14c832`.

SHA-256 checks against the pre-edit baseline verified **116 protected existing
files unchanged**, including every tracked data file, heat module, routing and
planner module, simulator, requirements, original ZIP/archive and relevant
runtime/deployment configuration. Baseline and audit evidence are local ignored
QA files under `cache/coolnex-rebrand/`; production does not depend on them.

The merged-model results remain 6 RM100k interventions, RM99,818 build spending,
RM182 remaining, 7,084.471 horizon-average daily modelled exposure avoided,
36.74% demand-weighted trips with a cooler route, and default route distances
824.5/826.3 m. These are preserved results, not new scientific claims. Sensors
are SIMULATED; the heat index is modelled; investment costs are illustrative.

## Remaining old-name audit and reasons

The audit searched tracked text and artifact paths case-insensitively for
`CoolCorridor`, `COOLCORRIDOR`, `coolcorridor`, `Cool Corridor`, `cool corridor`
and `cool-corridor`. It also inspected the active ZIP and compared every member
with the previous package. Binary archives, Git history, local virtual
environment files, ignored historical screenshots/logs and cache files are not
rewritten merely to erase old branding.

| Classification | Remaining locations | Reason |
|---|---|---|
| B: internal identifier | `engine.py`, `deployment_check.py`, `tests/test_deployment.py`, `docs/deployment_guide.md` | Preserve `COOLCORRIDOR_DATA_DIR`, the supported data-directory environment variable. The normal app UI no longer displays its old-brand spelling. |
| B: internal paths | `.gitignore`, README and the Cool Route, Heat Map, Sensors, Planner, simulator, integration, deployment and merge guides | Preserve `.pytest_coolcorridor_temp`, including the exact requested verification command. |
| B: package/runtime identifiers | `deployment_package.py`, active/archived deployment manifests, deployment/readiness/merge guides and this review | Preserve `coolcorridor-<content hash>.zip` and `coolcorridor-runtime`; do not rename existing artifacts or runtime paths. |
| C: frozen source description | `engine.py` first-line docstring | Historical module description retained while preserving the reviewed scientific source byte-for-byte; it is not displayed by the application. |
| C: frozen research provenance | `data/results/integration-156845bcd5e3a50beedf/results.json`, `integration-2548cfb50721d28596d5/results.json`, `integration-7bc2cfed0119ae14be33/results.json`, `integration-ceac3f6ae7b8ad8f3c3c/results.json` | Original recorded Windows workspace paths contain the old directory name. They are immutable historical provenance, not current branding. |
| C: previous releases | Existing deployment ZIPs and `deployment/archive/` | Preserve original bytes, titles inside archived apps, filenames and manifest references. Only the active new snapshot displays COOLNEX. |
| D: external identity | `docs/deployment_guide.md`, `docs/deployment_readiness.md`, Git origin | `HRChiam/coolcorridor` is still the actual repository. Changing these references would falsely imply an owner-approved repository rename. |
| C: explanatory history | This review | Names and paths here identify the former brand and intentional exceptions, rather than current app branding. |

No current user-facing app or CLI project title retains the old brand. Generic
tab names such as Cool Route are feature names and remain unchanged.

## Validation

The exact requested command passed: **255 passed in 240.24 seconds** (253
existing cases plus two new branding regressions):

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

The new tests check both local and packaged page titles, and independently
compare every runtime payload against the previous reviewed package. The
isolated cloud-entrypoint AppTest now also checks the COOLNEX H1. Existing
scientific/integration tests remain intact. CLI `person2_results.py --help`
shows COOLNEX without running exports or changing source data.

Actual installed **Chrome and Edge**, driven headlessly through CDP, both
verified the packaged app on the requested localhost port 8501: browser title
and heading COOLNEX, four working tabs, no visible former branding or Streamlit
exceptions, successful CARTO tile responses (HTTP 200), real maps, default route
heat avoidance 9.283, and Planner RM99,818 / 6 selections. Screenshots were
captured and inspected for headings, maps, sensor status and Planner metrics.
390 x 844 mobile emulation passed across all four tabs in both browsers;
viewport and document widths were both 390 pixels, with no horizontal overflow.
This is **not physical-phone or cloud verification**.

The first Edge automation attempt checked its canvas before asynchronous map
rendering completed. A readiness wait corrected the harness; both browsers then
completed the full check. No application change was needed for that timing issue.
All test-owned server/browser processes were stopped; no pre-existing server
was displaced.

Evidence: `cache/coolnex-rebrand/browser-results.json`, protected-integrity and
audit JSON, plus per-browser screenshots. Example screenshots:
[Chrome heading](../cache/coolnex-rebrand/chrome-heading.png),
[Edge route map](../cache/coolnex-rebrand/edge-cool-route-map.png),
[Edge mobile Planner](../cache/coolnex-rebrand/edge-mobile-planner.png).
These are ignored local evidence, not deployment inputs.

## Launch locally

From the repository root:

```powershell
.venv\Scripts\python.exe -B deployment_package.py
.venv\Scripts\python.exe -B -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open `http://127.0.0.1:8501`. Verify the browser tab and main heading read COOLNEX,
then inspect Heat Map, Cool Route, Sensors and Planner. Test the S01 spike and
S02 outage replay, corrected-source labels, 13-hour heat scale, route metrics,
Planner horizons and RM100k spending. Do not regenerate any source datasets.

## Possible owner actions, not performed

Proposed repository name: `HRChiam/coolnex`.
Proposed Streamlit address: `coolnex-sdp.streamlit.app`.
Neither name's availability nor ownership has been verified. These are proposals,
not existing renamed or deployed resources. The repository owner must separately
approve and check availability, redirects, remotes, integrations and Streamlit
settings before changing an external identity.

After explicit approval, review and publish this branch with:

```powershell
git status
git diff --check
git add -- README.md app.py person2_results.py docs tests/test_branding.py tests/test_deployment.py deployment/package_manifest.json deployment/archive/package_manifest-f5d9e8d1e2f6a281ec6c.json deployment/coolcorridor-c9a128054ca0eaff5c1d.zip
git diff --cached --stat
git diff --cached --check
git commit -m "Rebrand application and documentation as COOLNEX"
git push -u origin rebrand-coolnex
gh pr create --base main --head rebrand-coolnex --title "Rebrand project as COOLNEX" --body "Branding-only update. Scientific algorithms, validated datasets and correction artifacts preserved. See docs/rebranding.md for audit, tests and browser verification."
```

Review the staged diff before committing; do not include unrelated future changes.
PR creation does not authorize merging or deployment.

## Complete repository file changes

- `README.md` (modified)
- `app.py` (modified)
- `deployment/package_manifest.json` (modified)
- `docs/assumptions.md` (modified)
- `docs/deployment_guide.md` (modified)
- `docs/deployment_readiness.md` (modified)
- `docs/final_results.md` (modified)
- `docs/full_integration_repair.md` (modified)
- `docs/hackathon_demo.md` (modified)
- `docs/merge_resolution.md` (modified)
- `docs/sensor_simulator.md` (modified)
- `person2_results.py` (modified)
- `tests/test_deployment.py` (modified)
- `deployment/archive/package_manifest-f5d9e8d1e2f6a281ec6c.json` (new)
- `deployment/coolcorridor-c9a128054ca0eaff5c1d.zip` (new)
- `docs/rebranding.md` (new)
- `tests/test_branding.py` (new)
