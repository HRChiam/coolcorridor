"""Read-only adapters between Person 2's routing engine and the Cool Route UI."""

from __future__ import annotations

import json
import math
from pathlib import Path

import networkx as nx
import pandas as pd
import pydeck as pdk
from pydeck.types import String
from pyproj import Transformer

import engine

ROUTE_LABELS = {"shortest": "Shortest route", "coolest": "Coolest route"}
ROUTE_COLORS = {"shortest": [222, 119, 34], "coolest": [0, 128, 96]}
METRICS = {
    "distance_m": "Distance (m)",
    "walking_time_min": "Walking time (min)",
    "minutes_in_sun": "Sun exposure (min)",
    "heat_exposure": "Heat exposure (°C·min)",
}


def load_places(path: Path | None = None) -> pd.DataFrame:
    """Load the real point locations and IDs used by engine.route()."""
    path = Path(path) if path is not None else engine.DATA_DIR / "places.geojson"
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("type") != "FeatureCollection" or not payload.get("features"):
        raise ValueError("The places file must contain a nonempty GeoJSON FeatureCollection")
    # RFC 7946 GeoJSON is WGS84; honor and normalize older named CRS metadata.
    crs = payload.get("crs")
    source_crs = "EPSG:4326"
    if crs is not None:
        if crs.get("type") != "name" or not crs.get("properties", {}).get("name"):
            raise ValueError("Place CRS must be a named coordinate reference system")
        source_crs = crs["properties"]["name"]
    to_lonlat = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    rows = []
    for feature in payload["features"]:
        properties = feature.get("properties") or {}
        geometry = feature.get("geometry") or {}
        if not all(properties.get(k) for k in ("place_id", "name", "kind")):
            raise ValueError("Every place needs a place_id, name and kind")
        if geometry.get("type") != "Point":
            raise ValueError("Place locations must be GeoJSON Points")
        coordinates = geometry.get("coordinates")
        if not isinstance(coordinates, (list, tuple)) or len(coordinates) < 2:
            raise ValueError("Missing place coordinates")
        lon, lat = _coordinate(to_lonlat.transform(coordinates[0], coordinates[1]))
        name, kind = str(properties["name"]), str(properties["kind"])
        label = name
        if kind == "transit" and "putra heights" in name.lower():
            label = "Putra Heights LRT Station"
        if name.startswith("Serasi Residences"):
            label += " (opens Feb 2027)"
        rows.append({"place_id": str(properties["place_id"]), "name": name,
                     "kind": kind, "label": label, "lon": lon, "lat": lat})
    places = pd.DataFrame(rows)
    if places.place_id.duplicated().any():
        raise ValueError("Place IDs must be unique")
    return places


def default_place_ids(places: pd.DataFrame) -> tuple[str, str]:
    shops = places.loc[places.kind == "shop"]
    station = places.loc[(places.kind == "transit") & places.name.str.contains("Putra Heights", case=False)]
    if shops.empty or station.empty:
        raise ValueError("A real shop and Putra Heights LRT Station are required for the default route")
    preferred = shops.loc[shops.name == "99 Speedmart"]
    return (preferred if not preferred.empty else shops).place_id.iloc[0], station.place_id.iloc[0]


def _coordinate(value) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) < 2:
        raise ValueError("Missing route or place coordinates")
    lon, lat = float(value[0]), float(value[1])
    if not math.isfinite(lon) or not math.isfinite(lat) or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ValueError("Map coordinates must be finite longitude/latitude values")
    return [lon, lat]


def route_paths(result: dict, mode: str) -> list[dict]:
    """Convert engine-returned line geometries directly to pydeck paths."""
    if not isinstance(result, dict):
        raise ValueError("No route result was returned")
    for key in METRICS:
        value = result.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
            raise ValueError(f"Route result is missing a valid {key}")
    geometry = result.get("geometry") or {}
    if geometry.get("type") != "FeatureCollection" or not geometry.get("features"):
        raise ValueError("No route geometry was returned")
    detail = (f"{result['distance_m']:.1f} m · {result['walking_time_min']:.2f} min walking\n"
              f"{result['minutes_in_sun']:.2f} min sun · {result['heat_exposure']:.3f} °C·min heat")
    rows = []
    for feature in geometry["features"]:
        line = feature.get("geometry") or {}
        if line.get("type") == "LineString":
            parts = [line.get("coordinates")]
        elif line.get("type") == "MultiLineString":
            parts = line.get("coordinates")
        else:
            raise ValueError("Route geometry must contain walking lines")
        if not parts:
            raise ValueError("Route geometry contains no coordinates")
        for part in parts:
            if not part or len(part) < 2:
                raise ValueError("Each walking line needs at least two coordinates")
            link_id = (feature.get("properties") or {}).get("link_id", "")
            rows.append({"path": [_coordinate(point) for point in part],
                         "title": f"{ROUTE_LABELS[mode]} · {link_id}", "detail": detail,
                         "link_id": link_id})
    return rows


def fetch_routes(places: pd.DataFrame, origin_id: str, destination_id: str, hour: int) -> tuple[dict, dict]:
    """Request both real routes, retaining either result if the other is unavailable."""
    if origin_id == destination_id:
        raise ValueError("Choose different origin and destination places.")
    valid_ids = set(places.place_id)
    if origin_id not in valid_ids or destination_id not in valid_ids:
        raise ValueError("Choose an origin and destination from the places list.")
    if type(hour) is not int or hour not in engine.HOURS:
        raise ValueError("Choose a departure time from 07:00 to 19:00.")
    routes, errors = {}, {}
    for mode in ROUTE_LABELS:
        try:
            result = engine.route(origin_id, destination_id, hour, mode=mode)
            route_paths(result, mode)  # Missing metrics or geometry are not drawable results.
            routes[mode] = result
        except (OSError, ValueError, TypeError, KeyError, RuntimeError, nx.NetworkXException) as exc:
            errors[mode] = str(exc)
    return routes, errors


def comparison_table(routes: dict) -> pd.DataFrame:
    return pd.DataFrame({
        ROUTE_LABELS[mode]: [result[key] for key in METRICS]
        for mode, result in routes.items()
    }, index=list(METRICS.values())).rename_axis("Metric")


def comparison_metrics(routes: dict) -> dict[str, float]:
    shortest, coolest = routes["shortest"], routes["coolest"]
    return {
        "heat_avoided": shortest["heat_exposure"] - coolest["heat_exposure"],
        "sun_minutes_avoided": shortest["minutes_in_sun"] - coolest["minutes_in_sun"],
        "extra_walking_min": coolest["walking_time_min"] - shortest["walking_time_min"],
        "extra_distance_m": coolest["distance_m"] - shortest["distance_m"],
        "extra_distance_pct": 100 * (coolest["distance_m"] / shortest["distance_m"] - 1)
        if shortest["distance_m"] else 0,
    }


def build_route_map(routes: dict, origin: dict, destination: dict,
                    visible_modes: tuple[str, ...] = ("shortest", "coolest")) -> pdk.Deck:
    """Show real paths and place points; fit the camera to all returned paths."""
    layers, points = [], [_coordinate([origin["lon"], origin["lat"]]),
                         _coordinate([destination["lon"], destination["lat"]])]
    # Draw orange first so shared links retain an orange border around green.
    for mode in ROUTE_LABELS:
        if mode not in routes:
            continue
        result = routes[mode]
        paths = route_paths(result, mode)
        points.extend(point for row in paths for point in row["path"])
        if mode in visible_modes:
            layers.append(pdk.Layer(
                "PathLayer", id=f"route-{mode}", data=paths, get_path="path",
                get_color=ROUTE_COLORS[mode], get_width=8 if mode == "shortest" else 4,
                # Plain strings become @@=accessors in pydeck; enum props need String.
                width_units=String("pixels"), width_min_pixels=1, width_max_pixels=12,
                pickable=True, cap_rounded=True, joint_rounded=True,
            ))
    endpoints = [
        {"position": points[0], "marker": "O", "title": origin["label"],
         "detail": "Origin · recorded place location", "color": [49, 75, 105]},
        {"position": points[1], "marker": "D", "title": destination["label"],
         "detail": "Destination · recorded place location", "color": [105, 63, 127]},
    ]
    layers.extend([
        pdk.Layer("ScatterplotLayer", id="places", data=endpoints, get_position="position",
                  get_fill_color="color", get_radius=12, radius_units=String("pixels"),
                  radius_min_pixels=6, radius_max_pixels=16,
                  pickable=True),
        pdk.Layer("TextLayer", id="place-labels", data=endpoints, get_position="position",
                  get_text="marker", get_color=[255, 255, 255], get_size=13,
                  size_units=String("pixels"), size_max_pixels=16,
                  get_text_anchor=String("middle"), get_alignment_baseline=String("center")),
    ])
    view = pdk.data_utils.compute_view(points)
    view.zoom = min(18, max(10, view.zoom - 0.7))
    # Keep deck.gl's geospatial viewport default (LNGLAT). Explicit numeric CRS
    # enum values differ between deck.gl versions bundled by Streamlit.
    return pdk.Deck(layers=layers, initial_view_state=view,
                    map_provider="carto", map_style=pdk.map_styles.CARTO_LIGHT,
                    tooltip={"text": "{title}\n{detail}"})
