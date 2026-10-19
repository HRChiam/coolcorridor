# Assumptions

Every assumption and simulated input in CoolCorridor, as the organisers require. Values are what the code uses; replace any with a sourced figure when one is found. Pilot area: Putra Heights, an 800 m catchment around the LRT station (KJ37/SP31).

## Heat model (Person 1)

| Assumption | Value | Basis |
|---|---|---|
| Heat score formula | H = T_air + (1 − s) × R/1000 × (a + b(1 − α)) − c × w | Our simple index (°C) |
| Heat score coefficients a, b, c | 8, 4, 0.5 | Our choice; on the design day at 1pm, exposed asphalt scores 42.8°C and a covered walkway 33.0°C |
| Weather day replayed | 6 Sep 2026: max 35.3°C, sunlight 22.05 MJ/m² | Open-Meteo archive (real); hottest of the sunniest quarter of the 60 days before 13 Oct 2026 |
| Sun position | Computed per hour, 7am–7pm | pvlib (calculated) |
| Tree canopy shade | Blocks 80% of direct sun | Our estimate |
| Covered walkway shade | 100% | Roof blocks direct sun |
| Shade where trees and building shadows overlap | Combined as independent: s = b + (1 − b) × 0.8 × canopy | Our simplification |
| Low sun | Sun below 2° elevation: links count as fully shaded | Shadows become effectively endless |
| Shadow method | Building footprints extruded as flat-roofed blocks on flat ground; links sampled every 5 m | Plan method; terrain ignored |
| Building heights where OSM has none | 3.5 m per floor; terrace 2 floors, shophouse 3, semi-detached and detached 2, apartments 10, others 2 | Our estimate; 94 of 4,730 buildings have OSM heights |
| Serasi Residences | Blocks 1–3: 33, 33 and 28 storeys; 507, 419 and 502 units (1,428) | The Edge (theedgemalaysia.com/node/727438) |
| Serasi occupancy | Its 1,428 households are counted although completion is Feb 2027 | Design choice: the model represents the year Serasi opens |
| Households in houses | 1 per house footprint; homes grouped into 200 m cells (855 households) | Our estimate from OSM footprints |
| Surface reflectivity (albedo) | Asphalt 0.10, concrete 0.30, paver 0.25, grass 0.25 | Typical published values; **source still to cite** |
| Hand-tagged links | 60 links (6.0 km, 69% of household walking distance): covered, surface, canopy | Street View by hand (real); canopy estimated by eye in steps of 0.25 |
| Untagged links | Canopy and surface borrowed from tagged links on the same street (199 links), else the same road type with at least 4 tagged links (1,076); the remaining 156 keep canopy 0 | Our estimate from the hand tags |
| Satellite canopy | Not used: ESA WorldCover (10 m) and Meta canopy height (1 m) did not match the hand tags (correlation ≤ 0.07) | Tested |
| Default surface | Footpaths concrete, roads asphalt, where neither tags nor borrowing apply | Our estimate |
| Covered walkways | OSM `covered=yes` (18 links) plus hand tags | Real (OSM + hand) |
| Walking network | OSM walk network pulled 1,200 m around the station, including gated-estate streets (`access=private`); homes and places within 800 m | Gated estates connect only through gates beyond 800 m; residents walk their own streets |
| Sensor correction | Each link within 150 m of a sensor takes its nearest sensor's air-temperature offset, scaled by 1 − distance/150 m; the heat score shifts one-for-one | Our method |
| Sensor reading per hour | Median of readings within ±30 min of the hour | Ignores spikes; a silent sensor is skipped that hour |

## Routing and planner (Person 2)

| Assumption | Value | Basis |
|---|---|---|
| Comfort line | 32°C | Our choice; to test at 30 and 34 |
| Trips per household by hour and destination | To set | Our estimate |
| Maximum detour for a cool route | 25% longer than shortest | Design choice |
| Cost per fix (trees, shade sail, covered walkway, cool paving) | To find | Public figure if found, else assumption |

## Simulated sensors (Person 3)

All sensor readings are **synthetic** and labelled "Simulated data" wherever shown.

| Assumption | Value | Basis |
|---|---|---|
| Sensor sites | 8 links: 2 exposed asphalt, 2 tree-lined, 1 covered walkway, 1 LRT entrance, 1 park, 1 shops (`data/sensor_links.csv`) | Chosen for contrast |
| Air temperature offsets by link type | Asphalt +1.5, concrete +1.0, paver +0.8, covered −0.5, tree-lined −1.0, park −1.5 °C | Our estimate |
| Noise | Air ±0.3°C, humidity ±2%, surface ±1°C | Our estimate |
| Faults | One sensor silent for 30 min, one spikes | Built in to test the app's checks |
