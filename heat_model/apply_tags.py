"""Heat model step 2b: merge your hand tags (data/link_tags.csv) into links.geojson.

Only filled cells override; blank cells keep the OSM value or default. Safe to
re-run any time, including after pull_area.py.

  covered  yes / no
  surface  asphalt / concrete / paver / grass
  canopy   share of the link under tree canopy, 0 to 1 (by eye from Street View)

Untagged links then borrow canopy and walking surface from tagged ones: first the
same street (its length-weighted mean canopy and main surface), else the same road
type if at least MIN_TAGGED_PER_TYPE links of that type were tagged. Covered stays
OSM + hand only. tag_src records the source: hand / street / road_type / default.
(Satellite canopy maps, ESA WorldCover 10 m and Meta 1 m, were tried and did not
match the hand tags, so they are not used.)

Run:  .venv/Scripts/python heat_model/apply_tags.py
"""

from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from pull_area import ALBEDO

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MIN_TAGGED_PER_TYPE = 4  # assumption: fewer tagged links than this is too thin to generalise


def summarise(groups):
    """Length-weighted mean canopy and the surface covering most length, per group."""
    return pd.DataFrame({
        "canopy": groups.apply(lambda g: np.average(g.canopy, weights=g.length_m)),
        "surface": groups.apply(lambda g: g.groupby("surface").length_m.sum().idxmax()),
        "n": groups.size(),
    })


def fill_untagged(links):
    hand = links["hand_tagged"].astype(bool)
    road = links["highway"].str.removesuffix("_link")  # a slip road is like its main road
    tagged = links[hand]
    by_street = summarise(tagged.dropna(subset=["name"]).groupby("name"))
    by_type = summarise(tagged.groupby(road[hand]))
    by_type = by_type[by_type.n >= MIN_TAGGED_PER_TYPE]

    street = ~hand & links["name"].isin(by_street.index)
    by_road = ~hand & ~street & road.isin(by_type.index)
    for mask, table, key, label in [(street, by_street, links["name"], "street"), (by_road, by_type, road, "road_type")]:
        links.loc[mask, "canopy"] = table.canopy.reindex(key[mask]).values.round(3)
        links.loc[mask, "surface"] = table.surface.reindex(key[mask]).values
        links.loc[mask, "surface_src"] = label
    default = ~hand & ~street & ~by_road
    links.loc[default, "canopy"] = 0.0
    links["albedo"] = links["surface"].map(ALBEDO)
    links["tag_src"] = np.select([hand, street, by_road], ["hand", "street", "road_type"], "default")
    return by_type


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

    by_type = fill_untagged(links)
    links.to_file(DATA / "links.geojson", driver="GeoJSON")
    print(f"Applied tags to {len(tags)} links: {links.covered.sum()} covered, "
          f"{(links.canopy > 0).sum()} with canopy, {(links.surface_src == 'hand').sum()} surfaces set by hand.")
    src = links.groupby("tag_src").agg(links=("link_id", "size"), km=("length_m", lambda s: round(s.sum() / 1000, 1)))
    print("Canopy and surface source for every link:\n" + src.to_string())
    print("Road-type values used:\n" + by_type.round(2).to_string())


if __name__ == "__main__":
    main()
