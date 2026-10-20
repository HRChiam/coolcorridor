"""CoolCorridor Person 2: routing and township intervention planner.

Public integration contract:
    heat_at(hour) -> geopandas.GeoDataFrame
    latest_sensors() -> pandas.DataFrame
    route(origin_id, dest_id, hour, mode) -> dict   (mode: shortest | balanced | coolest)
    priorities(budget_rm) -> pandas.DataFrame
    apply_fix(link_ids, fix) -> dict   (one link_id or a list)

Input files are read from DATA_DIR, by default ./data beside this file.
Person 1 owns links.geojson and weather.csv; Person 3 owns sensors_stream.csv.
No files belonging to other people are modified by this module.

All planning prices, walking speeds, household trip rates and comfort thresholds
are explicitly labelled modelling assumptions, not measured facts.
"""

from __future__ import annotations

import math
import os
import warnings
from collections import defaultdict
from pathlib import Path
from typing import Any

import geopandas as gpd
import networkx as nx
import numpy as np
import pandas as pd
from pyproj import Geod
from shapely.geometry import LineString, MultiLineString, Point, mapping

DATA_DIR = Path(os.environ.get("COOLCORRIDOR_DATA_DIR", Path(__file__).resolve().parent / "data"))
COMFORT_C = 32.0  # Assumption from team build plan
WALKING_METRES_PER_MIN = 72.0  # Assumption: 1.2 m/s
MAX_COOLER_DETOUR = 1.25
MAX_BALANCED_DETOUR = 1.10
DETOUR_LIMITS = {"balanced": MAX_BALANCED_DETOUR, "coolest": MAX_COOLER_DETOUR}
ROUTE_MODES = ("shortest", "balanced", "coolest")
UNSAFE_COST_FACTOR = 10.0  # build plan: unsafe links only if a place is otherwise cut off
BUDGET_STEP_RM = 10.0  # planner budget search resolution; costs round up to a step
DEFAULT_HORIZON_YEARS = 10.0  # planner horizon; the app's toggle also offers 1 year ("next 12 months")
WEEKS_PER_YEAR = 52.0
MAX_BUDGET_STEPS = 50_000  # very large budgets use coarser steps to stay fast
LAMBDA_VALUES = (5, 10, 20, 40, 80, 160)
HOURS = tuple(range(7, 20))
# Weather model coefficients from Person 1 build-plan formula:
HEAT_A, HEAT_B, HEAT_C = 8.0, 4.0, 0.5
# Trips PER HOUSEHOLD PER DAY, ONE-WAY. Assumptions requiring local survey.
TRIPS_PER_HOUSEHOLD = {"transit": 0.9, "shop": 0.45, "park": 0.15, "community": 0.10}
# Hourly trip weighting across 7am-7pm, normalized to sum to 1.
HOURLY_TRIP_WEIGHTS = (0.13, 0.12, 0.07, 0.05, 0.05, 0.06, 0.06,
                       0.07, 0.08, 0.10, 0.09, 0.07, 0.05)
SOURCE_NOTE = "modelled; prices, trip rates and comfort limit are assumptions"
GEOD = Geod(ellps="WGS84")
SENSOR_COLUMNS = ["sensor_id", "link_id", "timestamp", "air_temp_c", "rh_pct", "surface_temp_c", "source"]
PRIORITY_COLUMNS = ["rank", "link_id", "fix", "cost_rm", "upkeep_rm_per_year", "cost_10y_rm", "heat_drop",
                    "person_min_saved_day", "benefit_over_horizon", "benefit_per_rm", "weeks_to_effect", "quick_win"]


def set_data_dir(path: str | Path) -> None:
    """Change data directory for an app, demo or tests; does not write anything."""
    global DATA_DIR
    DATA_DIR = Path(path)


def _read_links() -> gpd.GeoDataFrame:
    path = DATA_DIR / "links.geojson"
    if not path.is_file():
        raise FileNotFoundError(f"Person 1's {path} is missing. Run heat_model/run_all.py first.")
    links = gpd.read_file(path)
    if links.empty:
        raise ValueError(f"{path} contains no walking links")
    if links.crs is None:
        warnings.warn("links.geojson has no CRS; assuming EPSG:4326", stacklevel=2)
        links = links.set_crs(4326)
    else:
        links = links.to_crs(4326)

    if "link_id" not in links:
        for alt in ("id", "edge_id"):
            if alt in links:
                links["link_id"] = links[alt]
                break
        else:
            raise ValueError("links.geojson must provide link_id (or id / edge_id)")
    links["link_id"] = links["link_id"].astype(str)
    if links["link_id"].duplicated().any():
        raise ValueError("link_id must be unique in links.geojson")

    if "length_m" not in links:
        if "length" in links:
            links["length_m"] = links["length"]
        else:
            links["length_m"] = links.geometry.map(lambda geom: GEOD.geometry_length(geom) if geom is not None else float("nan"))
    links["length_m"] = pd.to_numeric(links["length_m"], errors="coerce")
    if links["length_m"].isna().any() or (links["length_m"] <= 0).any():
        raise ValueError("Every link must have positive length_m (metres)")

    if "covered" not in links:
        links["covered"] = False
    links["covered"] = links["covered"].map(lambda v: str(v).strip().lower() in ("1", "true", "yes", "covered"))
    if "canopy" not in links:
        links["canopy"] = 0.0
    links["canopy"] = pd.to_numeric(links["canopy"], errors="coerce").fillna(0).clip(0, 1)
    if "albedo" not in links:
        # Only needed when a fix is evaluated. Explicit model assumption.
        links["albedo"] = 0.25
    links["albedo"] = pd.to_numeric(links["albedo"], errors="coerce").fillna(0.25).clip(0, 1)
    return links


def _hour_col(links: pd.DataFrame, prefix: str, hour: int) -> str | None:
    for key in (f"{prefix}_h{hour:02d}", f"{prefix}_h{hour}"):
        if key in links:
            return key
    return None


def _shade(row: pd.Series, hour: int) -> float:
    if bool(row.get("covered", False)):
        return 1.0
    key = f"shade_h{hour:02d}"
    if key not in row:
        key = f"shade_h{hour}"
    try:
        s = float(row[key])
        if math.isfinite(s):
            return max(0.0, min(1.0, s))
    except (KeyError, ValueError, TypeError):
        pass
    return max(0.0, min(1.0, float(row.get("canopy", 0)) * 0.8))


def _heat(row: pd.Series, hour: int) -> float:
    # Sensor-corrected heat (Person 1's heat_corr_hNN) when it exists, else the model's
    for key in (f"heat_corr_h{hour:02d}", f"heat_h{hour:02d}", f"heat_h{hour}"):
        if key in row and pd.notna(row[key]):
            return float(row[key])
    raise ValueError(f"Missing Person 1's heat_h{hour:02d} in links.geojson; run heat model before routing")


def heat_at(hour: int) -> gpd.GeoDataFrame:
    """Return Person 1's computed heat map at one hour, with heat_score/shade.

    Reads (does NOT recalculate or modify) the hourly columns. heat_score is the
    sensor-corrected heat once Person 1 has run the correction (heat_corr_hNN),
    else the uncorrected model (heat_hNN), which is always kept as heat_model.
    Every other links.geojson column (e.g. unsafe, confidence) is passed through.
    Person 3 can call this as soon as Person 1 supplies the exported GeoJSON.
    """
    hour = _validate_hour(hour)
    links = _read_links()
    key = _hour_col(links, "heat", hour)
    if key is None:
        raise ValueError(f"Person 1 must first produce heat_h{hour:02d} in data/links.geojson")
    links["heat_model"] = pd.to_numeric(links[key], errors="raise")
    corrected = _hour_col(links, "heat_corr", hour)
    links["heat_score"] = pd.to_numeric(links[corrected], errors="raise") if corrected else links["heat_model"]
    links["shade"] = links.apply(lambda r: _shade(r, hour), axis=1)
    links["hour"] = hour
    return links


def latest_sensors() -> pd.DataFrame:
    """Person 3's sensor data adapter. Empty shaped result until stream exists."""
    path = DATA_DIR / "sensors_stream.csv"
    if not path.is_file():
        return pd.DataFrame(columns=SENSOR_COLUMNS)
    sensors = pd.read_csv(path)
    for col in SENSOR_COLUMNS:
        if col not in sensors:
            sensors[col] = None
    if sensors.empty:
        return sensors[SENSOR_COLUMNS].copy()
    sensors = sensors.sort_values("timestamp").drop_duplicates("sensor_id", keep="last")
    return sensors[SENSOR_COLUMNS].reset_index(drop=True)


def _validate_hour(hour: int) -> int:
    if isinstance(hour, bool) or int(hour) not in HOURS:
        raise ValueError("Hour must be 7..19 (24-hour clock)")
    return int(hour)


def _endpoints(geom: Any) -> tuple[tuple[float, float], tuple[float, float]]:
    if isinstance(geom, LineString):
        coords = list(geom.coords)
        return (tuple(coords[0][:2]), tuple(coords[-1][:2]))
    if isinstance(geom, MultiLineString):
        parts = list(geom.geoms)
        return (tuple(parts[0].coords[0][:2]), tuple(parts[-1].coords[-1][:2]))
    raise ValueError(f"Walking link geometry must be LineString/MultiLineString; got {geom.geom_type}")


def _build_graph(links: gpd.GeoDataFrame, hour: int) -> nx.MultiGraph:
    graph = nx.MultiGraph()
    has_node_ids = "u" in links.columns and "v" in links.columns
    for _, row in links.iterrows():
        p1, p2 = _endpoints(row.geometry)
        if has_node_ids and pd.notna(row["u"]) and pd.notna(row["v"]):
            u, v = f"node:{row['u']}", f"node:{row['v']}"
        else:
            u, v = f"coord:{p1[0]:.6f},{p1[1]:.6f}", f"coord:{p2[0]:.6f},{p2[1]:.6f}"
        graph.add_node(u, xy=p1)
        graph.add_node(v, xy=p2)
        graph.add_edge(u, v, key=str(row["link_id"]), link_id=str(row["link_id"]),
                       length_m=float(row["length_m"]), heat_c=_heat(row, hour),
                       shade=_shade(row, hour), unsafe=_truthy(row.get("unsafe", False)),
                       geometry=row.geometry)
    return graph


def _truthy(value: Any) -> bool:
    if value is None or (isinstance(value, float) and math.isnan(value)):
        return False
    return str(value).strip().lower() in ("1", "true", "yes", "y")


def _read_places() -> gpd.GeoDataFrame:
    path = DATA_DIR / "places.geojson"
    if not path.is_file():
        raise FileNotFoundError(f"Person 1's {path} is missing")
    places = gpd.read_file(path)
    if places.crs is None:
        places = places.set_crs(4326)
    else:
        places = places.to_crs(4326)
    if "place_id" not in places:
        if "id" in places:
            places["place_id"] = places["id"]
        else:
            raise ValueError("places.geojson needs place_id or id")
    if "kind" not in places:
        raise ValueError("places.geojson needs a 'kind' field")
    places["place_id"] = places["place_id"].astype(str)
    if places["place_id"].duplicated().any():
        raise ValueError("place_id values must be unique")
    return places


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    _, _, dist = GEOD.inv(a[0], a[1], b[0], b[1])
    return abs(dist)


def _snap(graph: nx.MultiGraph, geom: Point) -> str:
    if not isinstance(geom, Point):
        geom = geom.centroid
    xy = (float(geom.x), float(geom.y))
    return min(graph.nodes, key=lambda u: _haversine_m(xy, graph.nodes[u]["xy"]))


def _resolve_node(graph: nx.MultiGraph, places: gpd.GeoDataFrame, place_id: Any) -> str:
    place_id = str(place_id)
    if place_id in graph:
        return place_id
    prefixed = f"node:{place_id}"
    if prefixed in graph:
        return prefixed
    matching = places.loc[places.place_id == place_id]
    if matching.empty:
        raise ValueError(f"Place {place_id!r} not found in places.geojson")
    return _snap(graph, matching.geometry.iloc[0])


def _degree_minutes(edge: dict[str, Any]) -> float:
    minutes = edge["length_m"] / WALKING_METRES_PER_MIN
    return minutes * max(0.0, edge["heat_c"] - COMFORT_C)


def _edge_cost(edge: dict[str, Any], penalty: float, unsafe_factor: float | None) -> float | None:
    """length + penalty x heat exposure; unsafe links are skipped (None) unless a factor is given."""
    cost = edge["length_m"] + penalty * _degree_minutes(edge)
    if edge.get("unsafe"):
        return None if unsafe_factor is None else cost * unsafe_factor
    return cost


def _get_path(graph: nx.MultiGraph, source: str, target: str, penalty: float,
              unsafe_factor: float | None = None) -> tuple[list[str], list[dict]]:
    def edge_weight(u: str, v: str, edges: dict) -> float | None:
        costs = [c for c in (_edge_cost(d, penalty, unsafe_factor) for d in edges.values()) if c is not None]
        return min(costs) if costs else None  # None hides the edge from Dijkstra

    nodes = nx.shortest_path(graph, source, target, weight=edge_weight, method="dijkstra")
    selected = []
    for u, v in zip(nodes, nodes[1:]):
        parallel = {k: d for k, d in graph.get_edge_data(u, v).items()
                    if _edge_cost(d, penalty, unsafe_factor) is not None}
        key = min(parallel, key=lambda k: (_edge_cost(parallel[k], penalty, unsafe_factor), parallel[k]["length_m"], k))
        selected.append(parallel[key])
    return nodes, selected


def _safe_path(graph: nx.MultiGraph, source: str, target: str,
               penalty: float) -> tuple[list[str], list[dict], bool]:
    """Path that skips unsafe links; if none exists, unsafe links cost 10x and the path is flagged."""
    try:
        return (*_get_path(graph, source, target, penalty), False)
    except nx.NetworkXNoPath:
        return (*_get_path(graph, source, target, penalty, UNSAFE_COST_FACTOR), True)


def _route_stats(path: list[dict]) -> dict:
    length = sum(p["length_m"] for p in path)
    exposure = sum(_degree_minutes(p) for p in path)
    in_sun = sum((p["length_m"] / WALKING_METRES_PER_MIN) * (1 - p["shade"]) for p in path)
    geoms = [mapping(p["geometry"]) for p in path]
    # FeatureCollection is directly consumed by GeoPandas/Streamlit/Folium.
    return {
        "link_ids": [p["link_id"] for p in path],
        "path": [p["link_id"] for p in path],
        "distance_m": round(length, 2),
        "walking_time_min": round(length / WALKING_METRES_PER_MIN, 3),
        "minutes_in_sun": round(in_sun, 3),
        "heat_exposure": round(exposure, 3),  # degrees C x walking minutes
        "geometry": {"type": "FeatureCollection", "features": [
            {"type": "Feature", "properties": {"link_id": p["link_id"]}, "geometry": g}
            for p, g in zip(path, geoms)
        ]},
    }


def _route_in_graph(graph: nx.MultiGraph, src: str, dst: str, mode: str,
                    max_detour: float | None = None) -> dict:
    """Shared route solver; expensive file reads happen only in public adapter.

    max_detour overrides the mode's detour cap (e.g. 1.30 for a sensitivity check).
    """
    if src == dst:
        raise ValueError("Origin and destination snap to the same graph node")
    try:
        _, baseline, uses_unsafe = _safe_path(graph, src, dst, 0)
    except (nx.NodeNotFound, nx.NetworkXNoPath) as e:
        raise ValueError("No connected walking path between these points") from e
    # Cooler candidates follow the same unsafe-link rule as the shortest route
    unsafe_factor = UNSAFE_COST_FACTOR if uses_unsafe else None
    short = _route_stats(baseline)
    picked = baseline
    if mode in DETOUR_LIMITS:
        best = (short["heat_exposure"], short["distance_m"])
        seen = set()
        for penalty in LAMBDA_VALUES:
            _, candidate = _get_path(graph, src, dst, penalty, unsafe_factor)
            ids = tuple(edge["link_id"] for edge in candidate)
            if ids in seen:
                continue
            seen.add(ids)
            stats = _route_stats(candidate)
            if stats["distance_m"] > short["distance_m"] * (max_detour or DETOUR_LIMITS[mode]) + 1e-9:
                continue
            contender = (stats["heat_exposure"], stats["distance_m"])
            if contender < best:
                best, picked = contender, candidate
    output = _route_stats(picked)
    output.update({
        "mode": mode,
        "extra_distance_pct": round(100 * (output["distance_m"] / short["distance_m"] - 1), 2),
        "heat_avoided": round(max(0.0, short["heat_exposure"] - output["heat_exposure"]), 3),
        "uses_unsafe": uses_unsafe,
        "warning": ("No route avoids unsafe roads; this one uses a road without a known footpath"
                    if uses_unsafe else None),
        "shortest": {k: v for k, v in short.items() if k != "geometry"},
        "heat_units": f"degree-C-minutes above {COMFORT_C:g}C comfort threshold (assumed)",
        "data_label": "Person 1 heat model; corrections may use simulated sensors",
    })
    return output


def route(origin_id: Any, dest_id: Any, hour: int, mode: str = "coolest") -> dict:
    """Compute the shortest, balanced (max 10% detour) or coolest (max 25%) route.

    For cooler routes, run exactly six heat-weighted shortest-path searches using
    lambda 5/10/20/40/80/160; choose minimal exposure among eligible candidates.
    Does NOT enumerate all simple paths. Every mode skips links marked unsafe; if
    that leaves no route, unsafe links cost 10x and the result has uses_unsafe=True.
    """
    hour = _validate_hour(hour)
    if mode not in ROUTE_MODES:
        raise ValueError(f"mode must be one of {', '.join(repr(m) for m in ROUTE_MODES)}")
    links = heat_at(hour)
    graph = _build_graph(links, hour)
    places = _read_places()
    src = _resolve_node(graph, places, origin_id)
    dst = _resolve_node(graph, places, dest_id)
    result = _route_in_graph(graph, src, dst, mode)
    result.update({"origin_id": str(origin_id), "dest_id": str(dest_id), "hour": hour})
    return result


def _category(kind: Any) -> str:
    kind = str(kind).strip().lower()
    if any(x in kind for x in ("home", "resident", "housing", "house")):
        return "home"
    if any(x in kind for x in ("lrt", "mrt", "transit", "station", "bus", "rail")):
        return "transit"
    if any(x in kind for x in ("shop", "market", "mall", "retail", "store")):
        return "shop"
    if "park" in kind or "garden" in kind:
        return "park"
    if any(x in kind for x in ("community", "hall", "library", "centre", "center")):
        return "community"
    return kind


def walking_demand() -> pd.DataFrame:
    """Assign assumed home-to-destination trips along SHORTEST routes.

    Output one row per link with flow_h07...flow_h19 and flow_day.
    Households and trip rates are assumptions when not supplied by Person 1.
    """
    links = _read_links()
    graph = _build_graph(links, HOURS[0])
    places = _read_places()
    places["category"] = places["kind"].map(_category)
    homes = places.loc[places.category == "home"]
    if homes.empty:
        warnings.warn("No home places found; walking demand is zero", stacklevel=2)
    profile_sum = sum(HOURLY_TRIP_WEIGHTS)
    flow: dict[str, dict[int, float]] = defaultdict(lambda: defaultdict(float))
    for _, home in homes.iterrows():
        households = pd.to_numeric(home.get("households", 1), errors="coerce")
        if pd.isna(households):
            households = 1
        households = max(0.0, float(households))
        home_node = _snap(graph, home.geometry)
        for category, daily_trips in TRIPS_PER_HOUSEHOLD.items():
            candidates = places.loc[places.category == category]
            if candidates.empty:
                continue
            # Choose destination by shortest WALKING distance, not straight-line distance.
            best_path: list[dict] | None = None
            best_m = float("inf")
            for _, destination in candidates.iterrows():
                dest_node = _snap(graph, destination.geometry)
                if home_node == dest_node:
                    continue
                try:
                    _, path, _ = _safe_path(graph, home_node, dest_node, 0)
                except nx.NetworkXNoPath:
                    continue
                dist = sum(e["length_m"] for e in path)
                if dist < best_m:
                    best_m, best_path = dist, path
            if best_path is None:
                warnings.warn(f"No walking connection for home {home['place_id']} to {category}", stacklevel=2)
                continue
            for h, time_share in zip(HOURS, HOURLY_TRIP_WEIGHTS):
                trips = households * daily_trips * time_share / profile_sum
                for edge in best_path:
                    flow[edge["link_id"]][h] += trips
    records = []
    for lid in links.link_id:
        values = {f"flow_h{h:02d}": round(flow[lid][h], 6) for h in HOURS}
        records.append({"link_id": lid, **values, "flow_day": round(sum(values.values()), 6)})
    return pd.DataFrame(records)


def _weather_radiation() -> dict[int, float]:
    """Read measured Open-Meteo radiation; no silently invented planning benefit."""
    path = DATA_DIR / "weather.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing: interventions need hourly solar radiation")
    weather = pd.read_csv(path)
    radiance = next((c for c in (
        "sw_wm2","shortwave_radiation", "shortwave_radiation_wm2", "shortwave_radiation_w_m2",
        "shortwave_radiation_w_m2", "solar_radiation", "radiation_wm2", "sunlight_wm2",
        "shortwave", "R_wm2", "R") if c in weather.columns), None)
    if radiance is None:
        raise ValueError("weather.csv needs shortwave_radiation (W/m2) for intervention estimates")
    hour_col = next((c for c in ("hour", "hour_local") if c in weather.columns), None)
    if hour_col:
        hours = pd.to_numeric(weather[hour_col], errors="coerce")
    else:
        time_col = next((c for c in ("time", "timestamp", "datetime", "date") if c in weather.columns), None)
        if time_col is None:
            raise ValueError("weather.csv needs 'hour' or a timestamp column")
        hours = pd.to_datetime(weather[time_col], errors="coerce").dt.hour
    weather = weather.copy()
    weather["_hour"] = hours
    weather["_solar"] = pd.to_numeric(weather[radiance], errors="coerce")
    filtered = weather.dropna(subset=["_hour", "_solar"])
    mapping_by_hour = filtered.groupby("_hour")["_solar"].mean().to_dict()
    absent = [h for h in HOURS if h not in mapping_by_hour]
    if absent:
        raise ValueError(f"weather.csv has no solar radiation data for these hours: {absent}")
    if (filtered["_solar"] < 0).any():
        raise ValueError("Radiation cannot be negative")
    return {h: float(mapping_by_hour[h]) for h in HOURS}


def _read_fixes() -> pd.DataFrame:
    path = DATA_DIR / "interventions.csv"
    if not path.is_file():
        raise FileNotFoundError(f"{path} missing: copy Person 2's interventions.csv into data/")
    fixes = pd.read_csv(path)
    needed = {"fix", "cost_rm_per_m", "shade_gain", "albedo_gain",
              "weeks_to_effect", "maintenance_rm_per_year", "quick_win", "note"}
    if not needed.issubset(fixes):
        raise ValueError(f"interventions.csv must have {sorted(needed)}")
    if fixes["fix"].duplicated().any():
        raise ValueError("Fix names must be unique")
    for c in ("cost_rm_per_m", "shade_gain", "albedo_gain", "weeks_to_effect", "maintenance_rm_per_year"):
        fixes[c] = pd.to_numeric(fixes[c], errors="raise")
    fixes["quick_win"] = fixes["quick_win"].map(_truthy)
    if (fixes.cost_rm_per_m <= 0).any() or (fixes[["shade_gain", "albedo_gain"]] < 0).any().any():
        raise ValueError("Intervention cost must be positive and gains nonnegative")
    if (fixes[["weeks_to_effect", "maintenance_rm_per_year"]] < 0).any().any():
        raise ValueError("weeks_to_effect and maintenance_rm_per_year must be nonnegative")
    return fixes


def _calculate_fix(row: pd.Series, fix: pd.Series, radiation: dict[int, float]) -> dict:
    length = float(row["length_m"])
    original_alpha = float(row["albedo"])
    after_alpha = min(1.0, original_alpha + float(fix["albedo_gain"]))
    original_heat, new_heat = {}, {}
    original_shade, new_shade = {}, {}
    for hour in HOURS:
        s0 = _shade(row, hour)
        # The fix blocks a share shade_gain of the sun still reaching the link, the
        # same way Person 1's shade model adds trees on top of building shadow
        s1 = s0 + (1.0 - s0) * float(fix["shade_gain"])
        # Covered walkway should provide full shade, even if shade_gain < 1.
        if str(fix["fix"]) == "covered_walkway":
            s1 = 1.0
        r = radiation[hour] / 1000.0
        h0 = _heat(row, hour)
        # Same heat formula as the team build plan; only solar term changes.
        old_solar = (1.0 - s0) * r * (HEAT_A + HEAT_B * (1 - original_alpha))
        new_solar = (1.0 - s1) * r * (HEAT_A + HEAT_B * (1 - after_alpha))
        original_heat[hour], new_heat[hour] = h0, h0 + new_solar - old_solar
        original_shade[hour], new_shade[hour] = s0, s1
    cost = length * float(fix["cost_rm_per_m"])
    return {"link_id": str(row["link_id"]), "fix": str(fix["fix"]),
            "cost_rm": round(cost, 2), "heat_drop": round(max(0.0, original_heat[13] - new_heat[13]), 4),
            "weeks_to_effect": int(fix["weeks_to_effect"]), "quick_win": bool(fix["quick_win"]),
            "maintenance_rm_per_year": round(length * float(fix["maintenance_rm_per_year"]), 2),
            "before": {"albedo": original_alpha,
                       "heat_by_hour": {f"h{h:02d}": round(original_heat[h], 4) for h in HOURS},
                       "shade_by_hour": {f"h{h:02d}": round(original_shade[h], 4) for h in HOURS}},
            "after": {"albedo": after_alpha,
                      "heat_by_hour": {f"h{h:02d}": round(new_heat[h], 4) for h in HOURS},
                      "shade_by_hour": {f"h{h:02d}": round(new_shade[h], 4) for h in HOURS}},
            "_baseline_heat": original_heat, "_new_heat": new_heat,
            "data_label": SOURCE_NOTE}


def _benefit(fix_result: dict, hourly_flow: pd.Series, length_m: float) -> float:
    minutes = length_m / WALKING_METRES_PER_MIN
    return sum(
        float(hourly_flow[f"flow_h{h:02d}"]) * minutes * (
            max(0.0, fix_result["_baseline_heat"][h] - COMFORT_C)
            - max(0.0, fix_result["_new_heat"][h] - COMFORT_C))
        for h in HOURS
    )


def apply_fix(link_ids: Any, fix: str) -> dict:
    """What-if simulation; returns before/after hourly heat and area-wide totals.

    link_ids is one link_id or a list of them. For one link, the result is that
    link's before/after plus area totals. For a list, it is {"links": [one result
    per link], ...} with cost, person-minutes saved and area totals for all of
    them together (benefits add up: flows follow shortest routes, not heat).

    Recomputes Person 1's solar heat FORMULA DIFFERENCE (without modifying links),
    so changes preserve its current hourly baseline including sensor corrections.
    """
    single = isinstance(link_ids, str) or not hasattr(link_ids, "__iter__")
    ids = [str(link_ids)] if single else list(dict.fromkeys(str(i) for i in link_ids))
    if not ids:
        raise ValueError("apply_fix needs at least one link_id")
    links = _read_links()
    unknown = [i for i in ids if i not in set(links.link_id)]
    if unknown:
        raise ValueError(f"Unknown link_id {unknown[0]!r}" if single else f"Unknown link_ids {unknown}")
    fixes = _read_fixes()
    named = fixes.loc[fixes["fix"] == fix]
    if named.empty:
        raise ValueError(f"Unknown fix {fix!r}; choices: {', '.join(fixes['fix'])}")
    radiation = _weather_radiation()
    flows = walking_demand().set_index("link_id")
    total_before = _total_heat_exposure(links, flows)
    units = "person-degree-C-minutes above comfort threshold per day"

    results = []
    for link_id in ids:
        row = links.loc[links.link_id == link_id].iloc[0]
        result = _calculate_fix(row, named.iloc[0], radiation)
        benefit = _benefit(result, flows.loc[link_id], float(row.length_m))
        result["person_min_saved_day"] = round(benefit, 3)
        result["benefit_per_rm"] = round(benefit / result["cost_rm"], 8)
        result["area_before"] = round(total_before, 3)
        result["area_after"] = round(max(0.0, total_before - benefit), 3)
        result["area_units"] = units
        del result["_baseline_heat"]
        del result["_new_heat"]
        results.append(result)
    if single:
        return results[0]

    cost = sum(r["cost_rm"] for r in results)
    saved = sum(r["person_min_saved_day"] for r in results)
    return {"link_ids": ids, "fix": str(fix), "links": results,
            "cost_rm": round(cost, 2), "person_min_saved_day": round(saved, 3),
            "benefit_per_rm": round(saved / cost, 8),
            "weeks_to_effect": results[0]["weeks_to_effect"], "quick_win": results[0]["quick_win"],
            "maintenance_rm_per_year": round(sum(r["maintenance_rm_per_year"] for r in results), 2),
            "area_before": round(total_before, 3), "area_after": round(max(0.0, total_before - saved), 3),
            "area_units": units, "data_label": SOURCE_NOTE}


def _total_heat_exposure(links: gpd.GeoDataFrame, flow: pd.DataFrame) -> float:
    flow_by_link = flow.set_index("link_id") if "link_id" in flow.columns else flow
    total = 0.0
    for _, row in links.iterrows():
        counts = flow_by_link.loc[str(row["link_id"])]
        walk_mins = float(row["length_m"]) / WALKING_METRES_PER_MIN
        for hour in HOURS:
            total += (float(counts[f"flow_h{hour:02d}"]) * walk_mins *
                      max(0.0, _heat(row, hour) - COMFORT_C))
    return total


def _best_mix(options: list[dict], budget_rm: float, cost_key: str = "cost_rm",
              benefit_key: str = "person_min_saved_day") -> list[dict]:
    """The set of fixes with the most person-minutes saved within the budget, at most one per link.

    Exact search (multiple-choice knapsack) by dynamic programming over the budget
    in steps of BUDGET_STEP_RM, coarser for very large budgets. Costs are rounded UP
    to a step, so the chosen set never exceeds the budget. Unlike picking fixes one
    by one by benefit per RM, it doesn't leave money on the table.
    """
    if not options or budget_rm <= 0:
        return []
    step = max(BUDGET_STEP_RM, math.ceil(budget_rm / MAX_BUDGET_STEPS))
    capacity = int(budget_rm // step)
    groups: dict[str, list[dict]] = defaultdict(list)
    for option in options:
        groups[option["link_id"]].append(option)
    group_list = list(groups.values())

    def steps(option: dict) -> int:
        return math.ceil(option[cost_key] / step - 1e-9)

    best = np.zeros(capacity + 1)  # best[c]: most benefit with at most c budget steps
    choices = np.full((len(group_list), capacity + 1), -1, dtype=np.int8)
    for g, group in enumerate(group_list):
        new = best.copy()
        for j, option in enumerate(group):
            w = steps(option)
            if w > capacity:
                continue
            candidate = np.full(capacity + 1, -np.inf)
            candidate[w:] = best[:capacity + 1 - w] + option[benefit_key]
            better = candidate > new + 1e-12
            new[better] = candidate[better]
            choices[g, better] = j
        best = new

    picked, c = [], capacity
    for g in range(len(group_list) - 1, -1, -1):
        j = choices[g, c]
        if j >= 0:
            picked.append(group_list[g][j])
            c -= steps(group_list[g][j])
    return picked


def effect_share(weeks_to_effect: float, horizon_weeks: float) -> float:
    """Average share of a fix's full effect over the horizon.

    The effect is assumed to grow steadily from nothing to full over weeks_to_effect,
    then stay full: 1 - w/(2H) if the fix is fully working within the horizon,
    otherwise H/(2w) (e.g. a tree needing 5 years gives 10% over 12 months).
    """
    w, h = float(weeks_to_effect), float(horizon_weeks)
    if w <= 0:
        return 1.0
    return 1 - w / (2 * h) if w <= h else h / (2 * w)


def _check_horizon(horizon_years: float) -> float:
    horizon_years = float(horizon_years)
    if not math.isfinite(horizon_years) or horizon_years <= 0:
        raise ValueError("horizon_years must be positive")
    return horizon_years


def _fix_options(links: gpd.GeoDataFrame, flow: pd.DataFrame, fixes: pd.DataFrame,
                 horizon_years: float, upkeep_scale: float = 1.0) -> list[dict]:
    """Every (link, fix) with a positive benefit over the horizon, with its costs."""
    radiation = _weather_radiation()
    options = []
    for _, row in links.iterrows():
        for _, fix in fixes.iterrows():
            result = _calculate_fix(row, fix, radiation)
            benefit = _benefit(result, flow.loc[str(row.link_id)], float(row.length_m))
            cost = result["cost_rm"]
            upkeep = result["maintenance_rm_per_year"] * upkeep_scale
            benefit_h = benefit * effect_share(result["weeks_to_effect"], horizon_years * WEEKS_PER_YEAR)
            if benefit_h > 1e-9 and cost > 0:
                options.append({"link_id": str(row.link_id), "fix": fix["fix"],
                                "cost_rm": cost, "upkeep_rm_per_year": round(upkeep, 2),
                                "cost_10y_rm": round(cost + 10 * upkeep, 2),
                                "heat_drop": result["heat_drop"],
                                "person_min_saved_day": benefit,
                                "benefit_over_horizon": benefit_h,
                                "benefit_per_rm": benefit_h / cost,
                                "weeks_to_effect": result["weeks_to_effect"],
                                "quick_win": result["quick_win"]})
    return options


def fix_options(horizon_years: float = DEFAULT_HORIZON_YEARS, upkeep_scale: float = 1.0) -> pd.DataFrame:
    """All candidate fixes (one row per link and fix) with benefit and costs.

    upkeep_scale multiplies the assumed upkeep, for sensitivity checks; value_10y
    is benefit over the horizon per RM of 10-year total cost (build + 10 x upkeep).
    """
    horizon_years = _check_horizon(horizon_years)
    options = pd.DataFrame(_fix_options(_read_links(), walking_demand().set_index("link_id"),
                                        _read_fixes(), horizon_years, upkeep_scale))
    if not options.empty:
        options["value_10y"] = options["benefit_over_horizon"] / options["cost_10y_rm"]
    return options


def priorities(budget_rm: float, quick_wins_only: bool = False,
               horizon_years: float = DEFAULT_HORIZON_YEARS) -> pd.DataFrame:
    """Best set of interventions within the building budget, at most one per link, ranked.

    The budget covers building (upfront) costs only; upkeep is shown alongside,
    per fix (upkeep_rm_per_year, cost_10y_rm = build + 10 x upkeep) and in total
    (.attrs), since build and upkeep budgets usually differ.
    Fixes are judged over a horizon (the app's toggle: 1 year = "next 12 months",
    10 years): benefit_over_horizon = full daily benefit x effect_share(weeks to
    take effect, horizon). The set is found by an exact search (see _best_mix),
    then listed by benefit per RM of build cost.
    Only positive-benefit improvements that fit within the budget are returned.
    Benefit is (assumed daily walkers) x (walking minutes) x (degrees over 32C)
    saved per day, not an empirically established health outcome. Each fix
    carries weeks_to_effect and quick_win; quick_wins_only=True ranks only fixes
    that work within months, i.e. what helps this year.
    """
    budget_rm = float(budget_rm)
    if not math.isfinite(budget_rm) or budget_rm < 0:
        raise ValueError("budget_rm must be a nonnegative, finite amount")
    horizon_years = _check_horizon(horizon_years)
    links = _read_links()
    flow = walking_demand().set_index("link_id")
    fixes = _read_fixes()
    if quick_wins_only:
        fixes = fixes[fixes.quick_win]
    proposed = _fix_options(links, flow, fixes, horizon_years)
    picked = _best_mix(proposed, budget_rm, cost_key="cost_rm", benefit_key="benefit_over_horizon")
    picked.sort(key=lambda d: (-d["benefit_per_rm"], -d["benefit_over_horizon"], d["cost_rm"], d["link_id"]))
    selected = [{"rank": i + 1, **option} for i, option in enumerate(picked)]
    answer = pd.DataFrame(selected, columns=PRIORITY_COLUMNS)
    for col in ("person_min_saved_day", "benefit_over_horizon", "benefit_per_rm", "heat_drop"):
        if col in answer:
            answer[col] = answer[col].round(5)
    answer.attrs["budget_rm"] = budget_rm
    answer.attrs["horizon_years"] = horizon_years
    answer.attrs["spent_rm"] = round(sum(o["cost_rm"] for o in picked), 2)  # building cost
    answer.attrs["upkeep_rm_per_year"] = round(sum(o["upkeep_rm_per_year"] for o in picked), 2)
    answer.attrs["cost_10y_rm"] = round(sum(o["cost_10y_rm"] for o in picked), 2)
    answer.attrs["area_before"] = round(_total_heat_exposure(links, flow), 3)
    # Average over the horizon: fixes still growing count for part of their effect
    answer.attrs["area_after"] = round(max(0.0, answer.attrs["area_before"] - answer["benefit_over_horizon"].sum()), 3)
    answer.attrs["data_label"] = SOURCE_NOTE
    return answer


def save_priorities(budget_rm: float, output_file: str | Path | None = None,
                    horizon_years: float = DEFAULT_HORIZON_YEARS) -> pd.DataFrame:
    """Explicitly write ONLY Person 2's priorities.csv."""
    table = priorities(budget_rm, horizon_years=horizon_years)
    output = Path(output_file) if output_file is not None else DATA_DIR / "priorities.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    table.to_csv(output, index=False)
    return table


def route_summary(sample_limit: int | None = None, hour: int | None = None, mode: str = "coolest",
                  max_detour: float | None = None) -> dict:
    """Report the modelled cooler-route share and per-trip benefits.

    Hour=None evaluates all hours 07..19, weighted by assumed trip demand per
    home and destination category. If hour is given, evaluates that hour only.
    Uses nearest destination by WALKING distance, as walking_demand() does.
    mode is "coolest" (max 25% detour, the results number) or "balanced" (10%);
    max_detour overrides the cap for a sensitivity check (e.g. 1.30).
    The cooler-route share is reported against all trips and against the trips
    whose shortest route has any heat exposure (only those can be improved).
    """
    if mode not in DETOUR_LIMITS:
        raise ValueError(f"mode must be one of {', '.join(repr(m) for m in DETOUR_LIMITS)}")
    hours = HOURS if hour is None else (_validate_hour(hour),)
    links = _read_links()
    places = _read_places()
    places["category"] = places.kind.map(_category)
    homes = places.loc[places.category == "home"]
    graph_7am = _build_graph(links, HOURS[0])
    od_pairs = []
    for _, home in homes.iterrows():
        home_node = _snap(graph_7am, home.geometry)
        households = pd.to_numeric(home.get("households", 1), errors="coerce")
        if pd.isna(households):
            households = 1
        for category, trips_per_home in TRIPS_PER_HOUSEHOLD.items():
            candidates = places.loc[places.category == category]
            best_dest = None
            shortest_dist = float("inf")
            for _, dest in candidates.iterrows():
                dest_node = _snap(graph_7am, dest.geometry)
                if dest_node == home_node:
                    continue
                try:
                    _, path, _ = _safe_path(graph_7am, home_node, dest_node, 0)
                except nx.NetworkXNoPath:
                    continue
                length = sum(e["length_m"] for e in path)
                if length < shortest_dist:
                    best_dest, shortest_dist = dest_node, length
            if best_dest is not None:
                od_pairs.append((home_node, best_dest, max(0.0, float(households)) * trips_per_home))
            if sample_limit is not None and len(od_pairs) >= sample_limit:
                break
        if sample_limit is not None and len(od_pairs) >= sample_limit:
            break
    totals = {"total": 0., "exposed": 0., "improved": 0., "heat": 0., "distance_pct": 0., "sun_minutes": 0.,
              "unsafe": 0.}
    for h in hours:
        graph = _build_graph(links, h)
        trip_hour_weight = HOURLY_TRIP_WEIGHTS[h - 7] / sum(HOURLY_TRIP_WEIGHTS)
        for src, dst, base_weight in od_pairs:
            weight = base_weight * (1 if hour is not None else trip_hour_weight)
            if weight <= 0:
                continue
            try:
                cool = _route_in_graph(graph, src, dst, mode, max_detour)
            except ValueError:
                continue
            totals["total"] += weight
            totals["exposed"] += weight * (cool["shortest"]["heat_exposure"] > 1e-9)
            totals["unsafe"] += weight * cool["uses_unsafe"]
            if cool["heat_avoided"] > 1e-9:
                totals["improved"] += weight
                totals["heat"] += weight * cool["heat_avoided"]
                totals["distance_pct"] += weight * cool["extra_distance_pct"]
                # Walking sun exposure for baseline computed from recorded links.
                short_links = cool["shortest"]["link_ids"]
                by_id = {edge["link_id"]: edge for u, v, key, edge in graph.edges(keys=True, data=True)}
                baseline_sun = sum((by_id[lid]["length_m"] / WALKING_METRES_PER_MIN) * (1 - by_id[lid]["shade"])
                                   for lid in short_links)
                totals["sun_minutes"] += weight * (baseline_sun - cool["minutes_in_sun"])
    improved = totals["improved"]
    return {
        "trips_with_cooler_route_pct": round(100 * improved / totals["total"], 2) if totals["total"] else 0.0,
        "trips_with_heat_exposure_pct": round(100 * totals["exposed"] / totals["total"], 2) if totals["total"] else 0.0,
        "exposed_trips_with_cooler_route_pct": (round(100 * improved / totals["exposed"], 2)
                                                if totals["exposed"] else 0.0),
        "mean_heat_avoided_per_improved_trip": round(totals["heat"] / improved, 3) if improved else 0.0,
        "mean_extra_distance_pct_per_improved_trip": round(totals["distance_pct"] / improved, 2) if improved else 0.0,
        "mean_sun_minutes_avoided_per_improved_trip": round(totals["sun_minutes"] / improved, 2) if improved else 0.0,
        "trips_needing_unsafe_link_pct": round(100 * totals["unsafe"] / totals["total"], 2) if totals["total"] else 0.0,
        "mode": mode,
        "max_detour_pct": round(100 * ((max_detour or DETOUR_LIMITS[mode]) - 1)),
        "evaluated_home_destination_pairs": len(od_pairs),
        "hour": hour if hour is not None else "07:00-19:00 demand-weighted",
        "data_label": SOURCE_NOTE,
    }


def save_flow_to_links() -> Path:
    """Explicitly fill Person 2-owned flow_day and flow_hNN in Person 1's GeoJSON.

    Only feature properties are updated, preserving geometry and all model fields.
    Call from your own Git branch after confirming the current input data is ready.
    """
    import json
    import tempfile

    path = DATA_DIR / "links.geojson"
    # Run both validators before opening the file for write.
    flows = walking_demand().set_index("link_id")
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if payload.get("type") != "FeatureCollection":
        raise ValueError("Expected a GeoJSON FeatureCollection")
    for f in payload["features"]:
        p = f.setdefault("properties", {})
        lid = str(p.get("link_id", p.get("id", p.get("edge_id", ""))))
        if lid not in flows.index:
            raise ValueError(f"Cannot match GeoJSON link_id {lid!r} to demand table")
        p["flow_day"] = float(flows.loc[lid, "flow_day"])
        for hour in HOURS:
            p[f"flow_h{hour:02d}"] = float(flows.loc[lid, f"flow_h{hour:02d}"])
    # Replace atomically; never leave partially written GeoJSON.
    with tempfile.NamedTemporaryFile("w", suffix=".geojson", dir=path.parent,
                                     encoding="utf-8", delete=False) as out:
        staging = Path(out.name)
        json.dump(payload, out, ensure_ascii=False)
    try:
        os.replace(staging, path)
    finally:
        if staging.exists():
            staging.unlink()
    return path
