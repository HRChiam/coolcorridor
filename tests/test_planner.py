"""Real engine integration, allocation checks, read-only previews and map regression."""

import copy
import hashlib
import json
from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
import pytest
from streamlit.testing.v1 import AppTest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine
import planner


@pytest.fixture(scope="module")
def inputs():
    return planner.load_planning_data()


@pytest.fixture(scope="module")
def allocation(inputs):
    links, fixes = inputs
    return planner.fetch_recommendations(100000, links, fixes)


def protected_hashes():
    paths = [ROOT / "engine.py"] + list((ROOT / "heat_model").glob("*.py")) + list((ROOT / "data").glob("*"))
    return {str(p): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths if p.is_file()}


def test_real_data_contract(inputs):
    links, fixes = inputs
    assert len(links) == 1491 and links.crs.to_epsg() == 4326
    assert set(fixes.fix) == set(planner.FIX_LABELS)
    assert all(f"heat_h{hour:02d}" in links for hour in engine.HOURS)
    assert not any(col.startswith("heat_corr") for col in links)


@pytest.mark.parametrize("budget", [-1, float("nan"), float("inf"), True, "10000", None])
def test_invalid_budget(budget):
    with pytest.raises((ValueError, TypeError)):
        planner.validate_budget(budget)


@pytest.mark.parametrize("budget", [0, 10000, 100000])
def test_real_budget_outputs(budget, inputs):
    links, fixes = inputs
    table, summary = planner.fetch_recommendations(budget, links, fixes)
    assert summary["spent"] == pytest.approx(table.cost_rm.sum())
    assert summary["remaining"] == pytest.approx(budget - summary["spent"])
    assert summary["spent"] <= budget
    assert not table.link_id.duplicated().any()
    assert table["rank"].tolist() == list(range(1, len(table) + 1))
    if budget == 0:
        assert table.empty and summary["benefit"] == 0
    elif budget == 100000:
        assert len(table) == 15
        assert summary["spent"] == 99920
        assert summary["remaining"] == 80
        assert summary["benefit"] == pytest.approx(5587.79224)
        assert set(table.fix) == {"shade_trees"}
        assert table.attrs["heat_source"] == "corrected"
        assert table.attrs["sensor_source"] == "simulated"


def test_display_retains_ranks_units_and_selected_status(allocation):
    table, _ = allocation
    display = planner.recommendation_table(table)
    assert display.Rank.tolist() == table["rank"].tolist()
    assert display["Cost (RM)"].tolist() == table.cost_rm.tolist()
    assert all(display.Selection == "Selected within budget (proposal)")
    assert "13:00 heat-index drop (°C)" in display
    assert f"Saving ({planner.BENEFIT_UNIT})" in display


@pytest.mark.parametrize("problem", ["missing", "overspend", "duplicate", "unknown_fix", "unknown_link", "nan", "rank", "attrs"])
def test_malformed_recommendations_rejected(problem, allocation, inputs):
    links, fixes = inputs
    table = allocation[0].copy(deep=True)
    if problem == "missing":
        table = table.drop(columns="cost_rm")
    elif problem == "overspend":
        table.loc[0, "cost_rm"] = 100001
    elif problem == "duplicate":
        table.loc[1, "link_id"] = table.loc[0, "link_id"]
    elif problem == "unknown_fix":
        table.loc[0, "fix"] = "invented"
    elif problem == "unknown_link":
        table.loc[0, "link_id"] = "missing"
    elif problem == "nan":
        table.loc[0, "person_min_saved_day"] = float("nan")
    elif problem == "rank":
        table.loc[0, "rank"] = 10
    else:
        table.attrs["spent_rm"] = 1
    with pytest.raises(ValueError):
        planner.validate_recommendations(table, 100000, links, fixes)


def test_missing_engine_result(inputs):
    with pytest.raises(ValueError, match="incomplete"):
        planner.validate_recommendations(None, 100000, *inputs)


def test_actual_preview_is_isolated_and_nonmutating(inputs, allocation):
    before = protected_hashes()
    data_dir = engine.DATA_DIR
    baseline = allocation[0].copy(deep=True)
    result = planner.fetch_preview("L0027", "shade_trees", *inputs)
    assert result["cost_rm"] == 4896
    assert result["heat_drop"] == pytest.approx(3.4157)
    assert result["person_min_saved_day"] == pytest.approx(364.838)
    hours = planner.preview_table(result)
    assert len(hours) == 13
    assert hours.loc[6, "Before heat index (°C)"] - hours.loc[6, "After heat index (°C)"] == pytest.approx(result["heat_drop"], abs=.0001)
    assert (hours["After shade (%)"] >= hours["Before shade (%)"]).all()
    assert result["area_before"] - result["area_after"] == pytest.approx(result["person_min_saved_day"], abs=.001)
    result["before"]["albedo"] = .99  # caller must not poison cached outputs
    assert planner.fetch_preview("L0027", "shade_trees", *inputs)["before"]["albedo"] != .99
    pd.testing.assert_frame_equal(planner.fetch_recommendations(100000, *inputs)[0], baseline)
    # Re-run the real engine, bypassing the presentation cache, to verify isolation.
    pd.testing.assert_frame_equal(engine.priorities(100000), baseline)
    assert engine.DATA_DIR == data_dir and protected_hashes() == before


@pytest.mark.parametrize("link_id,fix", [("missing", "shade_trees"), ("L0027", "unsupported")])
def test_unsupported_preview_selection(link_id, fix, inputs):
    with pytest.raises(ValueError, match="supported"):
        planner.fetch_preview(link_id, fix, *inputs)


def test_missing_preview_fields_and_results(monkeypatch, inputs):
    monkeypatch.setattr(planner, "_cached_preview", lambda *args: None)
    with pytest.raises(ValueError, match="missing"):
        planner.fetch_preview("L0027", "shade_trees", *inputs)
    with pytest.raises(KeyError):
        planner.preview_table({"before": {}, "after": {}})


def test_real_map_geometries_serialization_and_colors(inputs, allocation):
    links, _ = inputs
    base, selected, skipped = planner.planning_paths(links, allocation[0])
    assert not skipped and len(base) == 1491 and len(selected) == 15
    deck = json.loads(planner.build_planner_map(base, selected).to_json())
    assert deck["mapProvider"] == "carto" and deck["mapStyle"] == planner.pdk.map_styles.CARTO_LIGHT
    assert set(tuple(c) for c in planner.FIX_COLORS.values()).__len__() == 4
    for layer in deck["layers"]:
        assert layer["widthUnits"] == "pixels" and layer["widthMaxPixels"] <= 10
        assert "coordinateSystem" not in layer
        for item in layer["data"]:
            for lon, lat in item["path"]:
                assert 101 < lon < 102 and 2 < lat < 4
    for row in selected:
        assert row["color"] == planner.FIX_COLORS["shade_trees"]
        assert "Selected within budget" in row["detail"] and planner.BENEFIT_UNIT in row["detail"]
    assert deck["layers"][0]["getWidth"] < deck["layers"][1]["getWidth"]


def test_missing_map_geometry_is_reported(inputs, allocation):
    links = inputs[0].copy()
    links.loc[0, "geometry"] = None
    base, _, skipped = planner.planning_paths(links, allocation[0])
    assert skipped == [links.link_id.iloc[0]] and len(base) == len(links) - 1
    links["geometry"] = None
    with pytest.raises(ValueError, match="No valid"):
        planner.planning_paths(links, allocation[0])


def test_projected_input_transformed_and_incomplete_fields(tmp_path, inputs):
    links, fixes = inputs
    fixes.to_csv(tmp_path / "interventions.csv", index=False)
    links.to_crs(3857).to_file(tmp_path / "links.geojson", driver="GeoJSON")
    transformed, _ = planner.load_planning_data(tmp_path)
    assert transformed.crs.to_epsg() == 4326
    assert transformed.geometry.iloc[0].equals_exact(links.geometry.iloc[0], tolerance=1e-8)
    links.drop(columns="heat_h13").to_file(tmp_path / "links.geojson", driver="GeoJSON")
    with pytest.raises(ValueError, match="missing fields"):
        planner.load_planning_data(tmp_path)


def test_app_budget_preview_and_previous_tabs():
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert [tab.label for tab in at.tabs] == ["Cool Route", "Heat Map", "Sensors", "Planner"]
    tab = at.tabs[3]
    assert tab.metric[0].value == "RM 99,920.00"
    assert tab.metric[1].value == "RM 80.00"
    at.button(key="planner_preview_button").click().run()
    assert not at.exception
    assert at.tabs[3].metric[4].value == "RM 4,896.00"
    at.number_input(key="planner_budget").set_value(0).run()
    assert not at.exception
    assert at.tabs[3].metric[0].value == "RM 0.00"
    assert any("No positive-benefit" in message.value for message in at.tabs[3].info)
    assert all(tab.get("deck_gl_json_chart") for tab in at.tabs)
    assert at.select_slider(key="route_hour").value == 14
    assert at.select_slider(key="heat_hour").value == 14
    assert at.select_slider(key="sensors_time").value == 785


def test_engine_failure_is_local_to_planner(monkeypatch):
    def fail(*args):
        raise ValueError("Shared planning inputs unavailable")
    monkeypatch.setattr(planner, "fetch_recommendations", fail)
    at = AppTest.from_file(str(ROOT / "app.py"), default_timeout=60).run()
    assert not at.exception
    assert "Shared planning inputs unavailable" in at.tabs[3].error[0].value
    assert all(tab.get("deck_gl_json_chart") for tab in at.tabs[:3])
