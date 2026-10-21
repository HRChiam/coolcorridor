# CoolCorridor

Heat-aware walking routes and cooling intervention planning around Putra Heights
LRT. The repository contains the heat model (Person 1), routing and planner
(Person 2), and the synthetic sensor generator and Streamlit + pydeck Cool Route
tab (Person 3).

## Launch the Cool Route app locally

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
