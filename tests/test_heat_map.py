"""Heat Map tests use real committed data; synthetic inputs cover error branches."""

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import heat_map


@pytest.fixture(scope="module")
def links():
    return heat_map.load_heat_data(14)


def heat_tab(at):
    return next(tab for tab in at.tabs if tab.label == "Heat Map")


def test_real_network_matches_baseline_and_versioned_correction(links):
    payload = json.loads((ROOT / "data/links.geojson").read_text(encoding="utf-8"))
    props = {f["properties"]["link_id"]: f["properties"] for f in payload["features"]}
    assert len(links) == 1491
    assert links.crs.to_epsg() == 4326
    assert links.attrs["sensor_corrected"]
    assert links.heat_source.eq("corrected").all()
    assert links.sensor_source.eq("simulated").all()
    for link in links.itertuples():
        assert link.heat_model == props[link.link_id]["heat_h14"]
        assert link.shade == props[link.link_id]["shade_h14"]
    assert (links.heat != links.heat_model).any()


def test_colors_use_same_fixed_scale_for_every_hour():
    assert heat_map.heat_color(26) == list(heat_map.COLOR_STOPS[0][1])
    assert heat_map.heat_color(44) == list(heat_map.COLOR_STOPS[-1][1])
    assert heat_map.heat_color(20) == heat_map.heat_color(26)
    assert heat_map.heat_color(50) == heat_map.heat_color(44)
    colors = {}
    for hour in range(7, 20):
        frame = heat_map.load_heat_data(hour)
        for value in frame.heat.unique():
            color = heat_map.heat_color(value)
            assert all(0 <= c <= 255 for c in color)
            if value in colors:
                assert colors[value] == color
            colors[value] = color
    assert heat_map.heat_color(26.38) != heat_map.heat_color(43.08)
    html = heat_map.legend_html()
    assert "26°C" in html and "44°C" in html
    assert "linear-gradient" in html


@pytest.mark.parametrize("hour", [6, 20, 14.5, True])
def test_invalid_hour_is_rejected(hour):
    with pytest.raises(ValueError, match="Replay hour"):
        heat_map.load_heat_data(hour)


def test_summary_aggregation_is_explicit(links):
    summary = heat_map.heat_summary(links)
    assert summary["average"] == pytest.approx(links.heat.sum() / len(links))
    assert summary["hottest"] == links.heat.max()
    assert summary["hottest_id"] == links.loc[links.heat == links.heat.max()].link_id.min()
    assert summary["shade"] == pytest.approx((links.shade * links.length_m).sum() / links.length_m.sum())


def test_real_sensor_snapshots_do_not_use_future_or_other_day():
    original = pd.read_csv(ROOT / "data/sensors_stream.csv")
    for hour in (7, 12, 14, 19):
        snapshot = heat_map.sensor_snapshot(hour, "2026-09-06")
        assert len(snapshot) == 8
        for row in snapshot.itertuples():
            raw = original.loc[(original.sensor_id == row.sensor_id) & (original.timestamp == row.timestamp)]
            assert len(raw) == 1
            assert row.air_temp_c == raw.air_temp_c.iloc[0]
            assert pd.Timestamp(row.timestamp) <= pd.Timestamp(f"2026-09-06 {hour:02d}:00", tz="Asia/Kuala_Lumpur")
    at_noon = heat_map.sensor_snapshot(12, "2026-09-06").set_index("sensor_id")
    assert at_noon.loc["S02", "timestamp"].endswith("11:55:00+08:00")
    assert "stale" in at_noon.loc["S02", "status"]
    other_day = heat_map.sensor_snapshot(14, "2026-09-07")
    assert other_day.air_temp_c.isna().all()


def test_missing_stream_keeps_eight_locations(tmp_path):
    snapshot = heat_map.sensor_snapshot(14, "2026-09-06", stream_path=tmp_path / "missing.csv")
    assert len(snapshot) == 8
    assert not snapshot.attrs["stream_available"]
    assert snapshot.air_temp_c.isna().all()
    assert all(len(pos) == 2 for pos in snapshot.position)


def test_old_readings_withheld_and_bad_mapping_rejected(tmp_path):
    path = tmp_path / "stream.csv"
    readings = pd.read_csv(ROOT / "data/sensors_stream.csv")
    readings = readings.loc[readings.timestamp.str.contains("T07:00:")]
    readings.to_csv(path, index=False)
    assert heat_map.sensor_snapshot(14, "2026-09-06", stream_path=path).air_temp_c.isna().all()
    readings.loc[readings.index[0], "link_id"] = "unknown"
    readings.to_csv(path, index=False)
    with pytest.raises(ValueError, match="mismatched"):
        heat_map.sensor_snapshot(14, "2026-09-06", stream_path=path)


def test_real_paths_hover_and_overlay_attributes(links):
    rows = heat_map.link_paths(links)
    indexed = links.set_index("link_id")
    for row in rows:
        link = indexed.loc[row["link_id"]]
        assert row["path"] == [list(point) for point in link.geometry.coords]
        assert row["color"] == heat_map.heat_color(link.heat)
        assert "Shade:" in row["detail"] and "Covered:" in row["detail"]
        assert link.surface in row["detail"]
        for lon, lat in row["path"]:
            assert 101 < lon < 102 and 2 < lat < 4
    sensors = heat_map.sensor_snapshot(14, "2026-09-06")
    deck = json.loads(heat_map.build_heat_map(links, sensors, covered=True, canopy=True, shade=True).to_json())
    layers = {layer["id"]: layer for layer in deck["layers"]}
    assert len(layers["heat-network"]["data"]) == 1491
    assert {r["link_id"] for r in layers["heat-covered"]["data"]} == set(links.loc[links.covered].link_id)
    assert {r["link_id"] for r in layers["heat-canopy"]["data"]} == set(links.loc[links.canopy > 0].link_id)
    assert {r["link_id"] for r in layers["heat-shade"]["data"]} == set(links.loc[links.shade > 0].link_id)


def test_serialized_layers_preserve_purple_map_fix(links):
    sites = heat_map.sensor_snapshot(14, "2026-09-06")
    deck = json.loads(heat_map.build_heat_map(links, sites).to_json())
    assert deck["mapProvider"] == "carto"
    assert deck["mapStyle"] == heat_map.pdk.map_styles.CARTO_LIGHT
    layers = {layer["id"]: layer for layer in deck["layers"]}
    assert layers["heat-network"]["widthUnits"] == "pixels"
    assert layers["heat-network"]["widthMaxPixels"] <= 12
    assert layers["heat-sensors"]["radiusUnits"] == "pixels"
    assert layers["heat-sensors"]["radiusMaxPixels"] <= 14
    assert layers["heat-sensor-labels"]["sizeUnits"] == "pixels"
    assert layers["heat-sensor-labels"]["getTextAnchor"] == "middle"
    assert layers["heat-sensor-labels"]["getAlignmentBaseline"] == "center"
    assert len(layers["heat-sensors"]["data"]) == 8
    for dot, site in zip(layers["heat-sensors"]["data"], sites.itertuples()):
        assert dot["position"] == [site.lon, site.lat]
        assert "SIMULATED" in dot["detail"]
    assert 101 < deck["initialViewState"]["longitude"] < 102
    assert 2 < deck["initialViewState"]["latitude"] < 4


def test_baseline_fallback_and_unversioned_correction_rejection(monkeypatch, tmp_path):
    import shutil
    shutil.copy2(ROOT / "data/links.geojson", tmp_path / "links.geojson")
    monkeypatch.setattr(heat_map, "DATA", tmp_path)
    baseline = heat_map.load_heat_data(14)
    assert not baseline.attrs["sensor_corrected"]
    assert baseline.heat_source.eq("baseline").all()
    np.testing.assert_array_equal(baseline.heat, baseline.heat_model)
    payload = json.loads((tmp_path / "links.geojson").read_text(encoding="utf-8"))
    payload["features"][0]["properties"]["heat_corr_h14"] = 40.
    (tmp_path / "links.geojson").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="(?i)unversioned|embedded"):
        heat_map.load_heat_data(14)


def test_heat_tab_updates_hour_colors_and_leaves_route_state_unchanged():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert at.select_slider(key="heat_hour").value == 14
    tab = heat_tab(at)
    assert tab.get("deck_gl_json_chart")
    assert any("Sensor-corrected model heat using SIMULATED" in c.value for c in tab.caption)
    assert any("SIMULATED" in message.value for message in tab.info)
    expected = heat_map.heat_summary(heat_map.load_heat_data(14))
    assert tab.metric[0].value.startswith(f"{expected['average']:.2f}")
    afternoon = json.loads(tab.get("deck_gl_json_chart")[0].proto.json)
    afternoon_paths = next(layer["data"] for layer in afternoon["layers"] if layer["id"] == "heat-network")
    at.select_slider(key="heat_hour").set_value(7).run()
    assert not at.exception
    morning_data = heat_map.load_heat_data(7)
    assert heat_tab(at).metric[0].value.startswith(f"{morning_data.heat.mean():.2f}")
    morning = json.loads(heat_tab(at).get("deck_gl_json_chart")[0].proto.json)
    morning_paths = next(layer["data"] for layer in morning["layers"] if layer["id"] == "heat-network")
    assert len(morning_paths) == len(afternoon_paths) == 1491
    assert [p["color"] for p in morning_paths] == [heat_map.heat_color(value) for value in morning_data.heat]
    assert [p["color"] for p in afternoon_paths] != [p["color"] for p in morning_paths]
    assert at.select_slider(key="route_hour").value == 14
    at.select_slider(key="heat_hour").set_value(19).run()
    assert not at.exception
    at.checkbox(key="heat_covered").check().run()
    at.checkbox(key="heat_canopy").check().run()
    at.checkbox(key="heat_shade").check().run()
    assert not at.exception
    with_overlays = json.loads(heat_tab(at).get("deck_gl_json_chart")[0].proto.json)
    assert {"heat-covered", "heat-canopy", "heat-shade"}.issubset({layer["id"] for layer in with_overlays["layers"]})


def test_missing_heat_does_not_break_cool_route(monkeypatch):
    monkeypatch.setattr(heat_map, "heat_at", lambda h, **kwargs: (_ for _ in ()).throw(FileNotFoundError("Missing model")))
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not at.exception
    assert any("Heat network unavailable" in message.value for message in at.error)
    assert next(t for t in at.tabs if t.label == "Cool Route").get("deck_gl_json_chart")
