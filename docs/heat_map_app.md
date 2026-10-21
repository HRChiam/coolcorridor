# Heat Map tab — Phase 4

The tab displays the actual walking network around Putra Heights LRT Station.
It opens at 14:00 and supports every whole hour from 07:00 to 19:00. All values
come from repository inputs and a validated offline correction bundle. App
rendering never generates corrections or writes shared data.

## Run and test

From the repository root in PowerShell, using the existing environment:

```powershell
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open http://127.0.0.1:8501 and select Heat Map. The current four-tab app starts
on Sensors; replay controls remain independent. Stop with Ctrl+C.
No new dependencies are required. For a fresh environment, install
`requirements-person3-lock.txt` as described in the README.

```powershell
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

Pytest resets only the specified temporary directory. If Windows denies access,
run the command as the Windows account that owns that directory. Tests include
the existing engine, sensor simulator and Cool Route suites.

## Sources and interfaces

| Input/interface | Use |
|---|---|
| `heat_model.heat.heat_at(hour)` | Hourly heat, uncorrected heat, shade, canopy, covered status, surface, albedo and actual walking geometry |
| `data/links.geojson` | Frozen baseline network, shade, surface attributes and real geometry |
| `heat_model.heat.design_weather()` | The replay date, currently 6 September 2026 |
| `data/sensor_links.csv` | All eight sensor IDs, link mappings and recorded longitude/latitude |
| `data/sensors_stream.csv` | Synthetic air temperature, humidity and surface readings |

The network has 1,491 links and includes gated-estate streets, as documented by
Person 1. It extends beyond the 800 m places catchment to keep paths connected.
Network geometry is normalized to EPSG:4326 before map paths are built. Both
paths and markers use `[longitude, latitude]`, never projected metre coordinates.
The camera is computed from the real walking network; no station coordinates or
temperatures are hardcoded into the visualization.

## Heat and correction labels

The plotted value is `heat_at(hour).heat`; `heat_model` remains the uncorrected
model in hover text. The shared reader validates a complete versioned correction
bundle selected by `data/corrections/current.json`, including hashes, design date,
all links/hours and baseline agreement. The same effective heat feeds the engine
and Planner. A damaged, partial or stale active bundle fails clearly; no bundle
or zero usable sensor coverage produces explicitly labelled baseline heat.

The active correction is derived offline from **SIMULATED** air readings. A
corrected source label identifies the bundle, not proof every link changed:
links outside all sensor influence areas retain zero correction. It does not
establish real-world heat accuracy. Input content and version keys invalidate
cached data. Baseline heat is still checked against the strict design weather.

The heat score is a simplified index combining air, sun, shade, wind and surface
reflectivity. Its units are expressed in degrees C, but it is **not measured air
temperature**, a clinical risk indicator, or live weather. Sensor air temperature
and surface temperature are distinct quantities and are labelled separately.

## Colors, legend and overlays

The color mapping is fixed across all hours. It linearly interpolates between
these design choices, without scaling to the current hour's minimum/maximum:

| Heat index | RGB |
|---|---|
| 26°C | 49, 54, 149 |
| 30°C | 69, 180, 195 |
| 34°C | 254, 224, 139 |
| 38°C | 244, 109, 67 |
| 44°C | 165, 0, 38 |

The visible gradient uses the same stops. Values outside 26–44°C use the nearest
end color; hover text retains actual numeric values. At 07:00 the baseline is
26.38°C, but simulated corrections introduce spatial differences. Some corrected
afternoon links exceed 44°C and use the red endpoint color without truncating
their tooltip values. See final_results.md for current summaries.

Overlay switches add outlines underneath the central heat-colored paths:

- Covered walkways: blue, only where `covered` is true.
- Tree canopy: green, where `canopy > 0`, with intensity related to canopy share.
- Shade: grey, where hourly `shade > 0`, with opacity proportional to shade.

These outlines show attributes, not simulated new interventions or individual
tree locations. When enabled together, their outlines overlap; the central line
always retains its heat color. Layer widths and marker radii are pixel-bounded.
Pydeck string constants use `pydeck.types.String` to preserve the purple-map fix.
The working keyless CARTO Positron basemap is retained and needs internet access.

## Sensor replay policy

All eight sites remain on the map when the sensor stream is absent or a recent
reading is missing. Markers are purple when a reading is available and grey
otherwise; hover text includes the sensor ID, site type and walking link.

For a chosen hour, use only readings on the design day at or before HH:00 local
time. The latest eligible reading is shown if it is at most five minutes old.
An exact-time reading is labelled **SIMULATED**; an earlier reading is explicitly
labelled **SIMULATED · stale (N min old)**. Older and future readings are withheld.
The five-minute allowance is a Person 3 display policy matching the stream's
sampling interval; it is not an agreed real-sensor fault-detection threshold.

For example, S02 has no reading at 12:00 because of its injected outage. The tab
shows its real 11:55 sample with a five-minute stale label. It does not use the
12:30 reading. At 13:00, it does not show S01's 13:05 spike. This phase displays
snapshots, not complete time-series charts or fault alerts.

## Summary definitions

- **Average link heat index:** arithmetic mean across all walking links, with
  equal weight per link. It is not a mean air temperature or population exposure.
- **Hottest walking link:** maximum displayed heat; all ties are counted and the
  lexicographically smallest link ID is displayed.
- **Network shade:** sum of link length times shade, divided by total link length.
- **Walking links:** number of links in the prepared network.

Toggles highlight attributes without filtering links, so summaries do not change
when overlays are enabled. They do update when the selected hour changes.

## Automated and manual checks

Tests cover actual hourly values, the fixed scale across all 13 hours, summary
formulas, sensor replay timing and missing data, correction labels, coordinates,
overlay membership, bounded layer sizes and literal enum serialization. AppTest
checks hour/toggle changes and confirms the Cool Route hour stays unchanged.
AppTest does not render WebGL; browser screenshots must also be inspected.

Phase 4 browser QA used the installed Chrome and Edge in headless mode with
software WebGL. Screenshots were inspected for the actual network, CARTO streets,
sensor markers, fixed legend, overlays, blue 07:00 colors and unchanged Cool Route
rendering. Mouse-driven overlay and hour changes were checked in both browsers.
QA screenshots and the local browser helper are in the ignored `cache/` folder;
no browser installation or new application dependency was needed.

In Chrome and Edge:

1. At 14:00, confirm streets, red/yellow heat links, eight labelled sensors,
   the fixed 26–44°C legend, and the uncorrected-model label.
2. Hover links for ID, index, shade, covered status, canopy, surface and albedo.
   Hover sensors for SIMULATED air/RH/surface values and timestamps.
3. Enable each outline and then all three; check that central heat colors remain.
4. Move to 07:00: links should become blue, with corrected spatial variation,
   while legend endpoints stay unchanged. Check 19:00 as well.
5. At 12:00, inspect S02's stale 11:55 sample. Pan and zoom to check marker sizes.
6. Return to Cool Route; confirm the real default routes and 14:00 metrics still
   work, independently of the Heat Map slider.

## Remaining limitations

The integration gaps found in Phase 7 are repaired; see
[full integration repair](full_integration_repair.md). Scientific limits remain:
synthetic offsets, estimated canopy/surfaces, eight-site spatial coverage, a
simplified heat index and no field validation. Marker snapshots show only causal
raw readings; offline centred calibration windows can include later samples and
must not be described as live nowcasting.
