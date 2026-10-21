"""Real-data sensor replay, fault handling, charts and dashboard integration."""

from dataclasses import replace
from pathlib import Path
import json
import shutil
import sys

import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import sensors_dashboard as dashboard


@pytest.fixture(scope="module")
def data():
    return dashboard.load_sensor_data()


@pytest.fixture
def inputs(tmp_path):
    for name in ("sensor_links.csv", "weather.csv", "sensors_stream.csv"):
        shutil.copyfile(ROOT / "data" / name, tmp_path / name)
    return tmp_path


def sensor_tab(at):
    return next(tab for tab in at.tabs if tab.label == "Sensors")


def test_loads_real_readings_sites_and_timezone(data):
    original = pd.read_csv(ROOT / "data/sensors_stream.csv")
    sites = pd.read_csv(ROOT / "data/sensor_links.csv")
    assert len(data.sites) == 8
    assert len(data.readings) == len(original) == 1154
    assert len(data.timeline) == 145
    assert str(data.readings.timestamp.dt.tz) == "Asia/Kuala_Lumpur"
    assert data.readings.source.eq("simulated").all()
    assert data.sites.position.tolist() == [[row.lon, row.lat] for row in sites.itertuples()]
    assert data.readings.air_temp_c.sum() == pytest.approx(original.air_temp_c.sum())
    assert data.config.seed == 20260906


def test_weather_comparison_uses_interpolated_design_air_not_heat(data):
    row = data.readings.loc[(data.readings.sensor_id == "S01") & (data.readings.timestamp.dt.strftime("%H:%M") == "13:05")].iloc[0]
    assert row.weather_air_c == pytest.approx(34.4 + (35.3 - 34.4) / 12)
    assert row.air_temp_c == 43.738
    assert row.weather_delta_c == pytest.approx(row.air_temp_c - row.weather_air_c)
    assert data.timeline.weather_air_c.iloc[-1] == 31.7
    assert not any(col.startswith("heat") for col in data.readings.columns)


@pytest.mark.parametrize("minute", [419, 421, 1145, True, 785.0])
def test_invalid_replay_selection_rejected(data, minute):
    with pytest.raises(ValueError, match="five-minute"):
        dashboard.replay_target(data, minute)


def test_statuses_are_causal_and_anomaly_resolves(data):
    before = dashboard.sensor_statuses(data, dashboard.replay_target(data, 780)).set_index("sensor_id")
    spike = dashboard.sensor_statuses(data, dashboard.replay_target(data, 785)).set_index("sensor_id")
    after = dashboard.sensor_statuses(data, dashboard.replay_target(data, 790)).set_index("sensor_id")
    assert before.loc["S01", "status"] == "Active"
    assert spike.loc["S01", "status"] == "Anomaly"
    assert after.loc["S01", "status"] == "Active"
    assert before.loc["S01", "sample_time"].endswith("13:00:00+08:00")
    assert len(dashboard.detected_events(data, dashboard.replay_target(data, 780))) == 0
    assert len(dashboard.detected_events(data, dashboard.replay_target(data, 790))) == 1


@pytest.mark.parametrize("minute,status,age", [(715, "Active", 0), (720, "Stale", 5),
    (725, "Stale", 10), (730, "Missing", 15), (745, "Missing", 30), (750, "Active", 0)])
def test_real_outage_boundaries_and_recovery(data, minute, status, age):
    snapshot = dashboard.sensor_statuses(data, dashboard.replay_target(data, minute)).set_index("sensor_id")
    assert snapshot.loc["S02", "status"] == status
    assert snapshot.loc["S02", "age_min"] == age
    if status == "Missing":
        assert pd.isna(snapshot.loc["S02", "air_temp_c"])
        assert snapshot.loc["S02", "sample_time"].endswith("11:55:00+08:00")
    assert len(snapshot) == 8


def test_detector_is_causal_and_independent_of_fault_config(data):
    target = dashboard.replay_target(data, 785)
    events = dashboard.detected_events(data, target)
    assert len(events) == 1
    event = events.iloc[0]
    assert event.sensor_id == "S01"
    assert event.timestamp == target
    assert event.departure_c == pytest.approx(7.6825)
    prior = data.readings.loc[(data.readings.sensor_id == "S01") & (data.readings.timestamp < target)
                             & (data.readings.timestamp >= target - pd.Timedelta(minutes=30))]
    assert event.baseline_delta_c == pytest.approx(prior.weather_delta_c.median())
    modified = replace(data, config=replace(data.config, spike_sensor="S08", spike_time="09:00", spike_delta_c=99))
    pd.testing.assert_frame_equal(events, dashboard.detected_events(modified, target))
    prefix = data.readings.loc[data.readings.timestamp <= target].drop(columns=[
        "weather_delta_c", "baseline_delta_c", "departure_c", "anomaly"])
    recomputed = dashboard.detect_anomalies(prefix)
    pd.testing.assert_frame_equal(data.readings.loc[data.readings.timestamp <= target].reset_index(drop=True),
                                  recomputed.reset_index(drop=True))


def test_known_fault_metadata_is_separate(data):
    faults = dashboard.injected_faults(data).set_index("kind")
    outage = faults.loc["Configured outage"]
    assert outage.sensor_id == "S02"
    assert outage.start.strftime("%H:%M") == "12:00"
    assert outage.end.strftime("%H:%M") == "12:30"
    assert "+8°C" in faults.loc["Configured spike", "description"]


def test_history_gaps_weather_and_full_day_option(data):
    target = dashboard.replay_target(data, 745)
    prefix = dashboard.sensor_history(data, "S02", target)
    full = dashboard.sensor_history(data, "S02", target, full_day=True)
    assert prefix.timestamp.max() == target
    assert len(full) == 145
    assert full.timestamp.max() > target
    missing = full.loc[full.air_temp_c.isna()]
    assert missing.timestamp.dt.strftime("%H:%M").tolist() == ["12:00", "12:05", "12:10", "12:15", "12:20", "12:25"]
    assert full.weather_air_c.notna().all()
    assert full.loc[full.timestamp.dt.strftime("%H:%M") == "11:55", "segment"].iloc[0] != full.loc[
        full.timestamp.dt.strftime("%H:%M") == "12:30", "segment"].iloc[0]


def test_missing_and_header_only_stream_keep_sites_and_weather(inputs):
    # Rename only a pytest-owned fixture, leaving the committed stream untouched.
    (inputs / "sensors_stream.csv").rename(inputs / "original.csv")
    empty = dashboard.load_sensor_data(inputs)
    assert empty.readings.empty
    assert empty.notices
    snapshot = dashboard.sensor_statuses(empty, dashboard.replay_target(empty, 785))
    assert len(snapshot) == 8 and snapshot.status.eq("Missing").all()
    assert snapshot.air_temp_c.isna().all()
    history = dashboard.sensor_history(empty, "S01", dashboard.replay_target(empty, 785))
    assert history.weather_air_c.notna().all()
    assert history.air_temp_c.isna().all()
    pd.DataFrame(columns=dashboard.SENSOR_COLUMNS).to_csv(inputs / "sensors_stream.csv", index=False)
    assert dashboard.load_sensor_data(inputs).readings.empty


@pytest.mark.parametrize("problem", ["wrong_link", "duplicate", "naive", "humidity", "missing_column", "schedule", "source"])
def test_bad_stream_contract_rejected(inputs, problem):
    path = inputs / "sensors_stream.csv"
    frame = pd.read_csv(path)
    if problem == "wrong_link":
        frame.loc[0, "link_id"] = "unknown"
    elif problem == "duplicate":
        frame = pd.concat([frame, frame.iloc[:1]])
    elif problem == "naive":
        frame.loc[0, "timestamp"] = "2026-09-06T07:00:00"
    elif problem == "humidity":
        frame.loc[0, "rh_pct"] = 101
    elif problem == "missing_column":
        frame = frame.drop(columns="surface_temp_c")
    elif problem == "schedule":
        frame.loc[0, "timestamp"] = "2026-09-06T07:01:00+08:00"
    else:
        frame.loc[0, "source"] = "unknown"
    frame.to_csv(path, index=False)
    with pytest.raises(ValueError):
        dashboard.load_sensor_data(inputs)


def test_other_day_is_excluded_and_missing_config_is_nonfatal(inputs):
    path = inputs / "sensors_stream.csv"
    readings = pd.read_csv(path)
    readings["timestamp"] = readings.timestamp.str.replace("2026-09-06", "2026-09-07")
    readings.to_csv(path, index=False)
    data = dashboard.load_sensor_data(inputs, config_path=inputs / "missing.json")
    assert data.readings.empty
    assert data.config is None
    assert dashboard.injected_faults(data).empty
    assert len(data.notices) == 2


def test_map_serialization_and_all_real_positions(data):
    snapshot = dashboard.sensor_statuses(data, dashboard.replay_target(data, 785))
    deck = json.loads(dashboard.build_sensor_map(snapshot, "S01").to_json())
    layers = {layer["id"]: layer for layer in deck["layers"]}
    markers = layers["dashboard-sensors"]
    assert markers["radiusUnits"] == "pixels" and markers["radiusMaxPixels"] <= 15
    assert layers["dashboard-sensor-labels"]["sizeUnits"] == "pixels"
    assert layers["dashboard-sensor-labels"]["getTextAnchor"] == "middle"
    assert len(markers["data"]) == 8
    assert [d["position"] for d in markers["data"]] == data.sites.position.tolist()
    assert markers["data"][0]["color"] == dashboard.STATUS_COLORS["Anomaly"]
    assert deck["mapProvider"] == "carto"


def test_chart_specs_include_weather_gaps_and_config_annotations(data):
    history = dashboard.sensor_history(data, "S02", dashboard.replay_target(data, 785), full_day=True)
    charts = dashboard.history_charts(history, dashboard.injected_faults(data), "S02")
    air = charts["air"].to_dict()
    encoded = json.dumps(air)
    assert "weather_air_c" in encoded and "heat_score" not in encoded
    assert "segment" in encoded and '"rect"' in encoded
    assert "utcFormat" in encoded and "28800000" in encoded
    assert "time(toDate(datum.value))" in encoded
    assert '"value": "#cc6331"' in encoded
    assert len(charts) == 3
    # All three specs validate, including history with zero observations.
    for chart in charts.values():
        chart.to_dict(validate=True)


def test_dashboard_replay_selection_statuses_and_previous_tabs():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45).run()
    assert not at.exception
    tab = sensor_tab(at)
    assert tab.select_slider(key="sensors_time").value == 785
    assert tab.metric[2].value == "1"
    assert tab.get("deck_gl_json_chart")
    assert any("SIMULATED DATA" in item.value for item in tab.info)
    at.selectbox(key="sensors_selected").select("S02").run()
    at.select_slider(key="sensors_time").set_value(730).run()
    assert not at.exception
    assert any("S02 — Missing" in item.value for item in sensor_tab(at).markdown)
    assert sensor_tab(at).metric[4].value == "Unavailable"
    at.select_slider(key="sensors_time").set_value(750).run()
    assert not at.exception
    assert any("S02 — Active" in item.value for item in sensor_tab(at).markdown)
    at.checkbox(key="sensors_full_day").check().run()
    assert not at.exception
    assert at.select_slider(key="heat_hour").value == 14
    assert at.select_slider(key="route_hour").value == 14
    assert all(tab.get("deck_gl_json_chart") for tab in at.tabs)


def test_missing_stream_dashboard_does_not_break_previous_tabs(monkeypatch, inputs):
    (inputs / "sensors_stream.csv").rename(inputs / "original.csv")
    monkeypatch.setattr(dashboard, "DATA", inputs)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=45).run()
    assert not at.exception
    assert sensor_tab(at).metric[0].value == "0/8"
    assert sensor_tab(at).get("deck_gl_json_chart")
    assert any("stream unavailable" in message.value for message in sensor_tab(at).warning)
