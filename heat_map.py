"""Read-only heat-network and replay-sensor preparation for the Heat Map tab."""

import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
import pydeck as pdk
from pydeck.types import String

from cool_route import _coordinate
from heat_model.heat import HOURS, TZ, design_weather, heat_at

DATA = Path(__file__).resolve().parent / "data"
HEAT_MIN, HEAT_MAX = 26.0, 44.0
# A fixed, perceptually ordered cool-to-hot palette, shared by paths and legend.
COLOR_STOPS = ((26, (49, 54, 149)), (30, (69, 180, 195)), (34, (254, 224, 139)),
               (38, (244, 109, 67)), (44, (165, 0, 38)))


def validate_hour(hour):
    if type(hour) is not int or hour not in HOURS:
        raise ValueError("Replay hour must be a whole hour from 07:00 to 19:00")


def heat_color(value):
    value = float(value)
    if not math.isfinite(value):
        raise ValueError("Heat values must be finite")
    return [int(round(np.interp(value, [p[0] for p in COLOR_STOPS],
                                 [p[1][channel] for p in COLOR_STOPS]))) for channel in range(3)]


def load_heat_data(hour):
    """Use Person 1's public interface; inspect column availability for honest labels."""
    validate_hour(hour)
    links = heat_at(hour).copy()
    if links.empty or links.crs is None:
        raise ValueError("Heat network must be nonempty and have a coordinate reference system")
    links = links.to_crs(epsg=4326)
    required = {"link_id", "length_m", "heat", "heat_model", "shade", "covered", "canopy", "surface", "albedo"}
    if not required.issubset(links.columns):
        raise ValueError(f"Heat network is missing columns: {sorted(required - set(links.columns))}")
    if links.link_id.isna().any() or links.link_id.duplicated().any():
        raise ValueError("Walking link IDs must be present and unique")
    for col in ("length_m", "heat", "heat_model", "shade", "canopy", "albedo"):
        links[col] = pd.to_numeric(links[col], errors="raise")
        if not np.isfinite(links[col]).all():
            raise ValueError(f"Heat network has invalid {col}")
    if (links.length_m <= 0).any() or not links[["shade", "canopy", "albedo"]].apply(lambda c: c.between(0, 1).all()).all():
        raise ValueError("Link lengths must be positive; shade, canopy and albedo must be in 0..1")
    links["covered"] = links.covered.map(lambda v: str(v).lower() in ("true", "yes", "1"))
    payload = json.loads((DATA / "links.geojson").read_text(encoding="utf-8"))
    corrected_col = f"heat_corr_h{hour:02d}"
    corrected = [corrected_col in f["properties"] for f in payload["features"]]
    if any(corrected) and not all(corrected):
        raise ValueError("Corrected heat columns are incomplete; coordinate the shared output with Person 1")
    links.attrs["sensor_corrected"] = bool(corrected) and all(corrected)
    raw = pd.DataFrame([f["properties"] for f in payload["features"]]).set_index("link_id")
    source_column = corrected_col if links.attrs["sensor_corrected"] else f"heat_h{hour:02d}"
    if (set(raw.index) != set(links.link_id)
            or not np.allclose(links.heat.to_numpy(), raw.loc[links.link_id, source_column].to_numpy(dtype=float),
                               rtol=0, atol=1e-9)):
        raise ValueError("Heat reader contains cached values from an older file. Restart the app to reload shared heat data")
    return links


def replay_date(hour):
    validate_hour(hour)
    weather = design_weather()
    if weather.date.nunique() != 1 or hour not in weather.index:
        raise ValueError("Design weather must contain a single replay date and the selected hour")
    return str(weather.loc[hour, "date"])


def sensor_snapshot(hour, date, *, stream_path=None):
    """Latest same-day reading <= replay time; never borrow future readings.

    Exact-time samples are current. Samples up to five minutes old are labelled
    stale. Older samples are withheld, while all eight site markers remain.
    """
    validate_hour(hour)
    sites = pd.read_csv(DATA / "sensor_links.csv")
    if len(sites) != 8 or sites.sensor_id.duplicated().any() or sites.link_id.duplicated().any():
        raise ValueError("Expected eight distinct sensor sites and link IDs")
    sites["position"] = [_coordinate([lon, lat]) for lon, lat in zip(sites.lon, sites.lat)]
    for col in ("air_temp_c", "rh_pct", "surface_temp_c"):
        sites[col] = float("nan")
    sites["timestamp"] = ""
    sites["status"] = "No recent simulated reading"
    path = Path(stream_path) if stream_path is not None else DATA / "sensors_stream.csv"
    if not path.exists():
        sites.attrs["stream_available"] = False
        return sites
    readings = pd.read_csv(path)
    required = {"sensor_id", "link_id", "timestamp", "air_temp_c", "rh_pct", "surface_temp_c", "source"}
    if not required.issubset(readings.columns):
        raise ValueError("Sensor stream does not match the seven-column sensor contract")
    if not readings.source.eq("simulated").all():
        raise ValueError("Sensor stream contains rows not labelled simulated")
    mapping = sites.set_index("sensor_id").link_id
    if not readings.sensor_id.map(mapping).eq(readings.link_id).all():
        raise ValueError("Sensor stream contains an unknown or mismatched sensor/link ID")
    readings["at"] = pd.to_datetime(readings.timestamp, utc=True, errors="raise").dt.tz_convert(TZ)
    for col in ("air_temp_c", "rh_pct", "surface_temp_c"):
        readings[col] = pd.to_numeric(readings[col], errors="raise")
        if not np.isfinite(readings[col]).all():
            raise ValueError("Sensor readings must be finite")
    if not readings.rh_pct.between(0, 100).all():
        raise ValueError("Sensor humidity must be in 0..100")
    target = pd.Timestamp(date).normalize().tz_localize(TZ) + pd.Timedelta(hours=hour)
    eligible = readings.loc[(readings["at"].dt.date == target.date()) & (readings["at"] <= target)
                            & (readings["at"] >= target - pd.Timedelta(minutes=5))]
    latest = eligible.sort_values("at").drop_duplicates("sensor_id", keep="last").set_index("sensor_id")
    for index, site in sites.iterrows():
        if site.sensor_id not in latest.index:
            continue
        row = latest.loc[site.sensor_id]
        for col in ("air_temp_c", "rh_pct", "surface_temp_c"):
            sites.loc[index, col] = row[col]
        sites.loc[index, "timestamp"] = row["at"].isoformat()
        age = int((target - row["at"]).total_seconds() / 60)
        sites.loc[index, "status"] = "SIMULATED" if age == 0 else f"SIMULATED · stale ({age} min old)"
    sites.attrs["stream_available"] = True
    return sites


def heat_summary(links):
    hottest = links.sort_values(["heat", "link_id"], ascending=[False, True]).iloc[0]
    return {"average": float(links.heat.mean()), "hottest": float(hottest.heat),
            "hottest_id": hottest.link_id, "ties": int(links.heat.eq(hottest.heat).sum()),
            "shade": float(np.average(links.shade, weights=links.length_m)), "count": len(links)}


def link_paths(links):
    rows = []
    for link in links.itertuples():
        geometry = link.geometry
        if geometry is None or geometry.is_empty or geometry.geom_type not in ("LineString", "MultiLineString"):
            raise ValueError("Walking links must contain nonempty LineString or MultiLineString geometry")
        parts = list(geometry.geoms) if geometry.geom_type == "MultiLineString" else [geometry]
        for part in parts:
            path = [_coordinate(list(p)) for p in part.coords]
            rows.append({"path": path, "link_id": link.link_id, "heat": float(link.heat),
                         "color": heat_color(link.heat), "shade": float(link.shade),
                         "covered": bool(link.covered), "canopy": float(link.canopy),
                         "title": f"{link.link_id} · {link.name or 'Unnamed walking link'}",
                         "detail": f"Modelled heat index: {link.heat:.2f} °C\n"
                                   f"Uncorrected model: {link.heat_model:.2f} °C\n"
                                   f"Shade: {link.shade:.0%} · Covered: {'Yes' if link.covered else 'No'}\n"
                                   f"Tree canopy: {link.canopy:.0%}\nSurface: {link.surface} · Albedo: {link.albedo:.2f}"})
    return rows


def build_heat_map(links, sensors, *, covered=False, canopy=False, shade=False):
    paths = link_paths(links)
    if set(sensors.link_id) - set(links.link_id):
        raise ValueError("Sensor sites reference links missing from the heat network")
    layers = []

    def path_layer(layer_id, data, color, width):
        return pdk.Layer("PathLayer", id=layer_id, data=data, get_path="path", get_color=color,
                         get_width=width, width_units=String("pixels"), width_min_pixels=1,
                         width_max_pixels=12, cap_rounded=True, joint_rounded=True, pickable=True)

    if shade:
        shaded = [dict(p, overlay_color=[40, 48, 64, int(p["shade"] * 180)]) for p in paths if p["shade"] > 0]
        layers.append(path_layer("heat-shade", shaded, "overlay_color", 10))
    if canopy:
        trees = [dict(p, overlay_color=[0, 100, 65, int(80 + p["canopy"] * 175)]) for p in paths if p["canopy"] > 0]
        layers.append(path_layer("heat-canopy", trees, "overlay_color", 8))
    if covered:
        layers.append(path_layer("heat-covered", [p for p in paths if p["covered"]], [42, 94, 224], 7))
    layers.append(path_layer("heat-network", paths, "color", 4))
    dots = []
    for site in sensors.itertuples():
        available = pd.notna(site.air_temp_c)
        detail = f"{site.status}\nSite: {site.site_type} · Link: {site.link_id}"
        if available:
            detail += (f"\nAir: {site.air_temp_c:.2f} °C · RH: {site.rh_pct:.1f}%"
                       f"\nSurface: {site.surface_temp_c:.2f} °C\nReading: {site.timestamp}")
        dots.append({"position": site.position, "sensor_id": site.sensor_id,
                     "title": f"{site.sensor_id} · sensor site", "detail": detail,
                     "color": [88, 48, 141] if available else [105, 110, 120]})
    layers.extend([
        pdk.Layer("ScatterplotLayer", id="heat-sensors", data=dots, get_position="position",
                  get_fill_color="color", get_radius=11, radius_units=String("pixels"),
                  radius_min_pixels=6, radius_max_pixels=14, pickable=True),
        pdk.Layer("TextLayer", id="heat-sensor-labels", data=dots, get_position="position",
                  get_text="sensor_id", get_color=[255, 255, 255], get_size=10,
                  size_units=String("pixels"), size_max_pixels=12,
                  get_text_anchor=String("middle"), get_alignment_baseline=String("center")),
    ])
    view = pdk.data_utils.compute_view([point for p in paths for point in p["path"]])
    view.zoom = min(18, max(10, view.zoom - .7))
    return pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto",
                    map_style=pdk.map_styles.CARTO_LIGHT, tooltip={"text": "{title}\n{detail}"})


def legend_html():
    colors = ", ".join(f"rgb{rgb} {(value - HEAT_MIN) / (HEAT_MAX - HEAT_MIN) * 100:.2f}%"
                       for value, rgb in COLOR_STOPS)
    return ('<div aria-label="Fixed heat index scale from 26 to 44 degrees Celsius">'
            f'<div style="height:14px;border-radius:5px;background:linear-gradient(to right,{colors})"></div>'
            '<div style="display:flex;justify-content:space-between;font-size:13px">'
            + ''.join(f'<span>{value}°C</span>' for value in (26, 32, 38, 44)) + '</div></div>')
