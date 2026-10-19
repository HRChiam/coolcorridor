"""Heat model step 2a: pick the links worth hand-tagging and make a tagging sheet.

Ranks links by households x metres walked on them, over the shortest walks (home -> LRT, shops, parks,
community) use them, then writes:
  data/link_tags.csv   the top links, with blank covered/surface/canopy columns
                       for you to fill from Street View
  data/tagging_map.html  those links numbered on a map, each with a Street View link

Run:  .venv/Scripts/python heat_model/tag_links.py [--n 60]
It never overwrites an existing link_tags.csv (that's your hand work); if the
sheet exists, it only rebuilds the map from the sheet's links.
Then fill the sheet and run heat_model/apply_tags.py.
"""

import argparse
from pathlib import Path

import folium
import geopandas as gpd
import networkx as nx
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
STATION = (2.99605, 101.57558)


def household_use(links, places):
    """Households whose shortest walk to each destination uses the link, summed."""
    G = nx.Graph()
    for row in links.itertuples():
        # keep the shortest of any parallel links between the same junctions
        if not G.has_edge(row.u, row.v) or G[row.u][row.v]["length"] > row.length_m:
            G.add_edge(row.u, row.v, length=row.length_m, link_id=row.link_id)
    homes = places[places.kind == "home"]
    dests = places[places.kind != "home"]
    use = pd.Series(0.0, index=links.link_id)
    for home in homes.itertuples():
        paths = nx.single_source_dijkstra_path(G, home.node_id, weight="length")
        for dest in dests.itertuples():
            path = paths.get(dest.node_id)
            if not path:
                continue
            for a, b in zip(path, path[1:]):
                use[G[a][b]["link_id"]] += home.households
    return use


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--n", type=int, default=60, help="how many links to put on the sheet")
    args = parser.parse_args()

    tags_path = DATA / "link_tags.csv"
    links = gpd.read_file(DATA / "links.geojson")
    places = gpd.read_file(DATA / "places.geojson")
    links["use"] = household_use(links, places).values
    # households x metres: long busy links matter more than short busy crossings
    links["exposure"] = links["use"] * links["length_m"]

    sheet_exists = tags_path.exists()
    if sheet_exists:  # keep the user's sheet and its ranks; rebuild only the map
        ranks = pd.read_csv(tags_path, usecols=["rank", "link_id"])
        top = links.merge(ranks, on="link_id").sort_values("rank")
    else:
        top = links.sort_values("exposure", ascending=False).head(args.n).copy()
        top["rank"] = range(1, len(top) + 1)

    utm = top.estimate_utm_crs()
    mid = top.to_crs(utm).geometry.interpolate(0.5, normalized=True).to_crs("EPSG:4326")
    top["lat"], top["lon"] = mid.y.round(6), mid.x.round(6)
    top["streetview"] = [
        f"https://www.google.com/maps/@?api=1&map_action=pano&viewpoint={y},{x}" for y, x in zip(top.lat, top.lon)
    ]
    if not sheet_exists:
        sheet = top[["rank", "link_id", "name", "highway", "length_m", "lat", "lon", "streetview"]].copy()
        sheet["osm_covered"] = top["covered"].map({True: "yes", False: ""})
        sheet["osm_surface"] = top["surface"].where(top["surface_src"] == "osm", "")
        for col in ["covered", "surface", "canopy", "note"]:
            sheet[col] = ""
        sheet.to_csv(tags_path, index=False)

    # Links that meet at a junction get different colours, so each one's extent is visible
    touching = nx.Graph()
    touching.add_nodes_from(top.link_id)
    by_node = pd.concat([top[["link_id", "u"]].rename(columns={"u": "node"}),
                         top[["link_id", "v"]].rename(columns={"v": "node"})])
    for ids in by_node.groupby("node").link_id:
        ids = list(ids[1])
        touching.add_edges_from((a, b) for i, a in enumerate(ids) for b in ids[i + 1:])
    palette = ["#dc2626", "#2563eb", "#d97706", "#7c3aed", "#059669", "#db2777"]
    colour_of = {k: palette[c % len(palette)] for k, c in nx.greedy_color(touching, "largest_first").items()}
    top["colour"] = top.link_id.map(colour_of)
    top["label"] = top["name"].fillna(top["highway"])

    m = folium.Map(location=STATION, zoom_start=16, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Light Gray", name="Light grey",
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite",
    ).add_to(m)
    folium.GeoJson(links[["geometry"]], style_function=lambda f: {"color": "#a3a3a3", "weight": 1.5}).add_to(m)
    folium.GeoJson(
        top[["rank", "link_id", "label", "length_m", "colour", "geometry"]],
        style_function=lambda f: {"color": f["properties"]["colour"], "weight": 5},
        highlight_function=lambda f: {"color": "#facc15", "weight": 10},  # hover shows the link's full extent
        tooltip=folium.GeoJsonTooltip(["rank", "link_id", "label", "length_m"],
                                      aliases=["#", "Link", "Street", "Length (m)"]),
    ).add_to(m)
    # Junction dots: each link runs from one dot to the next
    ends = {c for g in top.geometry for c in (g.coords[0], g.coords[-1])}
    for x, y in ends:
        folium.CircleMarker([y, x], radius=3, color="#111", weight=1.5, fill=True, fill_color="#fff",
                            fill_opacity=1).add_to(m)
    for row, point in zip(top.itertuples(), mid):
        popup = (f"<b>#{row.rank} {row.link_id}</b><br>{row.label}, {row.length_m} m<br>"
                 f"<a href='{row.streetview}' target='_blank'>Open Street View</a>")
        folium.Marker(
            [point.y, point.x], popup=folium.Popup(popup, max_width=250),
            icon=folium.DivIcon(html=f"<div style='font:bold 11px sans-serif;color:#fff;background:{row.colour};"
                                     f"border-radius:9px;padding:1px 5px;width:max-content'>{row.rank}</div>"),
        ).add_to(m)
    folium.LayerControl().add_to(m)
    m.save(DATA / "tagging_map.html")

    print(f"Top {len(top)} links cover {top.length_m.sum() / 1000:.1f} km and "
          f"{top.exposure.sum() / links.exposure.sum():.0%} of household walking distance.")
    print(("Kept your link_tags.csv; rebuilt" if sheet_exists else f"Wrote {tags_path.name} and") + " tagging_map.html")


if __name__ == "__main__":
    main()
