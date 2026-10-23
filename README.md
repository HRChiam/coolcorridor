# COOLNEX

**Live app: https://coolnex.streamlit.app/**

> Official project brand: **COOLNEX**. See the [rebranding review](docs/rebranding.md) for the active deployment snapshot and intentional compatibility/historical exceptions.

Current merge review: [resolved integration and updated results](docs/merge_resolution.md). Planner now uses safety-aware demand, horizon benefits and the budget optimizer from main. Historical numerical examples below are superseded by this report.

Heat-aware walking routes and cooling intervention planning around Putra Heights
LRT. The repository contains the heat model (Person 1), routing and planner
(Person 2), and the synthetic sensor generator and Streamlit + pydeck Cool Route,
Heat Map, Sensors and Planner tabs (Person 3).

## Deployment

The app is deployed on Streamlit Community Cloud at
**https://coolnex.streamlit.app/**, from the `main` branch of `HRChiam/CoolNex`
with Python 3.13.

Use **`streamlit_app.py` as the cloud entrypoint**. It verifies and extracts the
reviewed binary package, preserving the exact source/data bytes required by the
correction manifest even after Linux Git checkout. It runs the same real app;
no model or sensor regeneration occurs. `app.py` below remains the development
entrypoint. To check the package locally before a redeploy:

```powershell
.venv\Scripts\python.exe -B deployment_package.py
.venv\Scripts\python.exe -B deployment_check.py --app-test
.venv\Scripts\python.exe -B -m streamlit run streamlit_app.py --server.address=127.0.0.1 --server.port=8501
```

The ZIP is **284,060 bytes**, containing 24 runtime files and the active corrected
bundle. See [deployment readiness](docs/deployment_readiness.md) and the
[deployment guide](docs/deployment_guide.md), and rehearse the
[three-minute demo](docs/hackathon_demo.md). Redeploying needs the repository
owner (private-repository access) and Python 3.13. Any change to the runtime
needs a rebuilt package before it appears online.

Do not run data-generation scripts to make startup work, upload ignored caches,
or publish a different model silently. See `deployment/package_manifest.json`
for every required runtime path, size and SHA-256.

## Launch the app locally

From the repository root in PowerShell, using the existing `.venv`:

```powershell
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open **http://localhost:8501** in your browser. Stop the server with **Ctrl+C**.
For a fresh environment, follow the dependency installation commands below first.

The default route is the real **99 Speedmart (P043)** to **Putra Heights LRT
Station (P066)** at **14:00**, replaying the design day. Select any listed places
and an hour from 07:00 through 19:00. Both route options are calculated by
`engine.route()` and drawn from its returned walking-link geometry. The app
shows route metrics, comparison, map tooltips and visibility toggles. Route
calculations use local files; CARTO basemap tiles need internet access.

The **Heat Map** tab shows the actual 1,491-link network at 14:00.
Move the replay-hour slider from 07:00 to 19:00; the heat legend stays fixed at
26–44°C. Optional outlines highlight covered walkways, canopy and shade. Hover
links and the eight sensor markers for details. Sensor readings are explicitly
**SIMULATED**, selected at or before the chosen replay time; stale and missing
readings are labelled. All three model tabs share the same validated effective
heat index, using offline **SIMULATED** sensor corrections when activated, with
explicit baseline fallback. This is not measured air temperature. All tabs have
independent replay controls.

Read [the Heat Map guide](docs/heat_map_app.md) for source data, aggregation,
overlay definitions, limitations and visual verification steps. No additional
dependencies or startup commands are needed for this phase.

The app opens on **Sensors** at **13:05**, showing the actual S01 injected spike.
Replay 6 September 2026 in five-minute steps, select any sensor, and view its
air-versus-weather, humidity and surface-temperature histories. Active, Stale,
Missing and Anomaly statuses are computed against replay time. Sensor samples
remain explicitly **SIMULATED DATA**; no correction or regeneration runs.

For the outage demonstration, choose **S02** at **12:10**, then enable full-day
history to see the six-sample gap and 12:30 recovery. The full-day option may show
future history, but statuses and event counts remain tied to replay time.
See [the Sensors Dashboard guide](docs/sensors_dashboard.md) for detection rules,
configured fault annotations, provenance limitations and verification steps.

The fourth tab, **Planner**, calls Person 2's actual `engine.priorities(budget_rm)`.
Start at **RM100,000** to see actual selected interventions, remaining budget
and modelled daily exposure savings. Change the budget to recalculate the best
combination of fixes (an exact search, at most one fix per link); hover highlighted links for costs and benefits. Select a link and
improvement, then press **Preview intervention** for real hourly before/after
projections. Previews do not change data. Demand and candidate calculations are
reused across budgets using content and correction-version keys.

See [the Planner guide](docs/planner_app.md) and
[recomputed results](docs/final_results.md) for actual numbers, units and timings.
The historical Phase 7 results were superseded by the integrated repair:
authoritative place IDs, orientation-independent junction coordinates, strict
6 September 2026 weather, a versioned correction pipeline, and user-approved
proportional shade gains. [Repair and QA details](docs/full_integration_repair.md)
explain the algorithms and remaining modelling limitations. No field validation
or deployment is implied.

## Offline correction and reproducible results

The app only reads existing outputs. It does not regenerate sensors, apply
corrections automatically or modify the frozen network. The activated bundle is
selected by `data/corrections/current.json`; every output and source input is
validated. No bundle means clearly labelled baseline-only operation; a damaged
or stale bundle produces an error.

```powershell
# Explicit offline operation: creates/verifies a separate immutable version.
.venv\Scripts\python.exe -B -m heat_model.sensor_correction --activate

# Reproduce all-day route, demand, heat, allocation and benchmark results.
# The default new data/results/<version>/ destination refuses overwrite.
.venv\Scripts\python.exe -B integration_results.py
```

Existing correction versions are preserved. Repeating identical correction
inputs verifies the existing bundle. A different active version is never
silently replaced; review and archive/change the derived pointer explicitly.
Results can be rerun with `--output` pointing to a new unused directory. Do not
run `heat_model/run_all.py`, `heat_model/heat.py` or `person2_results.py` simply to
view the app: those older generation/export commands can replace canonical
outputs. Use `integration_results.py` for this repair's separate reports.

Run the full suite, including Streamlit interaction tests:

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

Pytest resets the named temporary directory, which is ignored by Git. If Windows
reports access denied, run the command from the same Windows account that owns
that folder. See [the Cool Route guide](docs/cool_route_app.md) for manual checks,
metric definitions and current engine integration limits.

## Sensor simulator

Run these PowerShell commands from the repository root. You do not need to
activate the environment when using its Python executable directly.

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-person3-lock.txt
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
.venv\Scripts\python.exe -B simulate_sensors.py
```

The generator writes `data/sensors_stream.csv`: **simulated data**, replaying
6 September 2026. Defaults produce 1,154 readings across the existing eight sites,
including one provisional outage and one spike. It does not update heat outputs.

Read [the simulator guide](docs/sensor_simulator.md) for configuration, formulas,
fault details, reproducibility checks and the later correction handoff.

Other project documentation:

- [App and sensor data contract](docs/app_and_sensors_guide.md)
- [Heat model integration](docs/heat_model_guide.md)
- [Assumptions and provisional inputs](docs/assumptions.md)
