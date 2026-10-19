"""Heat model step 2b: merge your hand tags (data/link_tags.csv) into links.geojson.

Only filled cells override; blank cells keep the OSM value or default. Safe to
re-run any time, including after pull_area.py.

  covered  yes / no
  surface  asphalt / concrete / paver / grass
  canopy   share of the link under tree canopy, 0 to 1 (by eye from Street View)

Run:  .venv/Scripts/python heat_model/apply_tags.py
"""

from pathlib import Path

import geopandas as gpd
import pandas as pd

from pull_area import ALBEDO

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"


def main():
    links = gpd.read_file(DATA / "links.geojson")
    tags = pd.read_csv(DATA / "link_tags.csv", dtype=str).fillna("")
    tags = tags[tags[["covered", "surface", "canopy"]].ne("").any(axis=1)].set_index("link_id")

    unknown = tags.index.difference(links.link_id)
    if len(unknown):
        raise SystemExit(f"link_ids not in links.geojson (re-pulled?): {list(unknown)}")
    bad_surface = tags.surface[(tags.surface != "") & ~tags.surface.isin(ALBEDO)]
    if len(bad_surface):
        raise SystemExit(f"surface must be one of {list(ALBEDO)}: {bad_surface.to_dict()}")

    idx = links.set_index("link_id").index
    for link_id, t in tags.iterrows():
        row = idx.get_loc(link_id)
        if t.covered:
            links.loc[row, "covered"] = t.covered.strip().lower() in {"yes", "y", "true", "1"}
        if t.surface:
            links.loc[row, "surface"] = t.surface
            links.loc[row, "surface_src"] = "hand"
            links.loc[row, "albedo"] = ALBEDO[t.surface]
        if t.canopy:
            links.loc[row, "canopy"] = min(max(float(t.canopy), 0.0), 1.0)
        links.loc[row, "hand_tagged"] = True

    links.to_file(DATA / "links.geojson", driver="GeoJSON")
    print(f"Applied tags to {len(tags)} links: {links.covered.sum()} covered, "
          f"{(links.canopy > 0).sum()} with canopy, {(links.surface_src == 'hand').sum()} surfaces set by hand.")


if __name__ == "__main__":
    main()
