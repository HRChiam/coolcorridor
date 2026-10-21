# Cool Route local app

The four-tab app includes Cool Route, Heat Map, Sensors and Planner. `app.py` renders the Streamlit controls and results;
`cool_route.py` handles place labels, calling the existing engine, validating
results and creating pydeck layers. No route or model output is written.

## Launch

From the repository root in PowerShell:

```powershell
# Only needed for a fresh environment:
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements-person3-lock.txt

# Start the app:
.venv\Scripts\python.exe -B -m streamlit run app.py --server.address=127.0.0.1 --server.port=8501 --browser.gatherUsageStats=false
```

Open http://localhost:8501. Keep the terminal open while using the app. Press
Ctrl+C in that terminal to stop it. No activation script or API key is needed.
The app reads local files, while the CARTO street basemap needs internet access.
If port 8501 is occupied, use `--server.port=8502` and open that port instead.

## Defaults and interactions

- Origin: **99 Speedmart**, the real shop `P043` in `data/places.geojson`.
- Destination: **Putra Heights LRT Station**, `P066`. The source name remains
  `SP31 KJ37 Putra Heights`; only the display label is made more readable.
- Departure: **14:00**, selectable by whole hour from **07:00 to 19:00**.
- All 66 real places are available in both dropdowns. IDs and place types are
  shown to distinguish entries. Serasi blocks are labelled as opening Feb 2027.
- Changing a selection immediately recomputes both routes, using
  `engine.route(origin_id, destination_id, hour, mode="shortest")` and
  `engine.route(origin_id, destination_id, hour, mode="coolest")`.

The map draws returned link geometries as paths, not straight lines between
places. Shortest is a wider orange line, coolest is a narrower green line.
Where both use the same link, the orange border remains visible. Each route can
be hidden independently. Hover on a route for its metrics, and drag/zoom the map.
O and D mark the recorded place coordinates; the engine uses the authoritative exported `node_id` and falls back to validated
coordinates only when that ID is absent. Place markers need not be exactly at
the recorded walking junction.

## Metrics and interpretation

The comparison table contains each route's distance in metres, walking time in
minutes, sun exposure in minutes, and heat exposure in degree-C-minutes. The
summary shows heat avoided, sun exposure avoided, extra distance and extra walk
time for coolest relative to shortest. Values come from the engine; comparison
differences are calculated from the two returned results.

- Sun exposure sums walking minutes weighted by each link's unshaded share.
- Heat exposure sums walking minutes multiplied by degrees above the assumed
  32 degrees C comfort line; it is not air temperature.
- Walking speed is assumed to be 72 m/min.
- The engine searches cooler alternatives subject to a 25% maximum distance
  detour; it does not guarantee a distinct or globally coolest possible route.

With the current committed inputs, the default 14:00 comparison is:

| Metric | Shortest | Coolest |
|---|---:|---:|
| Distance (m) | 824.5 | 826.3 |
| Walking time (min) | 11.451 | 11.476 |
| Sun exposure (min) | 9.684 | 8.466 |
| Heat exposure (degree-C-min) | 101.404 | 92.121 |

These numbers are documented examples, not hardcoded UI results. The app calls
the engine every time. The replay date is 6 September 2026, not live weather.

## Errors and incomplete results

Identical places are rejected before routing. Distinct places snapped to the
same junction or disconnected routes show the engine's message. Missing files,
missing geometry, invalid metrics or absent results produce messages instead
of fake routes. If one route succeeds, its map and table remain available; the
two-route comparison is withheld. Failed selections clear previous results.
When both paths match, the app explains that no cooler alternative was found
within the allowed detour at the chosen time. The effective heat determines
whether a cooler route exists; morning values are no longer assumed uniform.

## Verification

```powershell
# Complete suite, including all simulator and engine tests:
.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp

# Cool Route tests only:
.venv\Scripts\python.exe -B -m pytest tests/test_cool_route.py -q -p no:cacheprovider --basetemp=.pytest_coolcorridor_temp
```

Pytest clears the explicitly named temporary directory on startup. It is ignored
by Git and should contain test artifacts only. Windows folder ownership must
permit that cleanup.

Automated tests use Streamlit's AppTest to run real default routes, change time
and origin, check displayed metrics, reject identical selections, and exercise
missing/partial results. Other tests check route coordinates and metrics against
the actual network, validate map layers and visibility, and protect shared input
bytes. Test doubles are used for error cases only; production uses no placeholders.

For a manual browser check:

1. Confirm 99 Speedmart to the LRT station at 14:00 and the values above.
2. Hover the orange and green paths; toggle each off/on, pan and zoom.
3. Select 07:00, then 19:00; confirm the comparison updates.
4. Change the origin to FamilyMart and verify the route updates.
5. Set the same origin and destination and confirm the warning replaces the map.

## Shared effective heat and junctions

Route exposure uses the same versioned effective heat as Heat Map and Planner.
Labels identify corrected **SIMULATED** calibration or explicit baseline fallback.
Each hour is on 6 September 2026 Asia/Kuala_Lumpur; forecast weather is excluded.
Missing/inconsistent correction artifacts fail validation instead of mixing
sources. Viewing the app never runs correction or modifies shared files.

All 66 exported place IDs are resolved through one engine resolver, including
P066 → `node:8141631184`. Junction coordinates are inferred from common incident
geometry endpoints, independent of line orientation. Invalid supplied node IDs
raise errors; absent IDs may use coordinate fallback only when graph coordinates
are reliable. Recalculated values above supersede the previous snapping-based
results. See [final results](final_results.md) and [repair QA](full_integration_repair.md).

## Map rendering regression: purple rectangle

The initial map passed Python tests but rendered as a solid purple rectangle
in the browser. This was reproduced with the real default routes in headless
Edge. The purple was the destination ScatterplotLayer marker, drawn over the
routes and basemap with invalid sizing units.

Pydeck treats bare string layer arguments as JavaScript accessor expressions.
For example, `radius_units="pixels"` serialized to `"radiusUnits":"@@=pixels"`
instead of the literal `"radiusUnits":"pixels"`. Width units and text alignment
had the same mistake. The invalid unit setting let the destination marker cover
the viewport. Python-side metric and geometry tests did not catch this browser
rendering error.

Layer enum values now use `pydeck.types.String`, while real data accessors such
as `get_position="position"` remain expressions. Markers are capped at 16 pixels
radius, paths at 12 pixels width, and text at 16 pixels. The wider orange shortest
path is always drawn before the narrower green coolest path so shared links
retain both colors, even if route dictionary order changes.

All layers use deck.gl's geospatial viewport default (LNGLAT), avoiding numeric
coordinate-system enums that differ across deck.gl versions. The committed places and
links were verified as EPSG:4326. Places with legacy named CRS metadata are
transformed to EPSG:4326 with longitude first; route coordinates remain the real
engine output and are checked for valid geographic ranges. The viewport is
computed from those route and place coordinates.

The supported keyless CARTO Positron basemap is retained. Its style, TileJSON
index and a Putra Heights vector tile returned HTTP 200 during debugging; the
tile permits browser access via CORS. Thus the reproduced purple rectangle was
a layer sizing bug, not an unavailable tile service. Basemap tiles still require
internet access.

Regression tests inspect the serialized deck JSON for literal enums and size
caps, check geographic coordinates/viewport, test projected-place conversion,
and verify identical-route colors and draw order. Browser checks complement
these tests because Streamlit AppTest does not render WebGL pixels.
