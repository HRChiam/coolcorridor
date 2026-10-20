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
| Hand-tagged links | The 60 most-walked links (6.0 km, 55% of household walking distance), plus the S08 sensor site and 2 links on the main road east of the station (checked for a footpath): covered, surface, canopy | Street View by hand (real); canopy estimated by eye in steps of 0.25 |
| Untagged links | Canopy and surface borrowed from tagged links on the same street (199 links), else the same road type with at least 4 tagged links (1,076); the remaining 156 keep canopy 0 | Our estimate from the hand tags |
| Satellite canopy | Not used: ESA WorldCover (10 m) and Meta canopy height (1 m) did not match the hand tags (correlation ≤ 0.07) | Tested |
| Default surface | Footpaths concrete, roads asphalt, where neither tags nor borrowing apply | Our estimate |
| Covered walkways | OSM `covered=yes` (18 links) plus hand tags | Real (OSM + hand) |
| Walking network | OSM walk network pulled 1,200 m around the station, including gated-estate streets (`access=private`); homes and places within 800 m | Gated estates connect only through gates beyond 800 m; residents walk their own streets |
| Sensor correction | Each link within 150 m of a sensor takes its nearest sensor's air-temperature offset, scaled by 1 − distance/150 m; the heat score shifts one-for-one | Our method. Its before/after error is a **pipeline check, not validation**: the sensors are simulated from our own assumptions |
| Sensor reading per hour | Median of readings within ±30 min of the hour | Ignores spikes; a silent sensor is skipped that hour |
| Unsafe links | A main road (primary, trunk, secondary or their slip roads) is unsafe unless a footpath is known: an OSM sidewalk tag, or a paver or concrete walking surface seen on Street View on that link or on the same street. 60 links (3.2 km) are unsafe; other streets stay walkable | Plan's design rule. Approximate: OSM has no sidewalk tags at all in this area, so Street View evidence decides |
| Unsafe exceptions | `data/unsafe_overrides.csv` sets any link safe or unsafe by hand | For busy roads spotted on demo routes |
| Confidence per link | High: hand-tagged and within 150 m of a sensor site (49 links); medium: hand-tagged (14); low: neither (1,428) | Design choice |
| Shade coverage | Share of network length in shade = Σ(shade × length) ÷ Σ length; after fixes, each fix blocks its `shade_gain` share of the sun still reaching the link | Our definition |

## Routing and planner (Person 2)

Values as set in `engine.py` and `data/interventions.csv`.

| Assumption | Value | Basis |
|---|---|---|
| Comfort line | 32°C | Our choice; to test at 30 and 34 |
| Walking speed | 72 m per minute (1.2 m/s) | Our estimate |
| Trips per household per day (one way) | LRT 0.9, shops 0.45, park 0.15, community 0.10; spread over 7am–7pm by an assumed hourly profile; each trip goes to the nearest place of that kind | Our estimate; a local survey would replace it |
| Maximum detour | Coolest route ≤ 25% longer than shortest; balanced ≤ 10% | Design choice |
| Route search | Shortest path with cost = length + λ × heat exposure, λ = 5, 10, 20, 40, 80, 160 | Plan method |
| Unsafe links in routing | Left out of every route; if that cuts a place off, they are used at 10× cost and the route is flagged (today every place can reach the LRT without them) | Plan rule |
| Cost per fix | Shade trees RM 160/m, shade sail RM 350/m, covered walkway RM 1,000/m, cool paving RM 120/m | **Assumptions**; no Malaysian per-metre price found. Cross-checks: MBSA's own share of over 3 km of LRT3 walkways was RM 2.7 million (2026), at least ~RM 900/m; Kota Kinabalu budgeted RM 1 million for 1,000 shade trees plus shrubs (2012), at most ~RM 125/m; US shade sails US$2.50–8 per sq ft installed; Los Angeles cool coating US$5.40–6.50 per m², so RM 120/m may be high |
| Effect of each fix | Shade trees block 35% of remaining sun, shade sail 75%, covered walkway 100%; cool paving raises albedo by 0.30 | Our estimate |
| Weeks to take effect | Trees 260 (about 5 years to useful shade), shade sail 4, covered walkway 22, cool paving 2 | Covered walkway: MBSA's LRT3 walkways, announced July for completion in December 2026. Others our estimate |
| Yearly maintenance (RM per metre) | Trees 25, shade sail 44, covered walkway 15, cool paving 20 | **Assumptions.** Trees: DBKL pruning RM 100–1,000 per tree (2014), assumed RM 200 a tree a year. Sail: fabric replaced about every 8 years. Walkway: ~1.5% of cost a year. Paving: recoat about every 6 years (coating lasts 5–7 years) |
| Upkeep sensitivity | 10-year value (benefit ÷ build + 10 × upkeep) re-ranked with upkeep at half and double our estimate | With our assumed costs, sails beat trees on every link at all three levels. The best 10-year value is sails at half and our estimate, but covered walkways at double, so real upkeep costs are the first thing to confirm in a pilot |
| Quick win | Shade sail, covered walkway and cool paving (work within months); trees are not | Plan: trees take years to give full shade |
| Planner method | The set of fixes (at most one per link) that saves the most person-minutes of heat within the budget, found by an exact search over the budget in RM 10 steps; costs round up, so it never overspends | Design choice; it beat picking fixes one by one by benefit per RM by 1.8% at RM 50k, 6.7% at RM 100k and 39.6% at RM 250k |
| Planner horizon | Two views: next 12 months and 10 years (the app's toggle; `priorities.csv` uses 10 years). Benefit = full daily benefit × the average share of the fix's effect over the period, assuming it grows steadily until fully working: 1 − w/(2H) if it works within the period, else H/(2w) (w = weeks to take effect, H = the period). The budget covers building costs only; upkeep is shown alongside, per fix and in total ("plus RM X a year"), with a 10-year total cost (build + 10 × upkeep) | Design choice: build and upkeep usually come from different budgets, and upkeep may pass to the council after handover. With our assumed costs, RM 100k builds 5 shade sails and 1 cool paving in both views (−8.2% over 12 months, −8.5% over 10 years); trees get 10% credit in their first year and 75% over 10 years |
| Planner budget | Results reported at RM 50,000, 100,000 and 250,000; the app has a slider | **Illustrative** levels; the team picks the demo default |
| Detour cap sensitivity | Coolest route also tested at 30% instead of 25% | Sensitivity check only: at 1pm it gives the same 37.7% of trips, so the street layout, not the cap, limits cooler routes |

## Simulated sensors (Person 3)

All sensor readings are **synthetic** and labelled "Simulated data" wherever shown.

| Assumption | Value | Basis |
|---|---|---|
| Sensor sites | 8 links: 2 exposed asphalt, 2 tree-lined, 1 covered walkway, 1 LRT entrance, 1 park, 1 shops (`data/sensor_links.csv`) | Chosen for contrast |
| Air temperature offsets by link type | Asphalt +1.5, concrete +1.0, paver +0.8, grass verge +0.5 (proposed for S08), covered −0.5, tree-lined −1.0, park −1.5 °C | Our estimate |
| Noise | Air ±0.3°C, humidity ±2%, surface ±1°C | Our estimate |
| Faults | One sensor silent for 30 min, one spikes | Built in to test the app's checks |
