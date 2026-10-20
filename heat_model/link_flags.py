"""Heat model step 2c: safety flag and confidence per link.

unsafe (Person 2's routes never use these links):
  A main road (primary, trunk, secondary, or their slip roads) is unsafe unless a
  footpath is known to exist: OSM tags a sidewalk on it, or Street View showed one
  (hand-tagged walking surface paver or concrete, on that link or, for untagged
  links, on the same street). Hand-tagged asphalt or grass on a main road means
  people walk on the road or verge, so it is unsafe. OSM has no sidewalk tags at
  all in this area, so Street View evidence decides. Other streets stay walkable.
  data/unsafe_overrides.csv (link_id,unsafe,note; unsafe = yes/no) overrides all of
  this, e.g. for a busy road spotted on a demo route.

confidence (the app fades low-confidence links):
  high    hand-tagged and within SENSOR_RADIUS_M of a sensor site (data/sensor_links.csv)
  medium  hand-tagged
  low     everything else (values borrowed from other links, or defaults)

Writes unsafe, unsafe_reason, confidence (and, once, the OSM sidewalk tag) into
data/links.geojson. Run after apply_tags.py:
  .venv/Scripts/python heat_model/link_flags.py
"""

from pathlib import Path

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

MAIN_ROADS = {"primary", "primary_link", "secondary", "secondary_link", "trunk", "trunk_link"}
FOOTPATH_SURFACES = {"paver", "concrete"}
OSM_SIDEWALK = {"both", "left", "right", "separate", "yes"}
SENSOR_RADIUS_M = 150  # same radius as the sensor correction


def osm_sidewalk(links):
    """The OSM sidewalk tag per link, read once from the OSM download cache."""
    import pull_area

    pull_area.configure_osmnx()
    _, osm = pull_area.pull_links()
    same = len(osm) == len(links) and (osm.link_id.values == links.link_id.values).all() \
        and (osm.u.values == links.u.values).all() and (osm.v.values == links.v.values).all()
    if not same:
        raise SystemExit("OSM data no longer matches links.geojson (cache cleared or OSM changed); "
                         "can't read sidewalk tags without renumbering links.")
    return osm["sidewalk"].values


def safety(links):
    main = links["highway"].isin(MAIN_ROADS)
    tagged_sidewalk = links["sidewalk"].isin(OSM_SIDEWALK)
    seen = links["tag_src"].isin(["hand", "street"])
    footpath = links["surface"].isin(FOOTPATH_SURFACES)
    reason = np.select(
        [~main, tagged_sidewalk, seen & footpath, links["tag_src"].eq("hand")],
        ["not a main road", "OSM sidewalk tag", "footpath seen on Street View", "no footpath on Street View"],
        "main road, no footpath evidence",
    )
    unsafe = main & ~tagged_sidewalk & ~(seen & footpath)

    overrides_path = DATA / "unsafe_overrides.csv"
    if overrides_path.exists():
        ov = pd.read_csv(overrides_path, dtype=str).fillna("")
        unknown = set(ov.link_id) - set(links.link_id)
        if unknown:
            raise SystemExit(f"unsafe_overrides.csv has unknown link_ids: {sorted(unknown)}")
        for row in ov.itertuples():
            i = links.index[links.link_id == row.link_id][0]
            unsafe.loc[i] = row.unsafe.strip().lower() in {"yes", "y", "true", "1"}
            reason[i] = f"override: {row.note}" if row.note else "override"
    return unsafe, reason


def confidence(links):
    hand = links["hand_tagged"].astype(bool)
    sites = pd.read_csv(DATA / "sensor_links.csv")
    utm = links.estimate_utm_crs()
    points = gpd.GeoSeries(gpd.points_from_xy(sites.lon, sites.lat), crs="EPSG:4326").to_crs(utm)
    lines = links.to_crs(utm).geometry
    near_sensor = np.zeros(len(links), bool)
    for p in points:
        near_sensor |= (lines.distance(p) <= SENSOR_RADIUS_M).values
    return np.select([hand & near_sensor, hand], ["high", "medium"], "low")


def cut_off_places(links):
    """Places that can't reach the LRT without using unsafe links."""
    places = gpd.read_file(DATA / "places.geojson")
    G = nx.Graph()
    G.add_nodes_from(pd.concat([links.u, links.v]).unique())
    G.add_edges_from(links.loc[~links.unsafe, ["u", "v"]].itertuples(index=False))
    station = places.loc[places.kind == "transit", "node_id"].iloc[0]
    reachable = nx.node_connected_component(G, station)
    return places[~places.node_id.isin(reachable)]


def main():
    links = gpd.read_file(DATA / "links.geojson")
    if "sidewalk" not in links:
        links["sidewalk"] = osm_sidewalk(links)
    links["unsafe"], links["unsafe_reason"] = safety(links)
    links["confidence"] = confidence(links)
    links.to_file(DATA / "links.geojson", driver="GeoJSON")

    main_roads = links[links.highway.isin(MAIN_ROADS)]
    print(f"Main-road links: {len(main_roads)} ({main_roads.length_m.sum() / 1000:.1f} km); "
          f"OSM sidewalk tags in the area: {links.sidewalk.isin(OSM_SIDEWALK).sum()}")
    print(f"Unsafe: {links.unsafe.sum()} links ({links[links.unsafe].length_m.sum() / 1000:.1f} km)")
    print(links.groupby("unsafe_reason").agg(links=("link_id", "size"), unsafe=("unsafe", "sum")).to_string())
    print("Confidence:", links.confidence.value_counts().to_dict())
    cut = cut_off_places(links)
    if len(cut):
        print(f"!! {len(cut)} places can't reach the LRT without an unsafe link "
              f"(Person 2's fallback: x10 cost and flag the route):")
        print(cut[["place_id", "name", "kind", "households"]].to_string(index=False))
    else:
        print("Every place can still reach the LRT without unsafe links.")
    print("Wrote unsafe, unsafe_reason and confidence to links.geojson")


if __name__ == "__main__":
    main()
