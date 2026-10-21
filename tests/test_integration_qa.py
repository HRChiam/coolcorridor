"""Phase 7 cross-team contracts and Person 3 fail-closed regression checks."""

import json
from pathlib import Path
import shutil
import sys

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import app_data
import engine
import heat_map
from heat_model import heat
import planner
import sensors_dashboard as sensors
from simulate_sensors import generate_readings, load_config


@pytest.fixture
def bundle(tmp_path):
    for name in ("links.geojson", "places.geojson", "weather.csv", "interventions.csv",
                 "sensor_links.csv", "sensors_stream.csv"):
        shutil.copy2(ROOT / "data" / name, tmp_path / name)
    return tmp_path


def test_all_hour_heat_interfaces_match_effective_heat_and_design_weather():
    weather = app_data.design_day(ROOT / "data/weather.csv")
    for hour in engine.HOURS:
        display = heat_map.load_heat_data(hour).set_index("link_id")
        routed = engine.heat_at(hour).set_index("link_id").loc[display.index]
        np.testing.assert_array_equal(display.heat, routed.heat_score)
        np.testing.assert_array_equal(display.shade, routed.shade)
        w = weather.loc[hour]
        expected = heat.heat_score(w.air_temp_c, display.shade, w.sw_wm2, display.albedo, w.wind_ms)
        np.testing.assert_allclose(display.heat_model, expected, rtol=0, atol=.00501)
        assert display.attrs["sensor_corrected"]
        assert routed.heat_source.eq("corrected").all()
        assert routed.sensor_source.eq("simulated").all()


@pytest.mark.parametrize("hour", [7, 14])
def test_real_route_exposure_reconstructs_from_same_hour_heat_map(hour):
    links = heat_map.load_heat_data(hour).set_index("link_id")
    for mode in ("shortest", "coolest"):
        route = engine.route("P043", "P066", hour, mode=mode)
        walked = links.loc[route["link_ids"]]
        minutes = walked.length_m / engine.WALKING_METRES_PER_MIN
        assert route["heat_exposure"] == pytest.approx((minutes * (walked.heat - engine.COMFORT_C).clip(lower=0)).sum(), abs=.00051)
        assert route["minutes_in_sun"] == pytest.approx((minutes * (1 - walked.shade)).sum(), abs=.00051)
        assert route["distance_m"] == pytest.approx(walked.length_m.sum(), abs=.0051)


def test_engine_uses_authoritative_station_node():
    links = engine._read_links()
    places = engine._read_places()
    graph = engine._build_graph(links, 7)
    station = places.loc[places.place_id == "P066"].iloc[0]
    expected = f"node:{int(station.node_id)}"
    assert engine._resolve_node(graph, places, "P066") == expected


def test_unversioned_corrected_columns_are_rejected_by_both_readers(monkeypatch, bundle):
    payload = json.loads((bundle / "links.geojson").read_text(encoding="utf-8"))
    for feature in payload["features"]:
        feature["properties"]["heat_corr_h14"] = feature["properties"]["heat_h14"] + .5
    (bundle / "links.geojson").write_text(json.dumps(payload), encoding="utf-8")
    monkeypatch.setattr(engine, "DATA_DIR", bundle)
    for reader in (lambda: heat.heat_at(14, data_dir=bundle), lambda: engine.heat_at(14)):
        with pytest.raises(ValueError, match="(?i)unversioned|embedded"):
            reader()


def test_design_radiation_is_independent_of_extra_forecast_rows(bundle, monkeypatch):
    monkeypatch.setattr(engine, "DATA_DIR", bundle)
    weather = pd.read_csv(bundle / "weather.csv")
    design = app_data.design_day(bundle / "weather.csv")
    expected = engine._weather_radiation()
    assert expected == design.sw_wm2.to_dict()
    before = engine.apply_fix("L0027", "shade_trees")
    weather.loc[weather.day == "forecast", ["air_temp_c", "sw_wm2"]] = [-50, 99999]
    weather = pd.concat([weather, weather.loc[weather.day == "forecast"]], ignore_index=True)
    weather.to_csv(bundle / "weather.csv", index=False)
    pd.testing.assert_frame_equal(app_data.design_day(bundle / "weather.csv"), design)
    assert engine._weather_radiation() == expected
    assert engine.apply_fix("L0027", "shade_trees") == before


@pytest.mark.parametrize("field", ["shade_h14", "canopy", "albedo", "surface", "geometry", "baseline_with_correction"])
def test_heat_cache_updates_or_rejects_changed_nonheat_inputs(monkeypatch, bundle, field):
    monkeypatch.setattr(heat_map, "DATA", bundle)
    cached = heat_map.load_heat_data(14)
    payload = json.loads((bundle / "links.geojson").read_text(encoding="utf-8"))
    feature = payload["features"][0]
    if field in ("shade_h14", "canopy", "albedo"):
        feature["properties"][field] = .123456
    elif field == "surface":
        feature["properties"][field] = "changed-for-test"
    elif field == "geometry":
        feature["geometry"]["coordinates"][0][0] += .00001
    else:
        feature["properties"]["heat_corr_h14"] = feature["properties"]["heat_h14"]
        feature["properties"]["heat_h14"] += 1
    (bundle / "links.geojson").write_text(json.dumps(payload), encoding="utf-8")
    if field in ("shade_h14", "albedo", "baseline_with_correction"):
        with pytest.raises(ValueError):
            heat_map.load_heat_data(14)
    else:
        fresh = heat_map.load_heat_data(14)
        if field == "geometry":
            assert not fresh.geometry.iloc[0].equals(cached.geometry.iloc[0])
        else:
            assert fresh[field].iloc[0] == feature["properties"][field]
            assert fresh[field].iloc[0] != cached[field].iloc[0]


def test_changed_design_weather_rejects_old_heat(monkeypatch, bundle):
    weather = pd.read_csv(bundle / "weather.csv")
    weather.loc[weather.day == "design", "air_temp_c"] += 1
    weather.to_csv(bundle / "weather.csv", index=False)
    monkeypatch.setattr(heat_map, "DATA", bundle)
    with pytest.raises(ValueError, match="Heat and design weather disagree"):
        heat_map.load_heat_data(14)


@pytest.mark.parametrize("problem", ["duplicate_hour", "no_design", "nan", "multiple_dates", "invalid_date", "nat_date"])
def test_bad_design_weather_rejected(bundle, problem):
    weather = pd.read_csv(bundle / "weather.csv")
    if problem == "duplicate_hour":
        weather.loc[1, "hour"] = 7
    elif problem == "no_design":
        weather = weather.loc[weather.day == "forecast"]
    elif problem == "nan":
        weather.loc[0, "air_temp_c"] = float("nan")
    elif problem in ("invalid_date", "nat_date"):
        weather.loc[weather.day == "design", "date"] = "not-a-date" if problem == "invalid_date" else "NaT"
    else:
        weather.loc[0, "date"] = "2026-09-07"
    weather.to_csv(bundle / "weather.csv", index=False)
    with pytest.raises(ValueError):
        app_data.design_day(bundle / "weather.csv")


def test_seed_and_faults_match_csv_without_writing():
    config = load_config()
    actual = generate_readings(config)
    pd.testing.assert_frame_equal(actual.round(3), pd.read_csv(ROOT / "data/sensors_stream.csv").round(3))
    clean = generate_readings(config, faults=False)
    fault = actual.set_index(["sensor_id", "timestamp"])
    baseline = clean.set_index(["sensor_id", "timestamp"])
    key = ("S01", "2026-09-06T13:05:00+08:00")
    assert fault.loc[key, "air_temp_c"] - baseline.loc[key, "air_temp_c"] == pytest.approx(8)
    assert fault.loc[key, "surface_temp_c"] - baseline.loc[key, "surface_temp_c"] == pytest.approx(8)
    missing = baseline.index.difference(fault.index)
    assert len(missing) == 6 and set(missing.get_level_values(0)) == {"S02"}
    assert max(missing.get_level_values(1)) == "2026-09-06T12:25:00+08:00"


def test_invalid_fault_config_is_nonfatal_and_detector_independent(bundle):
    path = bundle / "bad_config.json"
    path.write_text(json.dumps({"spike_time": "25:00"}), encoding="utf-8")
    data = sensors.load_sensor_data(bundle, path)
    assert data.config is None and data.notices
    assert sensors.injected_faults(data).empty
    assert len(sensors.detected_events(data, sensors.replay_target(data, 785))) == 1


@pytest.mark.parametrize("problem", ["no_timezone", "duplicate", "off_schedule"])
def test_heat_map_rejects_invalid_sensor_timestamps(bundle, problem):
    readings = pd.read_csv(bundle / "sensors_stream.csv")
    if problem == "no_timezone":
        readings.loc[0, "timestamp"] = "2026-09-06T07:00:00"
    elif problem == "duplicate":
        readings = pd.concat([readings, readings.iloc[[0]]], ignore_index=True)
    else:
        readings.loc[0, "timestamp"] = "2026-09-06T07:01:00+08:00"
    readings.to_csv(bundle / "sensors_stream.csv", index=False)
    with pytest.raises(ValueError, match="timestamps"):
        heat_map.sensor_snapshot(14, "2026-09-06", stream_path=bundle / "sensors_stream.csv")


def test_planner_cache_invalidates_when_shared_input_changes(monkeypatch, bundle):
    monkeypatch.setattr(engine, "DATA_DIR", bundle)
    calls = []
    def counted(budget):
        calls.append(budget)
        return pd.DataFrame({"call": [len(calls)]})
    monkeypatch.setattr(engine, "priorities", counted)
    first = planner._cached_priorities(0, planner.input_signature())
    assert planner._cached_priorities(0, planner.input_signature()).equals(first)
    assert len(calls) == 1
    path = bundle / "weather.csv"
    path.write_bytes(path.read_bytes() + b"\n")
    assert planner._cached_priorities(0, planner.input_signature()).iloc[0, 0] == 2
    assert len(calls) == 2


def test_sensors_read_changed_csv_without_stale_cache(bundle):
    first = sensors.load_sensor_data(bundle)
    readings = pd.read_csv(bundle / "sensors_stream.csv")
    readings.loc[0, "air_temp_c"] += .1
    readings.to_csv(bundle / "sensors_stream.csv", index=False)
    second = sensors.load_sensor_data(bundle)
    assert second.readings.iloc[0].air_temp_c == pytest.approx(first.readings.iloc[0].air_temp_c + .1)


def test_app_rejects_mixed_engine_directory(monkeypatch, bundle):
    monkeypatch.setattr(engine, "DATA_DIR", bundle)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception and len(at.tabs) == 4
    assert "Engine data override differs" in at.error[0].value
    assert not at.tabs[0].get("deck_gl_json_chart") and not at.tabs[3].get("deck_gl_json_chart")
    assert at.tabs[1].get("deck_gl_json_chart") and at.tabs[2].get("deck_gl_json_chart")


def test_planner_rejects_mismatched_baseline_before_calling_engine(monkeypatch, bundle):
    links, fixes = planner.load_planning_data(bundle)
    weather = pd.read_csv(bundle / "weather.csv")
    weather.loc[weather.day == "design", "air_temp_c"] += 1
    weather.to_csv(bundle / "weather.csv", index=False)
    monkeypatch.setattr(engine, "DATA_DIR", bundle)
    def unexpected(*args):
        pytest.fail("Engine must not run against mismatched heat/weather inputs")
    monkeypatch.setattr(engine, "priorities", unexpected)
    monkeypatch.setattr(engine, "apply_fix", unexpected)
    with pytest.raises(ValueError, match="Heat and design weather disagree"):
        planner.fetch_recommendations(100000, links, fixes)
    with pytest.raises(ValueError, match="Heat and design weather disagree"):
        planner.fetch_preview("L0027", "shade_trees", links, fixes)


def test_readonly_app_modules_have_no_local_personal_paths_or_dependency_on_debug_cache():
    for name in ("app.py", "app_data.py", "cool_route.py", "heat_map.py", "planner.py", "sensors_dashboard.py", "simulate_sensors.py"):
        source = (ROOT / name).read_text(encoding="utf-8")
        assert "C:\\Users\\" not in source and "E:\\UTM" not in source
        assert "map_browser_check" not in source and "planner_browser_check" not in source
