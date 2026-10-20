"""Synthetic-network tests: do not require Person 1's real township data."""
from pathlib import Path
import sys

import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import engine


@pytest.fixture
def demo(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    A, B, C = (101.0, 3.0), (101.001, 3.0), (101.002, 3.0)
    D, E = (101.0, 3.001), (101.001, 3.001)
    edges = [
        ("hot1", A, B, 100, 40, 0),
        ("hot2", B, C, 100, 40, 0),
        ("cool1", A, D, 80, 30, 0.9),
        ("cool2", D, E, 80, 30, 0.9),
        ("cool3", E, C, 80, 30, 0.9),
    ]
    rows = []
    for lid, u, v, length, heat, shade in edges:
        p = dict(link_id=lid, length_m=length, covered=False, canopy=shade,
                 albedo=0.25, surface="asphalt")
        for h in engine.HOURS:
            p[f"heat_h{h:02d}"] = heat
            p[f"shade_h{h:02d}"] = shade
        p["geometry"] = LineString([u, v])
        rows.append(p)
    gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:4326").to_file(tmp_path / "links.geojson", driver="GeoJSON")
    gpd.GeoDataFrame([
        {"place_id": "home-1", "name": "Homes", "kind": "home", "households": 10, "geometry": Point(A)},
        {"place_id": "lrt-1", "name": "LRT", "kind": "transit", "households": 0, "geometry": Point(C)}
    ], crs="EPSG:4326").to_file(tmp_path / "places.geojson", driver="GeoJSON")
    pd.DataFrame([{"hour": h, "shortwave_radiation": 800 if h < 18 else 200}
                  for h in engine.HOURS]).to_csv(tmp_path / "weather.csv", index=False)
    (tmp_path / "interventions.csv").write_text((Path(__file__).resolve().parents[1] / "data" / "interventions.csv").read_text())
    return tmp_path


def test_heat_at_matches_shared_contract(demo):
    result = engine.heat_at(13)
    assert isinstance(result, gpd.GeoDataFrame)
    assert set(["link_id", "length_m", "heat_score", "shade"]).issubset(result)
    assert result.loc[result.link_id == "hot1", "heat_score"].iloc[0] == 40


def test_shortest_and_coolest_route(demo):
    a = engine.route("home-1", "lrt-1", 13, "shortest")
    b = engine.route("home-1", "lrt-1", 13, "coolest")
    assert a["distance_m"] == 200
    assert a["link_ids"] == ["hot1", "hot2"]
    assert b["distance_m"] == 240
    assert b["link_ids"] == ["cool1", "cool2", "cool3"]
    assert b["extra_distance_pct"] == 20
    assert b["heat_exposure"] == 0
    assert b["heat_avoided"] > 0
    assert b["minutes_in_sun"] < a["minutes_in_sun"]
    assert b["geometry"]["type"] == "FeatureCollection"


def test_no_route_longer_than_25pct(demo):
    links = gpd.read_file(demo / "links.geojson")
    links.loc[links.link_id.str.startswith("cool"), "length_m"] = 101  # 303m vs 200m
    links.to_file(demo / "links.geojson", driver="GeoJSON")
    out = engine.route("home-1", "lrt-1", 13, "coolest")
    assert out["distance_m"] == 200
    assert out["heat_avoided"] == 0


def test_balanced_route_keeps_within_10pct(demo):
    # The cool path is 20% longer: fine for coolest (25%), too long for balanced (10%)
    out = engine.route("home-1", "lrt-1", 13, "balanced")
    assert out["mode"] == "balanced"
    assert out["link_ids"] == ["hot1", "hot2"]
    assert out["extra_distance_pct"] == 0


def _mark_unsafe(demo, link_ids):
    links = gpd.read_file(demo / "links.geojson")
    links["unsafe"] = links.link_id.isin(link_ids)
    links.to_file(demo / "links.geojson", driver="GeoJSON")


def test_unsafe_links_are_skipped_by_every_mode(demo):
    _mark_unsafe(demo, ["hot1"])
    for mode in engine.ROUTE_MODES:
        out = engine.route("home-1", "lrt-1", 13, mode)
        assert "hot1" not in out["link_ids"]
        assert out["uses_unsafe"] is False
    assert engine.walking_demand().set_index("link_id").loc["hot1", "flow_day"] == 0


def test_unsafe_links_used_at_10x_and_flagged_when_cut_off(demo):
    _mark_unsafe(demo, ["hot1", "cool1"])  # both ways out of home-1
    out = engine.route("home-1", "lrt-1", 13, "shortest")
    assert out["uses_unsafe"] is True
    assert out["warning"]
    # At 10x, the shorter unsafe stretch wins: cool1 (80 m) costs 800 + 160 < hot1 (100 m) 1000 + 100
    assert out["link_ids"] == ["cool1", "cool2", "cool3"]


def test_demand_only_assigns_shortest_path(demo):
    flows = engine.walking_demand().set_index("link_id")
    assert flows.loc["hot1", "flow_day"] == pytest.approx(9, abs=0.001)
    assert flows.loc["hot2", "flow_day"] == pytest.approx(9, abs=0.001)
    assert flows.loc["cool1", "flow_day"] == 0


def test_fix_is_positive_non_mutating_and_has_before_after(demo):
    before = (demo / "links.geojson").read_bytes()
    result = engine.apply_fix("hot1", "shade_trees")
    assert result["cost_rm"] == 16000
    assert result["heat_drop"] > 0
    assert result["person_min_saved_day"] > 0
    assert result["area_after"] < result["area_before"]
    assert result["before"]["heat_by_hour"]["h13"] > result["after"]["heat_by_hour"]["h13"]
    assert (demo / "links.geojson").read_bytes() == before


def test_planner_budget_and_no_double_fixes(demo):
    # The budget covers building cost only; upkeep is reported alongside
    picks = engine.priorities(50000)
    assert not picks.empty
    assert picks["cost_rm"].sum() <= 50000
    assert picks.attrs["upkeep_rm_per_year"] == pytest.approx(picks["upkeep_rm_per_year"].sum())
    assert picks["link_id"].is_unique
    assert list(picks.columns) == engine.PRIORITY_COLUMNS
    assert (picks["person_min_saved_day"] > 0).all()
    assert {"weeks_to_effect", "quick_win"}.issubset(picks.columns)
    assert picks["quick_win"].isin([True, False]).all()
    assert engine.priorities(0).empty
    out = demo / "priorities.csv"
    engine.save_priorities(50000, out)
    assert out.is_file()
    assert set(engine.PRIORITY_COLUMNS).issubset(pd.read_csv(out).columns)


def _option(link_id, fix, cost, benefit):
    return {"link_id": link_id, "fix": fix, "cost_rm": cost, "person_min_saved_day": benefit,
            "benefit_per_rm": benefit / cost}


def test_best_mix_beats_greedy_and_keeps_one_fix_per_link():
    # Greedy by benefit per RM takes A (best ratio) and can't fit more: 70.
    # The exact search takes B + C: 110, exactly on budget.
    options = [_option("A", "x", 60, 70), _option("B", "x", 50, 55), _option("C", "x", 50, 55)]
    picked = engine._best_mix(options, 100)
    assert sorted(o["link_id"] for o in picked) == ["B", "C"]
    # Two fixes on one link: only one may be chosen, even when both fit
    options = [_option("X", "cheap", 50, 60), _option("X", "dear", 100, 100)]
    picked = engine._best_mix(options, 150)
    assert [(o["link_id"], o["fix"]) for o in picked] == [("X", "dear")]
    assert engine._best_mix(options, 0) == []


def test_effect_share_over_horizon():
    assert engine.effect_share(260, 260) == pytest.approx(0.5)            # tree, 5-year horizon
    assert engine.effect_share(4, 260) == pytest.approx(1 - 4 / 520)      # sail, nearly full
    assert engine.effect_share(260, 52) == pytest.approx(0.1)             # tree, next 12 months
    assert engine.effect_share(0, 52) == 1.0


def test_planner_counts_time_to_take_effect_and_upkeep(demo):
    for years in (1, 10):
        picks = engine.priorities(50000, horizon_years=years)
        assert not picks.empty
        assert (picks["benefit_over_horizon"] <= picks["person_min_saved_day"] + 1e-9).all()
        assert (picks["cost_10y_rm"] == (picks["cost_rm"] + 10 * picks["upkeep_rm_per_year"]).round(2)).all()
        assert picks["cost_rm"].sum() <= 50000
        assert picks.attrs["horizon_years"] == years


def test_upkeep_scale_for_sensitivity_checks(demo):
    base = engine.fix_options(10).set_index(["link_id", "fix"])
    double = engine.fix_options(10, upkeep_scale=2).set_index(["link_id", "fix"])
    assert (double["upkeep_rm_per_year"] == (2 * base["upkeep_rm_per_year"]).round(2)).all()
    assert (double["value_10y"] < base["value_10y"]).all()
    assert (double["benefit_over_horizon"] == base["benefit_over_horizon"]).all()


def test_sensor_stub_and_invalid_inputs(demo):
    assert list(engine.latest_sensors().columns) == engine.SENSOR_COLUMNS
    with pytest.raises(ValueError):
        engine.route("home-1", "lrt-1", 25, "coolest")
    with pytest.raises(ValueError):
        engine.route("home-1", "unknown", 13, "coolest")
    with pytest.raises(ValueError):
        engine.apply_fix("hot1", "not_a_fix")
    with pytest.raises(ValueError):
        engine.priorities(-1)


def test_route_summary(demo):
    values = engine.route_summary()
    assert values["evaluated_home_destination_pairs"] == 1
    assert values["trips_with_cooler_route_pct"] == 100
    assert values["mean_heat_avoided_per_improved_trip"] > 0


def test_save_flow_to_links_preserves_heat_and_geometry(demo):
    import json
    original = json.loads((demo / "links.geojson").read_text())
    out = engine.save_flow_to_links()
    assert out == demo / "links.geojson"
    modified = json.loads(out.read_text())
    assert len(original["features"]) == len(modified["features"])
    for left, right in zip(original["features"], modified["features"]):
        assert left["geometry"] == right["geometry"]
        assert left["properties"]["heat_h13"] == right["properties"]["heat_h13"]
        assert "flow_day" in right["properties"]
