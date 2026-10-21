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
| Serasi occupancy | 0 households counted; the towers are kept because they already stand and cast shadows | Completion is Feb 2027, so the model represents Putra Heights today |
| Households in houses | 1 per house footprint; homes grouped into 200 m cells (855 households, all households in the model) | Our estimate from OSM footprints |
| Surface reflectivity (albedo) | Asphalt 0.10, concrete 0.30, paver 0.25, grass 0.25 | Asphalt and concrete: aged-pavement values from US EPA, *Reducing Urban Heat Islands: Compendium of Strategies – Cool Pavements*, p. 5, Fig. 4 (asphalt lightens from ~0.05 new; concrete darkens from ~0.40 new). Paver and grass: our estimate within the same range |
| Hand-tagged links | The 60 most-walked links (6.0 km, 55% of household walking distance), plus the S08 sensor site: covered, surface, canopy | Street View by hand (real); canopy estimated by eye in steps of 0.25 |
| Untagged links | Canopy and surface borrowed from tagged links on the same street (199 links), else the same road type with at least 4 tagged links (1,076); the remaining 156 keep canopy 0 | Our estimate from the hand tags |
| Satellite canopy | Not used: ESA WorldCover (10 m) and Meta canopy height (1 m) did not match the hand tags (correlation ≤ 0.07) | Tested |
| Default surface | Footpaths concrete, roads asphalt, where neither tags nor borrowing apply | Our estimate |
| Covered walkways | OSM `covered=yes` (18 links) plus hand tags | Real (OSM + hand) |
| Walking network | OSM walk network pulled 1,200 m around the station, including gated-estate streets (`access=private`); homes and places within 800 m | Gated estates connect only through gates beyond 800 m; residents walk their own streets |
| Sensor correction | Each link within 150 m of a sensor takes its nearest sensor's air-temperature offset, scaled by 1 − distance/150 m; the heat score shifts one-for-one | Our method |
| Sensor reading per hour | Median of accepted readings in [hour − 30 min, hour + 30 min), Asia/Kuala_Lumpur | Exclude air residual departures >3°C from the previous 30-minute median, requiring 3 previous readings; skip silent sensor-hours |

## Routing and planner (Person 2)

| Assumption | Value | Basis |
|---|---|---|
| Comfort line | 32°C | Our choice; to test at 30 and 34 |
| One-way trips per household/day | Transit 0.9, shop 0.45, park 0.15, community 0.10 | Assumptions; nearest reachable destination by walking distance; 855 households |
| Hour weights 07..19 | 0.13, 0.12, 0.07, 0.05, 0.05, 0.06, 0.06, 0.07, 0.08, 0.10, 0.09, 0.07, 0.05; normalized | Assumptions, not observed pedestrian counts |
| Walking speed | 72 m/min (1.2 m/s) | Assumption |
| Maximum detour for a cool route | 25% longer than shortest | Design choice |
| Cost per metre: trees / sail / covered / paving | RM160 / RM350 / RM1,000 / RM120 | Existing interventions.csv; unverified estimates, not quotations |
| Shade gains: trees / sail / covered / paving | 0.35 / 0.75 / 1.00 / 0 | Existing CSV unchanged |
| Shade-gain semantics | s_after = min(1, s_before + (1 − s_before) × gain); covered forces 1 | User explicitly chose proportional gain on remaining sunlight during integration repair |
| Cool paving | Albedo increases by 0.30, capped at 1 | Existing CSV assumption |
| Effective heat after an intervention | Before effective heat + change in model solar term | Retains correction offset and rounded exported baseline; does not recalibrate sensors or reroute demand |

## Simulated sensors (Person 3)

All sensor readings are **synthetic** and labelled "Simulated data" wherever shown.

| Assumption | Value | Basis |
|---|---|---|
| Sensor sites | 8 links: 2 exposed asphalt, 2 tree-lined, 1 covered walkway, 1 LRT entrance, 1 park, 1 shops (`data/sensor_links.csv`) | Chosen for contrast |
| Air temperature offsets by link type | Asphalt +1.5, concrete +1.0, paver +0.8, grass verge +0.5 (proposed for S08), covered −0.5, tree-lined −1.0, park −1.5 °C | Our estimate |
| Noise | Air ±0.3°C, humidity ±2%, surface ±1°C | Our estimate |
| Faults | S02 silent from 12:00 inclusive to 12:30 exclusive; S01 spikes at 13:05 by +8 degrees C in air and surface | Provisional Person 3 choices; configurable; not real sensor faults |
| Random seed | 20260906, NumPy default_rng | Deterministic; CLI or JSON can override |
| Noise distribution | Independent uniform draws within the bounds above; humidity clipped to 0-100% | Provisional choice; configurable noise amplitudes |
| S08 offset in generated readings | +0.5 degrees C, explicit override in config/sensor_simulation.json | Provisional grass-verge value; shared sensor_links.csv unchanged |
| Replay timing | Design-day weather interpolated linearly every 5 minutes from 07:00 through 19:00, Asia/Kuala_Lumpur | Documented data contract; batch CSV generation in this phase |
| Surface temperature | Noisy sensor air + (1 - shade) * sunlight / 1000 * 25 * (1 - albedo) + independent noise | Documented simulator formula; shade from each reading's whole hour |
| Fault semantics | Silence omits six rows; one spike changes both temperature fields, leaving humidity unchanged | Provisional implementation; noise drawn before faults so a no-fault run is directly comparable |
| Precision | Three decimal places in the CSV; source is always simulated | Person 3 output convention |

Person 3 settings and verification commands are described in
[sensor_simulator.md](sensor_simulator.md). Offset overrides, noise amplitudes,
seed and fault choices live in `config/sensor_simulation.json`; these provisional
choices do not establish real-world calibration or fault-detection thresholds.

## Integrated correction and date contract

The model/replay date is fixed to **2026-09-06, Asia/Kuala_Lumpur (UTC+08)**.
Weather must contain exactly one finite design-day record at each hour 07..19.
Forecast rows cannot change heat, intervention radiation or correction validity.
The manifest records the whole weather file hash for provenance and a separate
selected-design-row hash for applicability.

Corrections use the existing sensor link midpoint and target link geometry in
local UTM, nearest available sensor within 150 m, linear distance decay, and a
median air residual versus design-hour weather. At least one accepted sample per
sensor-hour suffices, retaining Person 1's policy. Zero-coverage hours retain
zero offset and explicit baseline labels. Two-decimal effective heat is a heat
**index**, never a substitution of sensor air temperature for model heat.

Faults remain intact in the raw CSV. Calibration excludes detected outliers
using the existing Dashboard's causal residual rule, independent of configured
fault schedules. This replaces reliance on the median alone; it does not claim
to implement the Build Plan's underspecified across-sensor 3-sigma rule. With
only eight sites a single outlier cannot reach 3 population standard deviations
from their own mean. The chosen detector and its limitations are recorded in
each correction manifest.

Validation uses the previous hour's calibration against the next hour's median
simulated air residual (disjoint adjacent centred windows). It demonstrates
recovery of synthetic offsets. It does not validate heat-index accuracy, real
microclimate, pedestrian comfort or health outcomes. See
[full integration repair](full_integration_repair.md) for provenance and safety.
