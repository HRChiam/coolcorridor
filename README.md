# CoolCorridor

Heat-aware walking routes and cooling intervention planning around Putra Heights
LRT. The repository contains the heat model (Person 1), routing and planner
(Person 2), and the synthetic sensor generator and Streamlit + pydeck Cool Route,
Heat Map, Sensors and Planner tabs (Person 3).

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
readings are labelled. Current heat is **uncorrected model heat**, not measured
air temperature. All tabs have independent replay controls.

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
Start at **RM100,000** to see 14 selected shade-tree interventions costing
**RM99,584**, leaving **RM416**. Estimated daily exposure saving is
**5,561.765 person·°C·minutes/day**, using uncorrected model heat and assumed
walking demand. Change the budget to recalculate the greedy allocation; hover
the highlighted walking links for costs and benefits. Select a link and
improvement, then press **Preview intervention** for real engine hourly
before/after projections. Previews are independent of the selected budget plan
and do not write data. The standalone engine took about 10 seconds locally;
uncached app requests can take longer, especially during browser automation.
Unchanged inputs are cached in memory.

See [the Planner guide](docs/planner_app.md) for the actual algorithm, cost
assumptions, unit definitions, current weather/corrected-heat limitations and
verification steps. The existing environment and launch command support all
four tabs; no additional dependencies are needed.

Phase 7 integration status is **PARTIAL**. The app now validates shared
heat/weather inputs, detects stale Heat Map attributes, and isolates tab
interactions. The audit found an engine place-to-junction snapping problem,
mixed-date planner radiation and missing corrected-heat integration. See
[the integration QA handoff](docs/integration_qa.md) for evidence, owners,
suggested interfaces, test/browser results and deployment blockers. Current
route and investment numbers are the unchanged engine outputs and need
re-baselining after Person 2 fixes snapping; they are not validated field results.

Run the full suite, including Streamlit interaction tests:

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

Pytest resets the named temporary directory, which is ignored by Git. If Windows
reports access denied, run the command from the same Windows account that owns
that folder. See [the Cool Route guide](docs/cool_route_app.md) for manual checks,
metric definitions and current engine integration limits.

## Person 3: sensor simulator

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
