# Sensors Dashboard — Phase 5

The Sensors tab reads the committed synthetic sensor CSV. It adds no sensor
hardware connection, writes no readings, and does not run heat correction.
Heat Map, Cool Route and the simulator remain available and unchanged in function.
The existing `engine.latest_sensors()` has no replay cutoff, and Heat Map's
snapshot accepts whole hours. A separate read-only adapter supplies five-minute
dashboard replay without changing either existing interface.

## Launch and test

From the repository root in PowerShell:

```powershell
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open http://127.0.0.1:8501. Sensors is the initial tab; stop with Ctrl+C. Existing
dependencies already include Altair, Streamlit and pydeck, so no install is
required for this phase. For a fresh environment use the README setup commands.

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

Pytest resets the specified temporary directory. Use the Windows account that
owns that directory if Windows denies cleanup. All existing suites are included.

## Inputs and provenance

| Input | Purpose |
|---|---|
| `data/sensors_stream.csv` | 1,154 actual generated rows with sensor/link IDs, timestamp, air temperature, relative humidity, surface temperature and source |
| `data/sensor_links.csv` | Eight real site coordinates, link IDs and site descriptions |
| `data/weather.csv`, `day == design` | Hourly weather air for 6 September 2026; forecast rows are excluded |
| `config/sensor_simulation.json` | Configured seed and known injected-fault intent |

Sensor timestamps must be timezone-aware, unique per sensor, and aligned to
five-minute steps. Values must be finite; humidity must be 0–100%. Source must
be `simulated`, and sensor/link mappings must agree with the site file. Invalid
contracts produce a clear error. Valid rows outside the design-day replay
window are excluded with a notice. All locations come from the site CSV as
EPSG:4326 `[longitude, latitude]` coordinates.

The current configuration specifies seed **20260906**, S02 silent from **12:00
inclusive to 12:30 exclusive**, and one **+8°C** air/surface spike on S01 at
**13:05**. These are configuration metadata, not independent evidence that a
particular CSV was generated with those options. The CSV does not include a
generation manifest. Editing the JSON does not change the CSV, and the dashboard
never regenerates it. Missing configuration hides fault annotations and reports
that limitation; it does not prevent observed-data replay or anomaly detection.

## Replay semantics

The selector covers **07:00 through 19:00 inclusive**, every five minutes, in
`Asia/Kuala_Lumpur`. Default is **13:05**, sensor **S01**, to demonstrate the
actual spike. All snapshot statuses use selected replay time, never the current
wall-clock date. No future or next-day sample is used for a snapshot.

History normally ends at replay time. **Show full design-day history** explicitly
includes later observations as a retrospective overview. That option changes
charts and the selected-sensor readings table only; snapshot statuses, selected
sample values and detected-event counts remain as of replay time.

## Status rules — provisional demonstration choices

| Status | Rule at the selected replay instant |
|---|---|
| Active | Exact-time sample; no detected air anomaly |
| Anomaly | Exact-time sample whose independently computed detector flag is true |
| Stale | Last observed sample is 5 or 10 minutes old |
| Missing | No prior sample, or the last sample is more than 10 minutes old |

Freshness takes precedence over an old anomaly: a past anomalous sample is not
reported as a current anomaly during a later gap. Stale values are shown with
their actual sample timestamp and age. Missing values are withheld while the
last-seen timestamp remains available. All eight sites stay on the map even
when there are no readings. Green means Active, amber Stale, grey Missing and
red Anomaly; the selected marker is slightly larger but pixel-bounded.

These thresholds are UI/demo assumptions, not validated physical sensor service
levels. Heat Map retains its separately documented five-minute snapshot policy.

## Independent anomaly detector

For each sensor reading, interpolate **design-day weather air temperature** at
that exact time and calculate:

```text
weather_delta = sensor air - weather air
baseline_delta = median(weather_delta in the previous 30 minutes)
detected departure = weather_delta - baseline_delta
anomaly = abs(detected departure) > 3 degrees C
```

The baseline excludes the current sample and all future samples. At least three
prior observations in the window are required. The first three samples and
recovery periods with too little recent history are detector warm-up; lack of a
flag there is not proof of normal operation. A stable local offset is absorbed
by the per-sensor baseline rather than incorrectly treated as a fault.

The detector uses **no configured fault time, sensor ID, seed or spike magnitude**.
With the current CSV it detects one event, S01 at **13:05**: air **43.738°C**,
weather air **34.475°C**, and departure **+7.6825°C** from the trailing residual
median. The configured +8°C injection differs from the observed departure
because the underlying synthetic weather/noise values also change. The detected
table reports observed departure, not a hardcoded +8°C measurement.

Surface temperature and humidity are displayed, but only air has an anomaly
detector in this phase. This simple threshold can miss slow drift or early
spikes and is not a production calibration or health-risk model.

## Charts, faults and missing samples

- Air chart: orange sensor air, dashed blue weather air, red detected points.
- Humidity chart: percent relative humidity.
- Surface chart: degrees C, separate from air and the heat score.
- Purple dashed rule: configured spike. Amber band: configured silent interval
  for the selected sensor. These annotations describe intent, not detection.

Hourly weather air is linearly interpolated to five-minute steps. Sensor values
are never interpolated. Missing slots remain null, and line segments are split
so a line does not bridge an outage. At 12:10, S02 is Missing with last-seen time
11:55; its six absent samples are visible in full-day history, and it is Active
again at 12:30. S01's status returns to Active at 13:10, while its detected event
remains in the as-of event history.

Internal timestamps are timezone-aware and tables retain `+08:00`. Chart scales
represent actual instants in UTC, with axis labels explicitly formatted as UTC+8
so the labels remain Malaysian local time even in a different browser timezone.
The formatter converts date values to numeric timestamps before applying the
offset, using [Vega's date functions](https://vega.github.io/vega/docs/expressions/).
There is **no comparison with Person 1's modelled heat score**.

## Tables and summaries

Summary counts show current samples (Active plus Anomaly), stale/missing sites,
current anomalies, and all detected events up to replay time. The selected-sensor
cards show air, humidity and surface values. Tables provide all-site status and
last-seen timestamps, detected-event time/magnitude, configured faults, and the
selected sensor's observation grid. Null slots are retained in the history table.

If the stream is missing or contains only headers, locations/weather remain
available with Missing statuses; no fake measurements are inserted. Missing
weather or invalid CSV structure produces an error isolated to Sensors.

## Verification

Automated tests cover real input values, timezone parsing, weather interpolation,
replay bounds, outage/recovery, causal anomaly detection, independence from
configuration, gap preservation, full-day filtering, missing streams, invalid
contracts, map serialization and previous-tab integration. AppTest does not
render WebGL or charts; browser verification must also be performed.

Phase 5 QA inspected actual rendered charts/maps in installed Edge and Chrome
using headless software WebGL. Chrome replay interactions verified S02's Missing
state at 12:10, the full-day gap, and Active recovery at 12:30. The corrected
local-time axis labels and S01 spike were visually inspected in both browsers.
Screenshots and the local browser helper are under ignored `cache/`, including
`map-phase5-edge-spike-charts.png` and `map-phase5-chrome-outage-charts.png`.
The historical Phase 5 suite passed 105 tests, including all 75 previous tests.
Current complete integration results are in [full_integration_repair.md](full_integration_repair.md).

Manual demonstration checks:

1. At S01 / 13:05, inspect the red marker, air spike and detected +7.6825°C event.
2. Expand the rules/fault section: distinguish that event from configured +8°C.
3. Select S02 at 12:00 (Stale), 12:10 (Missing), then 12:30 (Active).
4. Enable full-day history and inspect the 12:00–12:25 missing slots and chart gap.
5. Verify air is compared with weather air and hover timestamps include +08:00.
6. Switch to Heat Map and Cool Route and verify their independent controls/maps.

Known limitations are the provisional detector/freshness thresholds, no automatic
CSV/config provenance check, synthetic-only data, and internet-dependent CARTO
basemap tiles. No live streaming, automatic correction or real-sensor claims are
made. Planner is now available; see [the full integration repair](full_integration_repair.md)
for current system-wide limitations. Phase 7 validates simulation configuration
before creating fault annotations: invalid configuration produces a warning and
omits those annotations while actual CSV-based detection remains operational.

The offline correction pipeline now uses the same causal air-residual anomaly
detector before aggregation, independently of fault annotations. It writes a
versioned audit and calibrates the model heat index; this dashboard continues to
show the untouched raw simulated air, humidity and surface readings. In particular,
S01's spike and S02's outage remain visible. Calibration uses centred hourly
windows offline; dashboard snapshots and statuses remain causal at replay time.
