"""Create a tiny SYNTHETIC network for offline integration testing only.

Use `python make_demo_data.py`; data goes into demo_data/, NEVER repo data/.
"""
from pathlib import Path
from shutil import copyfile

import geopandas as gpd
import pandas as pd
from shapely.geometry import LineString, Point

import engine


out = Path(__file__).parent / "demo_data"
out.mkdir(exist_ok=True)
A, B, C = (101.0, 3.0), (101.001, 3.0), (101.002, 3.0)
D, E = (101.0, 3.001), (101.001, 3.001)
segments = [
    ("hot1", A, B, 100, 40, 0.0),
    ("hot2", B, C, 100, 40, 0.0),
    ("cool1", A, D, 80, 30, 0.9),
    ("cool2", D, E, 80, 30, 0.9),
    ("cool3", E, C, 80, 30, 0.9),
]
links = []
for link_id, start, end, distance, heat, shade in segments:
    props = dict(link_id=link_id, length_m=distance, covered=False, canopy=shade,
                 albedo=0.25, surface="asphalt", geometry=LineString([start, end]))
    for hour in engine.HOURS:
        props[f"shade_h{hour:02d}"] = shade
        props[f"heat_h{hour:02d}"] = heat
    links.append(props)
gpd.GeoDataFrame(links, crs="EPSG:4326").to_file(out / "links.geojson", driver="GeoJSON")
places = [
    dict(place_id="home-1", name="SYNTHETIC Homes", kind="home", households=10, geometry=Point(A)),
    dict(place_id="lrt-1", name="SYNTHETIC Transit", kind="transit", households=0, geometry=Point(C)),
]
gpd.GeoDataFrame(places, crs="EPSG:4326").to_file(out / "places.geojson", driver="GeoJSON")
pd.DataFrame([{"hour": h, "shortwave_radiation": 800 if h < 18 else 200}
              for h in engine.HOURS]).to_csv(out / "weather.csv", index=False)
copyfile(Path(__file__).parent / "data" / "interventions.csv", out / "interventions.csv")
(out / "README.txt").write_text(
    "SYNTHETIC DEMO DATA ONLY. Not an actual Putra Heights / Ara Damansara map.\n"
    "Artificial distances, solar radiation, heat and household counts.\n"
    "Do not show these numbers as township findings.\n")
print(f"Created explicitly synthetic fixtures in {out}")
print("Try: python person2_results.py --data demo_data --budget 20000")
