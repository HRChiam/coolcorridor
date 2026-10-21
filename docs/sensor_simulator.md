# Person 3 sensor simulator

This phase implements a batch generator, not a running sensor service or the
Streamlit app. **All readings are simulated data.** It reads the existing eight
sites and the prepared heat-model inputs without updating them.

## Setup and baseline

Tested on Windows with Python 3.13.5. From the repository root in PowerShell:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-person3-lock.txt
.venv\Scripts\python.exe -m pip check
.venv\Scripts\python.exe -B -m pytest tests/test_engine_person2.py -q -p no:cacheprovider
```

`.venv` is ignored by Git. `requirements-person3.txt` declares the Person 3
dependencies and includes Person 2's requirements. `requirements-person3-lock.txt`
records the full installed environment, including transitive dependencies, for
reproduction. Streamlit and pydeck are installed for the approved later app phase.
The simulator itself uses pandas, NumPy and Person 1's GeoPandas-based reader.
`tzdata` supplies named timezones on Windows. OSMnx, pvlib and online API calls
are not required to run this generator with the committed model data.

Use `-B` to avoid creating Python bytecode files in teammate-owned folders.
`-p no:cacheprovider` avoids a pytest cache in the repository; test outputs go
to pytest's temporary directories.

## Generate and inspect

```powershell
.venv\Scripts\python.exe -B simulate_sensors.py
Get-Content data/sensors_stream.csv -TotalCount 10
Import-Csv data/sensors_stream.csv | Group-Object sensor_id | Select-Object Name,Count
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
```

The default output is `data/sensors_stream.csv`. Its exact columns are:

```text
sensor_id,link_id,timestamp,air_temp_c,rh_pct,surface_temp_c,source
```

There are 145 scheduled readings per sensor, inclusive of 07:00 and 19:00 on
6 September 2026: 1,160 rows before faults. The default outage omits six rows,
giving **1,154 rows**: S02 has 139 readings and every other sensor has 145.
Each timestamp includes `+08:00`, temperatures and humidity have three decimal
places, and `source` is always `simulated`. Rows are ordered by timestamp, then
sensor ID. Existing sensor CSVs can be regenerated; a non-sensor CSV is refused
to protect other data contracts.

## Inputs and calculation

- `data/sensor_links.csv`: IDs, link mapping and offsets, unchanged.
- `heat_model.heat.design_weather()`: only design-day rows, never forecast rows.
- `heat_model.heat.heat_at(hour)`: each sensor link's hourly shade and albedo.

Weather air temperature, relative humidity and sunlight are linearly interpolated
between hourly samples. Shade uses the reading's whole local hour (13:55 uses
hour 13; 14:00 uses hour 14). Covered S05 remains fully shaded.

```text
air_temp_c = interpolated model air + site offset + uniform air noise
rh_pct = clip(interpolated humidity + uniform humidity noise, 0, 100)
surface_temp_c = air_temp_c
                 + (1 - shade) * interpolated sunlight / 1000 * 25 * (1 - albedo)
                 + uniform surface noise
```

Surface temperature is distinct from the heat score. Later sensor charts should
compare sensor air with weather air, as explained in the app guide.

## Provisional settings

Edit `config/sensor_simulation.json`, or pass a copy with `--config`. Omitted
fields use the defaults in `SimulationConfig`; unknown fields are rejected.

| Setting | Default and meaning |
|---|---|
| `seed` | `20260906`; deterministic NumPy random generator |
| `offset_overrides_c` | `{"S08": 0.5}`; other sensors use the shared site's offset |
| `air_noise_c` | Uniform noise from -0.3 to +0.3 degrees C |
| `rh_noise_pct` | Uniform noise from -2 to +2 percentage points |
| `surface_noise_c` | Independent uniform noise from -1 to +1 degrees C |
| `silent_sensor` | `S02` |
| `silent_start` | `12:00`, inclusive local time |
| `silent_minutes` | `30`; end excluded, so 12:30 is present |
| `spike_sensor` | `S01`; must differ from the silent sensor |
| `spike_time` | `13:05`; one reading only |
| `spike_delta_c` | Add `8.0` to both air and surface, leaving humidity unchanged |

These fault choices, the distribution, and all local offsets are assumptions.
In particular, S08's grass-verge +0.5 degrees C remains provisional. An override
such as `{"S08": 0.8}` changes its offset without editing `sensor_links.csv`.
Sensor IDs must exist, noise amplitudes must be nonnegative, and faults must
align to the five-minute schedule. Silence must end by 19:00. Set all three
noise amplitudes to zero for a noise-free formula check.

The CSV keeps the seven-column contract; injected faults are documented here
and in the JSON rather than adding a fault-label column. Detection thresholds
and app alerts remain for a later phase.

For experiments that preserve the default output, write to a temporary folder:

```powershell
.venv\Scripts\python.exe -B simulate_sensors.py --no-faults --output "$env:TEMP\coolcorridor-no-faults.csv"
.venv\Scripts\python.exe -B simulate_sensors.py --seed 42 --output "$env:TEMP\coolcorridor-seed42.csv"
.venv\Scripts\python.exe -B simulate_sensors.py --config config/sensor_simulation.json --output "$env:TEMP\coolcorridor-custom.csv"
```

Noise draws happen before faults. Thus, with the same seed/config, disabling
faults restores the six omitted rows and removes the one spike, while leaving
every other reading unchanged.

## Check reproducibility

Use the same input files, config and locked environment. These two hashes should
match; the command intentionally regenerates the default sensor output twice:

```powershell
.venv\Scripts\python.exe -B simulate_sensors.py
$firstHash = (Get-FileHash data/sensors_stream.csv -Algorithm SHA256).Hash
.venv\Scripts\python.exe -B simulate_sensors.py
$secondHash = (Get-FileHash data/sensors_stream.csv -Algorithm SHA256).Hash
$firstHash -eq $secondHash
```

Tests cover timing, mapping, formulas, hourly shade changes, noise bounds,
humidity clipping, repeatability, configurable offsets/faults, invalid inputs,
CSV writing, Person 2's latest-reading adapter, and Person 1's correction reader.
The real-data test checks shared input bytes remain unchanged.

## Later handoff to Persons 1 and 2

The output can be read by `engine.latest_sensors()` and the existing correction
reader. The tests exercise both without running correction or changing engine
code. A 30-minute gap does not necessarily eliminate a whole sensor-hour: with
these defaults all 104 sensor-hour medians still have readings.

Heat correction is **not run in this phase**. Coordinate its ownership and the
known corrected-heat/weather/shade-gain integration issues with Persons 1 and 2
before regenerating shared heat or planner outputs. The correction script writes
`links.geojson` and `sensor_validation.csv`; running it is a separate handoff.
No Git commit or push is part of the simulator phase.
