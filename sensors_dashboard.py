"""Read-only sensor replay, independent anomaly detection and dashboard charts."""

from dataclasses import dataclass
from pathlib import Path

import altair as alt
import numpy as np
import pandas as pd
import pydeck as pdk
from pydeck.types import String
import streamlit as st

from cool_route import _coordinate
from simulate_sensors import SENSOR_COLUMNS, load_config

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
TZ = "Asia/Kuala_Lumpur"
AIR_ANOMALY_THRESHOLD_C = 3.0
STALE_LIMIT_MIN = 10
STATUS_COLORS = {"Active": [0, 128, 96], "Stale": [191, 135, 0],
                 "Missing": [105, 110, 120], "Anomaly": [211, 55, 55]}


@dataclass
class SensorData:
    sites: pd.DataFrame
    readings: pd.DataFrame
    timeline: pd.DataFrame
    config: object
    notices: list[str]


def detect_anomalies(readings):
    """Causal detector: no fault schedule, seed or future samples are consulted."""
    groups = []
    for _, group in readings.groupby("sensor_id", sort=True):
        group = group.sort_values("timestamp").copy()
        residual = pd.Series((group.air_temp_c - group.weather_air_c).to_numpy(),
                             index=pd.DatetimeIndex(group.timestamp))
        baseline = residual.rolling("30min", closed="left", min_periods=3).median()
        group["weather_delta_c"] = residual.to_numpy()
        group["baseline_delta_c"] = baseline.to_numpy()
        group["departure_c"] = residual.to_numpy() - baseline.to_numpy()
        group["anomaly"] = group.departure_c.abs() > AIR_ANOMALY_THRESHOLD_C
        groups.append(group)
    if not groups:
        result = readings.copy()
        for col in ("weather_delta_c", "baseline_delta_c", "departure_c"):
            result[col] = pd.Series(dtype=float)
        result["anomaly"] = pd.Series(dtype=bool)
        return result
    return pd.concat(groups, ignore_index=True).sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)


def load_sensor_data(data_dir=None, config_path=None):
    directory = Path(data_dir) if data_dir is not None else DATA
    sites = pd.read_csv(directory / "sensor_links.csv")
    required_sites = {"sensor_id", "link_id", "site_type", "lat", "lon"}
    if (not required_sites.issubset(sites.columns) or len(sites) != 8
            or sites[list(required_sites)].isna().any().any()
            or sites.sensor_id.duplicated().any() or sites.link_id.duplicated().any()):
        raise ValueError("Expected eight unique sensor sites with IDs, link IDs and coordinates")
    sites["position"] = [_coordinate([lon, lat]) for lon, lat in zip(sites.lon, sites.lat)]
    sites = sites.sort_values("sensor_id").reset_index(drop=True)
    weather = pd.read_csv(directory / "weather.csv")
    weather = weather.loc[weather.day == "design"].sort_values("hour")
    if list(weather.hour) != list(range(7, 20)) or weather.date.nunique() != 1:
        raise ValueError("Design weather must contain one date with hours 07..19 exactly once")
    weather["air_temp_c"] = pd.to_numeric(weather.air_temp_c, errors="raise")
    if not np.isfinite(weather.air_temp_c).all():
        raise ValueError("Design-day weather air temperatures must be finite")
    date = str(weather.date.iloc[0])
    times = pd.date_range(f"{date} 07:00", f"{date} 19:00", freq="5min", tz=TZ)
    timeline = pd.DataFrame({"timestamp": times, "weather_air_c": np.interp(
        times.hour + times.minute / 60, weather.hour, weather.air_temp_c)})
    notices = []
    try:
        config = load_config(Path(config_path) if config_path is not None else ROOT / "config/sensor_simulation.json")
    except (OSError, ValueError, TypeError) as exc:
        config = None
        notices.append(f"Simulation configuration unavailable; injected fault annotations omitted: {exc}")
    path = directory / "sensors_stream.csv"
    if not path.exists():
        notices.append("Sensor stream unavailable. Locations and weather remain visible; no sensor values are invented.")
        readings = pd.DataFrame(columns=SENSOR_COLUMNS)
    else:
        readings = pd.read_csv(path)
    if not set(SENSOR_COLUMNS).issubset(readings.columns):
        raise ValueError("Sensor stream must match the seven-column simulator contract")
    if not readings.source.eq("simulated").all():
        raise ValueError("Every sensor reading must be labelled simulated")
    if not readings.sensor_id.map(sites.set_index("sensor_id").link_id).eq(readings.link_id).all():
        raise ValueError("Sensor stream contains an unknown sensor or mismatched link ID")
    if not readings.empty and not readings.timestamp.astype(str).str.contains(r"(?:[+-]\d{2}:\d{2}|Z)$", regex=True).all():
        raise ValueError("Sensor timestamps must include a timezone offset")
    readings["timestamp"] = pd.to_datetime(readings.timestamp, utc=True, errors="raise").dt.tz_convert(TZ)
    if readings.timestamp.isna().any() or readings.duplicated(["sensor_id", "timestamp"]).any():
        raise ValueError("Sensor timestamps must be valid and unique per sensor")
    if (readings.timestamp.dt.minute.mod(5).ne(0) | readings.timestamp.dt.second.ne(0)
            | readings.timestamp.dt.microsecond.ne(0)).any():
        raise ValueError("Sensor readings must align to the five-minute replay schedule")
    for col in ("air_temp_c", "rh_pct", "surface_temp_c"):
        readings[col] = pd.to_numeric(readings[col], errors="raise")
        if not np.isfinite(readings[col]).all():
            raise ValueError(f"Sensor stream contains invalid {col}")
    if not readings.rh_pct.between(0, 100).all():
        raise ValueError("Relative humidity must be within 0..100%")
    valid = readings.timestamp.isin(times)
    if (~valid).any():
        notices.append(f"Ignored {int((~valid).sum())} readings outside the design-day replay window.")
    readings = readings.loc[valid].merge(timeline, on="timestamp", how="left", validate="many_to_one")
    return SensorData(sites, detect_anomalies(readings), timeline, config, notices)


def replay_target(data, minutes):
    if type(minutes) is not int or minutes not in range(7 * 60, 19 * 60 + 1, 5):
        raise ValueError("Replay time must be a five-minute step between 07:00 and 19:00")
    return data.timeline.timestamp.iloc[0].normalize() + pd.Timedelta(minutes=minutes)


def sensor_statuses(data, target):
    """Keep all sites; freshness and anomalies refer only to the replay instant."""
    if target not in set(data.timeline.timestamp):
        raise ValueError("Replay timestamp must belong to the design-day timeline")
    eligible = data.readings.loc[data.readings.timestamp <= target]
    latest = eligible.sort_values("timestamp").drop_duplicates("sensor_id", keep="last").set_index("sensor_id")
    rows = []
    for site in data.sites.to_dict("records"):
        row = dict(site, status="Missing", sample_time="", age_min=float("nan"),
                   air_temp_c=float("nan"), rh_pct=float("nan"), surface_temp_c=float("nan"),
                   departure_c=float("nan"))
        if site["sensor_id"] in latest.index:
            sample = latest.loc[site["sensor_id"]]
            age = (target - sample.timestamp).total_seconds() / 60
            row.update(sample_time=sample.timestamp.isoformat(), age_min=age)
            if age <= STALE_LIMIT_MIN:
                row.update({col: sample[col] for col in ("air_temp_c", "rh_pct", "surface_temp_c", "departure_c")})
                row["status"] = "Stale" if age else ("Anomaly" if sample.anomaly else "Active")
        rows.append(row)
    return pd.DataFrame(rows)


def sensor_history(data, sensor_id, target, full_day=False):
    if sensor_id not in set(data.sites.sensor_id):
        raise ValueError("Choose a sensor from the recorded sites")
    timeline = data.timeline if full_day else data.timeline.loc[data.timeline.timestamp <= target]
    history = timeline.merge(data.readings.loc[data.readings.sensor_id == sensor_id].drop(columns="weather_air_c"),
                             on="timestamp", how="left", validate="one_to_one")
    history["segment"] = history.air_temp_c.isna().cumsum()
    history["local_timestamp"] = history.timestamp.map(lambda t: t.isoformat())
    return history


def detected_events(data, target, sensor_id=None):
    events = data.readings.loc[data.readings.anomaly & (data.readings.timestamp <= target)].copy()
    if sensor_id is not None:
        events = events.loc[events.sensor_id == sensor_id]
    return events


def injected_faults(data):
    """Configured intent, kept separate from observations and detection rules."""
    config = data.config
    if config is None:
        return pd.DataFrame(columns=["sensor_id", "kind", "start", "end", "description"])
    date = data.timeline.timestamp.iloc[0].date().isoformat()
    start = pd.Timestamp(f"{date} {config.silent_start}", tz=TZ)
    spike = pd.Timestamp(f"{date} {config.spike_time}", tz=TZ)
    return pd.DataFrame([
        {"sensor_id": config.silent_sensor, "kind": "Configured outage", "start": start,
         "end": start + pd.Timedelta(minutes=config.silent_minutes),
         "description": f"No samples from {config.silent_start} inclusive for {config.silent_minutes} min; end excluded"},
        {"sensor_id": config.spike_sensor, "kind": "Configured spike", "start": spike, "end": spike,
         "description": f"Configured +{config.spike_delta_c:g}°C to air and surface at {config.spike_time}"},
    ])


def build_sensor_map(snapshot, selected_id):
    dots = []
    for row in snapshot.to_dict("records"):
        detail = f"{row['status']} · {row['site_type']} · {row['link_id']}"
        if row["sample_time"]:
            detail += f"\nLast seen: {row['sample_time']} ({row['age_min']:g} min old)"
        if pd.notna(row["air_temp_c"]):
            detail += f"\nSIMULATED air {row['air_temp_c']:.2f}°C · RH {row['rh_pct']:.1f}%\nSurface {row['surface_temp_c']:.2f}°C"
        dots.append(dict(position=row["position"], sensor_id=row["sensor_id"],
                         color=STATUS_COLORS[row["status"]], radius=13 if row["sensor_id"] == selected_id else 10,
                         title=f"{row['sensor_id']} · SIMULATED DATA", detail=detail))
    view = pdk.data_utils.compute_view([row["position"] for row in dots])
    view.zoom = min(17, max(12, view.zoom - .7))
    return pdk.Deck(layers=[
        pdk.Layer("ScatterplotLayer", id="dashboard-sensors", data=dots, get_position="position",
                  get_fill_color="color", get_radius="radius", radius_units=String("pixels"),
                  radius_min_pixels=6, radius_max_pixels=15, pickable=True),
        pdk.Layer("TextLayer", id="dashboard-sensor-labels", data=dots, get_position="position",
                  get_text="sensor_id", get_color=[255, 255, 255], get_size=10,
                  size_units=String("pixels"), size_max_pixels=12,
                  get_text_anchor=String("middle"), get_alignment_baseline=String("center")),
    ], initial_view_state=view, map_provider="carto", map_style=pdk.map_styles.CARTO_LIGHT,
        tooltip={"text": "{title}\n{detail}"})


def history_charts(history, faults, sensor_id):
    # UTC scale represents actual instants; labels explicitly show UTC+8 wall time
    # regardless of the browser's own timezone. Tooltip strings retain +08:00.
    axis = alt.Axis(labelExpr="utcFormat(time(toDate(datum.value)) + 28800000, '%H:%M')", tickCount=6)
    domain = [history.timestamp.min().isoformat(), history.timestamp.max().isoformat()]
    x = alt.X("timestamp:T", title="Replay time (Asia/Kuala_Lumpur)", scale=alt.Scale(type="utc", domain=domain), axis=axis)
    tooltip = [alt.Tooltip("local_timestamp:N", title="Sample time (+08:00)")]
    observed = history.loc[history.air_temp_c.notna()].copy()
    annotations = []
    for fault in faults.loc[faults.sensor_id == sensor_id].itertuples():
        if fault.start > history.timestamp.max():
            continue
        frame = pd.DataFrame([{"timestamp": fault.start, "end": min(fault.end, history.timestamp.max())}])
        if fault.kind == "Configured outage":
            annotations.append(alt.Chart(frame).mark_rect(color="#ed9b28", opacity=.13, clip=True)
                               .encode(x=x, x2="end:T"))
        else:
            annotations.append(alt.Chart(frame).mark_rule(color="#8155a3", strokeDash=[5, 4], clip=True).encode(x=x))
    air = alt.Chart(observed).mark_line(color="#cc6331", point=True, clip=True).encode(
        x=x, y=alt.Y("air_temp_c:Q", title="Air temperature (°C)", scale=alt.Scale(zero=False)),
        detail="segment:N", color=alt.value("#cc6331"),
        tooltip=tooltip + [alt.Tooltip("air_temp_c:Q", title="SIMULATED air (°C)", format=".3f")])
    weather = alt.Chart(history).mark_line(color="#2676af", strokeDash=[5, 3], clip=True).encode(
        x=x, y=alt.Y("weather_air_c:Q", title="Air temperature (°C)"),
        tooltip=tooltip + [alt.Tooltip("weather_air_c:Q", title="Weather air (°C)", format=".3f")])
    anomaly = alt.Chart(observed.loc[observed.anomaly.fillna(False)]).mark_point(color="#cf3131", size=95, filled=True).encode(
        x=x, y=alt.Y("air_temp_c:Q", title="Air temperature (°C)"), color=alt.value("#cf3131"),
        tooltip=tooltip + [alt.Tooltip("departure_c:Q", title="Detected departure (°C)", format="+.3f")])
    charts = {"air": alt.layer(*annotations, air, weather, anomaly).properties(height=270)}
    for col, title, color, name in (("rh_pct", "Relative humidity (%)", "#2676af", "humidity"),
                                    ("surface_temp_c", "Surface temperature (°C)", "#9b5c35", "surface")):
        line = alt.Chart(observed).mark_line(color=color, point=True, clip=True).encode(
            x=x, y=alt.Y(f"{col}:Q", title=title, scale=alt.Scale(zero=False)),
            detail="segment:N", color=alt.value(color),
            tooltip=tooltip + [alt.Tooltip(f"{col}:Q", title=title, format=".2f")])
        charts[name] = alt.layer(*annotations, line).properties(height=200)
    return charts


def render_sensors():
    st.subheader("Sensors Dashboard")
    st.info("SIMULATED DATA — all sensor measurements are synthetic. This dashboard demonstrates "
            "replay and data-quality checks, not real-world sensor accuracy or health risk.")
    try:
        data = load_sensor_data()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        st.error(f"Sensor data could not be loaded: {exc}")
        return
    for notice in data.notices:
        st.warning(notice)
    controls, sensor_control = st.columns([3, 2])
    default_minute = 13 * 60 + 5
    minutes = controls.select_slider("Sensor replay time", options=list(range(420, 1141, 5)), value=default_minute,
                                      format_func=lambda m: f"{m // 60:02d}:{m % 60:02d}", key="sensors_time")
    labels = data.sites.set_index("sensor_id").site_type.to_dict()
    sensor_id = sensor_control.selectbox("Sensor", data.sites.sensor_id.tolist(),
                                         format_func=lambda s: f"{s} · {labels[s]}", key="sensors_selected")
    target = replay_target(data, minutes)
    snapshot = sensor_statuses(data, target)
    events = detected_events(data, target)
    faults = injected_faults(data)
    st.caption(f"Replay: {target.isoformat()} · Statuses use replay time, never today's date. "
               "Green: Active · Yellow: Stale · Grey: Missing · Red: Anomaly.")
    fresh, unavailable, anomalies, total = st.columns(4)
    fresh.metric("Current samples", str(snapshot.status.isin(["Active", "Anomaly"]).sum()) + "/8")
    unavailable.metric("Stale / missing", str(snapshot.status.isin(["Stale", "Missing"]).sum()))
    anomalies.metric("Anomalous now", str(snapshot.status.eq("Anomaly").sum()))
    total.metric("Detected events so far", str(len(events)))
    st.pydeck_chart(build_sensor_map(snapshot, sensor_id), height=360, key="sensors_status_map",
                    alt="Eight actual sensor sites colored by replay-time data quality status")
    selected = snapshot.set_index("sensor_id").loc[sensor_id]
    st.write(f"**{sensor_id} — {selected['status']}** · {labels[sensor_id]} · {selected['link_id']}")
    air, humidity, surface = st.columns(3)
    air.metric("SIMULATED air", "Unavailable" if pd.isna(selected.air_temp_c) else f"{selected.air_temp_c:.3f} °C")
    humidity.metric("SIMULATED humidity", "Unavailable" if pd.isna(selected.rh_pct) else f"{selected.rh_pct:.2f} %")
    surface.metric("SIMULATED surface", "Unavailable" if pd.isna(selected.surface_temp_c) else f"{selected.surface_temp_c:.3f} °C")
    st.caption(f"Last observed sample: {selected.sample_time or 'none'}. "
               "Stale values retain their original sample time; values over ten minutes old are withheld.")
    full_day = st.checkbox("Show full design-day history (includes readings after replay time)", key="sensors_full_day")
    history = sensor_history(data, sensor_id, target, full_day)
    charts = history_charts(history, faults, sensor_id)
    st.subheader("Air temperature versus design-day weather")
    st.caption("Orange: simulated sensor air · Blue dashed: interpolated weather air · Red points: detected anomalies. "
               "Purple dashed rule / amber band: configured spike / outage. No heat score is plotted.")
    st.altair_chart(charts["air"], width="stretch")
    left, right = st.columns(2)
    left.altair_chart(charts["humidity"], width="stretch")
    right.altair_chart(charts["surface"], width="stretch")
    st.caption("Missing samples remain gaps; sensor values are never interpolated. Full-day history, if enabled, "
               "does not change replay-time statuses or event counts.")
    with st.expander("Detection rules and known injected faults", expanded=False):
        st.write("Active: exact-time sample without a detected anomaly. Stale: latest sample 5–10 minutes old. "
                 "Missing: no prior sample or age over 10 minutes. Anomaly: current air-minus-weather departure "
                 "differs by more than 3°C from its previous 30-minute median, requiring three prior samples. "
                 "The detector does not use the configured fault schedule. Surface spikes are shown but not independently detected.")
        st.caption("These are provisional demonstration thresholds. The first three samples are detector warm-up. "
                   "Known faults below are configured intent, not detected evidence; editing config does not regenerate the CSV.")
        if data.config is not None:
            st.write(f"Configured seed: {data.config.seed}")
            display_faults = faults.copy()
            for col in ("start", "end"):
                display_faults[col] = display_faults[col].map(lambda t: t.isoformat())
            st.dataframe(display_faults, hide_index=True, width="stretch")
    st.subheader("Detected anomalies up to replay time")
    if events.empty:
        st.write("No air-temperature anomalies detected so far.")
    else:
        display_events = events[["sensor_id", "timestamp", "air_temp_c", "weather_air_c", "departure_c"]].copy()
        display_events["timestamp"] = display_events.timestamp.map(lambda t: t.isoformat())
        display_events = display_events.rename(columns={"air_temp_c": "Air (°C)", "weather_air_c": "Weather air (°C)",
                                                         "departure_c": "Detected departure (°C)"})
        st.dataframe(display_events, hide_index=True, width="stretch")
    st.subheader("All sensor statuses")
    status_table = snapshot[["sensor_id", "link_id", "status", "sample_time", "age_min", "air_temp_c", "rh_pct", "surface_temp_c"]]
    st.dataframe(status_table.rename(columns={"air_temp_c": "Air (°C)", "rh_pct": "Humidity (%)",
                                              "surface_temp_c": "Surface (°C)"}), hide_index=True, width="stretch")
    with st.expander("Selected sensor readings with timestamps", expanded=False):
        table = history[["local_timestamp", "air_temp_c", "rh_pct", "surface_temp_c", "weather_air_c", "departure_c"]].copy()
        st.dataframe(table.rename(columns={"air_temp_c": "Air (°C)", "rh_pct": "Humidity (%)",
                                           "surface_temp_c": "Surface (°C)", "weather_air_c": "Weather air (°C)",
                                           "departure_c": "Detected departure (°C)"}), hide_index=True, width="stretch")
