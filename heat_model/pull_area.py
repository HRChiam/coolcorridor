"""Heat model step 1: pull the Putra Heights catchment from OpenStreetMap.

Writes to data/:
  links.geojson      one row per walking link (the shared contract file)
  places.geojson     homes, transit, shops, parks, community places
  buildings.geojson  footprints with heights (for the shadow step)
  coverage_map.html  open in a browser to spot gaps against satellite imagery

Run from the repo root:
  .venv/Scripts/python heat_model/pull_area.py           # first pull
  .venv/Scripts/python heat_model/pull_area.py --force   # re-pull (renumbers links!)

Hand inputs (optional):
  data/places_extra.csv        places OSM is missing: name,kind,lat,lon,households
  data/building_overrides.csv  sourced fixes per building: osm_id,name,floors,households,source
"""

import argparse
import sys
import time
from pathlib import Path

import folium
import geopandas as gpd
import numpy as np
import osmnx as ox
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"

# Putra Heights LRT station (KJ37 / SP31), centroid of OSM way 401169425
STATION = (2.99605, 101.57558)  # (lat, lon)
RADIUS_M = 800  # catchment: homes and places
# Network and buildings are pulled wider: the gated estates at the catchment edge
# only connect to the rest of the network through gates outside 800 m.
NETWORK_DIST_M = 1200
HOURS = range(7, 20)  # 7am to 7pm

# --- Assumptions (copy into the Assumptions table) ---------------------------
FLOOR_HEIGHT_M = 3.5
FLOORS_BY_TYPE = {  # used only when OSM has no height or levels
    "house": 2,  # terrace
    "terrace": 2,
    "semidetached_house": 2,
    "detached": 2,
    "residential": 2,
    "retail": 3,  # shophouse
    "commercial": 3,
    "apartments": 10,  # placeholder: check on Street View
    "roof": 1,
}
DEFAULT_FLOORS = 2
ALBEDO = {"asphalt": 0.10, "concrete": 0.30, "paver": 0.25, "grass": 0.25}
HOME_CELL_M = 200  # homes are grouped into 200 m cells, one place per cell

# OSM surface tag -> our four classes
SURFACE_MAP = {
    "asphalt": "asphalt", "paved": "asphalt", "chipseal": "asphalt",
    "concrete": "concrete", "concrete:plates": "concrete", "concrete:lanes": "concrete",
    "paving_stones": "paver", "sett": "paver", "bricks": "paver", "brick": "paver",
    "grass": "grass", "ground": "grass", "dirt": "grass", "earth": "grass",
    "unpaved": "grass", "gravel": "grass", "compacted": "grass", "fine_gravel": "grass",
}
FOOT_HIGHWAYS = {"footway", "path", "pedestrian", "steps", "corridor", "cycleway"}

# osmnx's walk filter minus its access=private exclusion: gated-community streets
# (e.g. Seksyen 7, Kingsley Hills) are tagged private, but residents walk them daily.
WALK_FILTER = (
    '["highway"]["area"!~"yes"]'
    '["highway"!~"abandoned|bus_guideway|construction|cycleway|motor|no|planned|platform|proposed|raceway|razed"]'
    '["foot"!~"no"]'
)

HOME_BUILDINGS = {"house", "terrace", "semidetached_house", "detached", "residential", "bungalow"}
PLACE_TAGS = {
    "railway": ["station"],
    "shop": True,
    "amenity": [
        "restaurant", "cafe", "fast_food", "food_court", "marketplace", "bank", "pharmacy",
        "community_centre", "townhall", "place_of_worship", "school", "kindergarten",
        "library", "clinic", "hospital",
    ],
    "leisure": ["park", "playground", "garden"],
    "landuse": ["retail", "commercial"],
}
SHOP_AMENITIES = {"restaurant", "cafe", "fast_food", "food_court", "marketplace", "bank", "pharmacy"}


def with_retry(fn, *args, **kwargs):
    """The public Overpass server is often busy; back off and retry."""
    for attempt in range(6):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 - osmnx raises several HTTP error types
            wait = 5 * 2**attempt
            print(f"  Overpass busy ({type(e).__name__}), retrying in {wait}s")
            time.sleep(wait)
    return fn(*args, **kwargs)


def first(value):
    """Simplified OSM edges can hold lists of tag values; keep the first."""
    if isinstance(value, list):
        return value[0] if value else None
    return value


def pull_links():
    G = with_retry(
        ox.graph_from_point, STATION, dist=NETWORK_DIST_M, dist_type="bbox", network_type="walk",
        custom_filter=WALK_FILTER,
    )
    G = ox.convert.to_undirected(G)
    nodes, edges = ox.graph_to_gdfs(G)
    edges = edges.reset_index().sort_values(["u", "v", "key"]).reset_index(drop=True)

    osm_surface = edges.get("surface", pd.Series(index=edges.index, dtype=object)).map(first)
    highway = edges["highway"].map(first)
    default_surface = np.where(highway.isin(FOOT_HIGHWAYS), "concrete", "asphalt")
    surface = osm_surface.map(SURFACE_MAP).fillna(pd.Series(default_surface, index=edges.index))
    covered = edges.get("covered", pd.Series(index=edges.index, dtype=object)).map(first) == "yes"
    private = edges.get("access", pd.Series(index=edges.index, dtype=object)).map(first) == "private"

    links = gpd.GeoDataFrame(
        {
            "link_id": [f"L{i:04d}" for i in range(1, len(edges) + 1)],
            "u": edges["u"],
            "v": edges["v"],
            "osm_way": edges["osmid"].map(lambda x: ";".join(map(str, x)) if isinstance(x, list) else str(x)),
            "name": edges.get("name", pd.Series(index=edges.index, dtype=object)).map(first),
            "highway": highway,
            "length_m": edges["length"].round(1),
            "private": private,  # gated-community street; walkable for residents
            "covered": covered,
            "canopy": 0.0,
            "surface": surface,
            "surface_src": np.where(osm_surface.isin(SURFACE_MAP.keys()), "osm", "default"),
            "albedo": surface.map(ALBEDO),
            "hand_tagged": False,
        },
        geometry=edges.geometry.values,
        crs=edges.crs,
    )
    for h in HOURS:
        links[f"shade_h{h:02d}"] = np.nan
    for h in HOURS:
        links[f"heat_h{h:02d}"] = np.nan
    links["flow_day"] = np.nan  # Person 2 fills
    return G, links


def pull_buildings():
    b = with_retry(ox.features_from_point, STATION, tags={"building": True}, dist=NETWORK_DIST_M)
    b = b[b.geom_type.isin(["Polygon", "MultiPolygon"])].reset_index()
    btype = b["building"].astype(str)
    levels = pd.to_numeric(b.get("building:levels"), errors="coerce") if "building:levels" in b else np.nan
    height = (
        pd.to_numeric(b["height"].astype(str).str.replace("m", "").str.strip(), errors="coerce")
        if "height" in b
        else pd.Series(np.nan, index=b.index)
    )
    assumed = btype.map(FLOORS_BY_TYPE).fillna(DEFAULT_FLOORS) * FLOOR_HEIGHT_M
    height_m = height.fillna(levels * FLOOR_HEIGHT_M).fillna(assumed)
    src = np.where(height.notna(), "osm_height", np.where(pd.Series(levels).notna(), "osm_levels", "assumed"))
    buildings = gpd.GeoDataFrame(
        {
            "building_id": [f"B{i:04d}" for i in range(1, len(b) + 1)],
            "osm_id": b["element"].astype(str) + "/" + b["id"].astype(str),
            "building": btype,
            "name": b.get("name"),
            "height_m": height_m.round(1),
            "height_src": src,
            "households": np.nan,  # apartments only, from the overrides file
        },
        geometry=b.geometry.values,
        crs=b.crs,
    )

    # Hand corrections from a sourced figure (e.g. Serasi Residences storeys and units)
    overrides_path = DATA / "building_overrides.csv"
    if overrides_path.exists():
        ov = pd.read_csv(overrides_path).set_index("osm_id")
        hit = buildings["osm_id"].isin(ov.index)
        o = ov.loc[buildings.loc[hit, "osm_id"]]
        buildings.loc[hit, "name"] = o["name"].values
        buildings.loc[hit, "height_m"] = (o["floors"] * FLOOR_HEIGHT_M).values
        buildings.loc[hit, "height_src"] = "hand"
        buildings.loc[hit, "households"] = o["households"].values
    return buildings


def classify(row):
    if row.get("railway") == "station":
        return "transit"
    if row.get("leisure") in {"park", "playground", "garden"}:
        return "park"
    amenity = row.get("amenity")
    if amenity in SHOP_AMENITIES or pd.notna(row.get("shop")):
        return "shop"
    if pd.notna(amenity):
        return "community"
    if row.get("landuse") in {"retail", "commercial"} and pd.notna(row.get("name")):
        return "shop"
    return None


def subkind(row):
    for tag in ("railway", "leisure", "shop", "amenity", "landuse"):
        if pd.notna(row.get(tag)):
            return str(row[tag])
    return ""


def pull_places(G, buildings):
    Gp = ox.project_graph(G)
    crs = Gp.graph["crs"]
    _, edges_p = ox.graph_to_gdfs(Gp)
    named = edges_p[edges_p["name"].notna()].copy() if "name" in edges_p else edges_p.iloc[0:0]
    named["name"] = named["name"].map(first)

    def nearest_street(points):
        if named.empty:
            return ["unnamed road"] * len(points)
        idx = named.sindex.nearest(points, return_all=False)[1]
        return named["name"].iloc[idx].tolist()

    # Points of interest
    poi = with_retry(ox.features_from_point, STATION, tags=PLACE_TAGS, dist=RADIUS_M).reset_index()
    poi["kind"] = poi.apply(classify, axis=1)
    poi = poi[poi["kind"].notna()].copy()
    poi["subkind"] = poi.apply(subkind, axis=1)
    poi_pts = poi.to_crs(crs).geometry.centroid
    streets = nearest_street(poi_pts)
    poi_names = [
        n if pd.notna(n) else f"{s.replace('_', ' ').capitalize()} near {st}"
        for n, s, st in zip(poi.get("name", [None] * len(poi)), poi["subkind"], streets)
    ]
    pois = gpd.GeoDataFrame(
        {"name": poi_names, "kind": poi["kind"].values, "subkind": poi["subkind"].values, "households": np.nan},
        geometry=poi_pts.values,
        crs=crs,
    )

    # Homes: group house footprints inside the catchment into cells; one household
    # per footprint (assumption)
    bp = buildings.to_crs(crs)
    station = gpd.GeoSeries(gpd.points_from_xy([STATION[1]], [STATION[0]]), crs="EPSG:4326").to_crs(crs).iloc[0]
    bp = bp[bp.geometry.centroid.distance(station) <= RADIUS_M]
    houses = bp[bp["building"].isin(HOME_BUILDINGS)]
    c = houses.geometry.centroid
    cells = pd.DataFrame({"x": c.x, "y": c.y})
    cells["cell"] = (cells.x // HOME_CELL_M).astype(int).astype(str) + "_" + (cells.y // HOME_CELL_M).astype(int).astype(str)
    grouped = cells.groupby("cell").agg(x=("x", "mean"), y=("y", "mean"), households=("x", "size")).reset_index()
    home_pts = gpd.points_from_xy(grouped.x, grouped.y, crs=crs)
    home_streets = nearest_street(home_pts)
    homes = gpd.GeoDataFrame(
        {"name": [f"Homes - {s}" for s in home_streets], "kind": "home", "subkind": "houses",
         "households": grouped["households"].astype(float)},
        geometry=home_pts,
        crs=crs,
    )

    # Apartments: one place each; households come from data/building_overrides.csv
    apts = bp[bp["building"] == "apartments"]
    apt_pts = apts.geometry.centroid
    apartments = gpd.GeoDataFrame(
        {"name": [n if pd.notna(n) else f"Apartments near {st}" for n, st in zip(apts["name"], nearest_street(apt_pts))],
         "kind": "home", "subkind": "apartments", "households": apts["households"].values},
        geometry=apt_pts.values,
        crs=crs,
    )

    parts = [homes, apartments, pois]
    extra_path = DATA / "places_extra.csv"
    if extra_path.exists():
        extra = pd.read_csv(extra_path)
        if len(extra):
            parts.append(gpd.GeoDataFrame(
                {"name": extra["name"], "kind": extra["kind"], "subkind": "hand_list", "households": extra.get("households")},
                geometry=gpd.points_from_xy(extra.lon, extra.lat, crs="EPSG:4326"),
            ).to_crs(crs))

    places = pd.concat(parts, ignore_index=True)
    # De-duplicate names so the app's dropdown is unambiguous
    dup = places.groupby("name").cumcount()
    places.loc[dup > 0, "name"] = places["name"] + " (" + (dup + 1).astype(str) + ")"
    places["node_id"] = ox.distance.nearest_nodes(Gp, places.geometry.x, places.geometry.y)
    places = places.sort_values(["kind", "name"]).reset_index(drop=True)
    places.insert(0, "place_id", [f"P{i:03d}" for i in range(1, len(places) + 1)])
    return places.to_crs("EPSG:4326")


def coverage_map(links, buildings, places, path):
    # OSM's tile server returns 403 to maps opened from a local file, and CARTO now
    # watermarks keyless use; Esri's tiles need neither
    m = folium.Map(location=STATION, zoom_start=16, tiles=None)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/Canvas/World_Light_Gray_Base/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Light Gray", name="Light grey",
    ).add_to(m)
    folium.TileLayer(
        tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        attr="Esri World Imagery", name="Satellite",
    ).add_to(m)
    folium.GeoJson(
        buildings[["building", "height_m", "height_src", "geometry"]],
        name="Buildings",
        style_function=lambda f: {
            "color": "#9a3412" if f["properties"]["height_src"] != "assumed" else "#737373",
            "weight": 0.5, "fillOpacity": 0.35,
        },
        tooltip=folium.GeoJsonTooltip(["building", "height_m", "height_src"]),
    ).add_to(m)

    def link_style(f):
        p = f["properties"]
        colour = "#2563eb" if p["covered"] else "#16a34a" if p["highway"] in FOOT_HIGHWAYS else "#525252"
        return {"color": colour, "weight": 4 if p["covered"] else 2.5}

    folium.GeoJson(
        links[["link_id", "name", "highway", "length_m", "covered", "surface", "geometry"]],
        name="Walking links (blue = covered, green = footpath)",
        style_function=link_style,
        tooltip=folium.GeoJsonTooltip(["link_id", "name", "highway", "length_m", "covered", "surface"]),
    ).add_to(m)
    colours = {"home": "#7c3aed", "transit": "#dc2626", "shop": "#ea580c", "park": "#16a34a", "community": "#0891b2"}
    layer = folium.FeatureGroup(name="Places").add_to(m)
    for _, p in places.iterrows():
        folium.CircleMarker(
            [p.geometry.y, p.geometry.x], radius=6, color=colours[p["kind"]], fill=True, fill_opacity=0.9,
            tooltip=f"{p['place_id']} {p['name']} ({p['kind']}"
                    + (f", {int(p['households'])} households" if pd.notna(p["households"]) else "") + ")",
        ).add_to(layer)
    folium.Circle(STATION, radius=RADIUS_M, color="#dc2626", fill=False, dash_array="6").add_to(m)
    folium.LayerControl().add_to(m)
    m.save(path)


def report(links, buildings, places):
    print("\n=== OSM coverage, Putra Heights LRT, 800 m ===")
    print(f"Links: {len(links)} ({links.length_m.sum() / 1000:.1f} km)")
    print(f"  footpaths: {links.highway.isin(FOOT_HIGHWAYS).sum()}, private (gated): {links.private.sum()}, "
          f"covered=yes: {links.covered.sum()}, surface from OSM: {(links.surface_src == 'osm').sum()} (rest defaulted)")
    print(f"Buildings: {len(buildings)}, height from OSM: {buildings.height_src.str.startswith('osm').sum()}, "
          f"by hand: {(buildings.height_src == 'hand').sum()} (rest assumed)")
    utm = links.estimate_utm_crs()
    station = gpd.GeoSeries(gpd.points_from_xy([STATION[1]], [STATION[0]]), crs="EPSG:4326").to_crs(utm).iloc[0]
    inside = buildings.to_crs(utm).centroid
    inside = inside[inside.distance(station) <= RADIUS_M]
    unreached = (inside.distance(links.to_crs(utm).geometry.union_all()) > 40).sum()
    print(f"  coverage check: {unreached} of {len(inside)} buildings in the catchment are >40 m from any link")
    print("  types:", buildings.building.value_counts().head(8).to_dict())
    print("Places:", places.kind.value_counts().to_dict())
    homes = places[places.kind == "home"]
    print(f"  households (est.): {int(homes.households.sum())} across {len(homes)} home places")
    missing = homes[homes.households.isna()]
    if len(missing):
        print(f"  !! {len(missing)} home places need households set by hand:", missing.name.tolist())


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--force", action="store_true", help="overwrite existing links.geojson (link_ids will change)")
    args = parser.parse_args()

    DATA.mkdir(exist_ok=True)
    links_path = DATA / "links.geojson"
    if links_path.exists() and not args.force:
        sys.exit(f"{links_path} exists. Re-pulling renumbers link_ids and loses hand tags; use --force if you mean it.")

    ox.settings.cache_folder = str(ROOT / "cache")
    ox.settings.useful_tags_way = list(ox.settings.useful_tags_way) + ["surface", "covered", "sidewalk", "footway"]

    print("Pulling walk network...")
    G, links = pull_links()
    print("Pulling buildings...")
    buildings = pull_buildings()
    print("Pulling places...")
    places = pull_places(G, buildings)

    links.to_file(links_path, driver="GeoJSON")
    buildings.to_file(DATA / "buildings.geojson", driver="GeoJSON")
    places.to_file(DATA / "places.geojson", driver="GeoJSON")
    coverage_map(links, buildings, places, DATA / "coverage_map.html")

    report(links, buildings, places)
    print(f"\nWrote {links_path.name}, places.geojson, buildings.geojson, coverage_map.html to {DATA}")


if __name__ == "__main__":
    main()
