"""Heat model step 4: shade per link per hour, 7am to 7pm, on the design day.

Building shadow = footprint swept away from the sun by height / tan(sun elevation).
Each link is sampled every 5 m; its building shade b is the share of points inside
a shadow (or a building). Roofs and trees then come from the hand tags:
  covered link  -> shade 1
  otherwise     -> shade = b + (1 - b) * TREE_SHADE * canopy
canopy is the share of the link under trees; the formula assumes trees and building
shadows fall independently along the link. Writes shade_h07..shade_h19 into
data/links.geojson.

Run after apply_tags.py and weather.py:
  .venv/Scripts/python heat_model/shade.py
"""

import time
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd
import shapely
from shapely.affinity import translate

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

SAMPLE_M = 5
TREE_SHADE = 0.8  # assumption: tree canopy blocks 80% of direct sun
MIN_ELEV_DEG = 2  # sun lower than this (or below the horizon): treat links as fully shaded


def shadow_polygons(footprints, heights, elev_deg, azim_deg):
    """Each footprint swept away from the sun; azimuth is clockwise from north."""
    length = heights / np.tan(np.radians(elev_deg))
    dx = -length * np.sin(np.radians(azim_deg))
    dy = -length * np.cos(np.radians(azim_deg))
    return np.array([
        shapely.union(g, translate(g, x, y)).convex_hull for g, x, y in zip(footprints, dx, dy)
    ])


def sample_points(lines):
    """Points at the middle of each ~5 m piece of each link, and which link each belongs to."""
    points, owner = [], []
    for i, line in enumerate(lines):
        n = max(int(np.ceil(line.length / SAMPLE_M)), 1)
        points.append(shapely.line_interpolate_point(line, (np.arange(n) + 0.5) / n, normalized=True))
        owner.append(np.full(n, i))
    return np.concatenate(points), np.concatenate(owner)


def main():
    start = time.time()
    links = gpd.read_file(DATA / "links.geojson")
    buildings = gpd.read_file(DATA / "buildings.geojson")
    weather = pd.read_csv(DATA / "weather.csv")
    design = weather[weather.day == "design"].set_index("hour")

    utm = links.estimate_utm_crs()
    lines = links.to_crs(utm).geometry.values
    footprints = buildings.to_crs(utm).geometry.values
    heights = buildings.height_m.values
    points, owner = sample_points(lines)

    covered = links.covered.astype(bool).values
    canopy = links.canopy.fillna(0).values
    summary = []
    for hour, sun in design.iterrows():
        col = f"shade_h{hour:02d}"
        if sun.sun_elev_deg <= MIN_ELEV_DEG:
            links[col] = 1.0
            summary.append((hour, sun.sun_elev_deg, np.nan, 1.0))
            continue
        shadows = shapely.STRtree(shadow_polygons(footprints, heights, sun.sun_elev_deg, sun.sun_azim_deg))
        hit = np.zeros(len(points), bool)
        hit[np.unique(shadows.query(points, predicate="intersects")[0])] = True
        b = np.bincount(owner, weights=hit, minlength=len(links)) / np.bincount(owner, minlength=len(links))
        shade = np.where(covered, 1.0, b + (1 - b) * TREE_SHADE * canopy)
        links[col] = shade.round(3)
        w = links.length_m.values
        summary.append((hour, sun.sun_elev_deg, np.average(b, weights=w), np.average(shade, weights=w)))

    links.to_file(DATA / "links.geojson", driver="GeoJSON")

    print("hour  sun elev  building shade  total shade   (length-weighted, all links)")
    for hour, elev, b, s in summary:
        b_txt = "    -" if np.isnan(b) else f"{b:5.0%}"
        print(f"{hour:4d}  {elev:7.1f}°       {b_txt}        {s:5.0%}")
    tagged = links[links.hand_tagged.astype(bool)]
    print(f"Hand-tagged links at 1pm: mean shade {tagged.shade_h13.mean():.0%}; "
          f"{(tagged.shade_h13 < 0.1).sum()} of {len(tagged)} are almost fully exposed (<10% shade)")
    print(f"Wrote shade_h07..shade_h19 to links.geojson in {time.time() - start:.0f}s "
          f"({len(points)} sample points, {len(footprints)} buildings)")


if __name__ == "__main__":
    main()
