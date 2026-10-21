"""Authoritative junctions, scalar planning equivalence and cache correctness."""

import hashlib
import os
from pathlib import Path
import shutil
import sys

import geopandas as gpd
import numpy as np
import pandas as pd
import pytest
from shapely.geometry import LineString, Point

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine


@pytest.fixture
def repaired_network(tmp_path, monkeypatch):
    """Reversed polylines and deliberately misleading place display locations."""
    a, b, c = (101., 3.), (101.001, 3.), (101.002, 3.)
    records = []
    for link_id, u, v, points in (("ab", 1, 2, [b, a]), ("bc", 2, 3, [c, b])):
        row = {"link_id": link_id, "u": u, "v": v, "length_m": 100.,
               "covered": False, "canopy": .5, "albedo": .25,
               "geometry": LineString(points)}
        for hour in engine.HOURS:
            row[f"heat_h{hour:02d}"] = 40.
            row[f"shade_h{hour:02d}"] = .5
        records.append(row)
    gpd.GeoDataFrame(records, crs=4326).to_file(tmp_path / "links.geojson", driver="GeoJSON")
    # Both display points coincide; only the authoritative IDs identify the trip.
    gpd.GeoDataFrame([
        {"place_id": "home", "node_id": 1, "kind": "home", "households": 10,
         "geometry": Point(b)},
        {"place_id": "station", "node_id": 3, "kind": "transit", "households": 0,
         "geometry": Point(b)},
    ], crs=4326).to_file(tmp_path / "places.geojson", driver="GeoJSON")
    pd.DataFrame([{"day": "design", "date": "2026-09-06", "hour": h,
                   "air_temp_c": 30., "rh_pct": 70., "wind_ms": 1., "sw_wm2": 800.}
                  for h in engine.HOURS]).to_csv(tmp_path / "weather.csv", index=False)
    shutil.copy2(ROOT / "data/interventions.csv", tmp_path / "interventions.csv")
    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    engine.clear_caches()
    yield tmp_path
    engine.clear_caches()


def test_reversed_geometry_resolves_real_endpoints_without_rewriting(repaired_network):
    links = engine._read_links()
    original = links.geometry.to_wkb().tolist()
    graph = engine._build_graph(links, 7)
    assert graph.nodes["node:1"]["xy"] == (101., 3.)
    assert graph.nodes["node:2"]["xy"] == (101.001, 3.)
    assert graph.nodes["node:3"]["xy"] == (101.002, 3.)
    assert not graph.graph["unresolved_coordinate_nodes"]
    assert links.geometry.to_wkb().tolist() == original
    assert set(key for _, _, key in graph.edges(keys=True)) == {"ab", "bc"}


def test_all_66_real_exported_node_ids_and_station_are_authoritative():
    links = engine._read_links()
    places = engine._read_places()
    graph = engine._build_graph(links, 7)
    assert len(places) == 66
    assert not graph.graph["unresolved_coordinate_nodes"]
    for place in places.itertuples():
        assert engine._resolve_node(graph, places, place.place_id) == f"node:{int(place.node_id)}"
    assert engine._resolve_node(graph, places, "P066") == "node:8141631184"
    # Every assigned junction is an endpoint of each incident geometry.
    for u, v, edge in graph.edges(data=True):
        endpoints = set(engine._endpoints(edge["geometry"]))
        assert graph.nodes[u]["xy"] in endpoints
        assert graph.nodes[v]["xy"] in endpoints


def test_route_demand_and_summary_share_authoritative_resolution(repaired_network, monkeypatch):
    def no_snapping(*args):
        pytest.fail("Authoritative IDs must not call spatial snapping")
    monkeypatch.setattr(engine, "_snap", no_snapping)
    result = engine.route("home", "station", 14, "shortest")
    assert result["link_ids"] == ["ab", "bc"] and result["distance_m"] == 200
    flows = engine.walking_demand()
    np.testing.assert_allclose(flows.flow_day, 9., atol=1e-5)
    assert engine.route_summary(hour=14)["evaluated_home_destination_pairs"] == 1


@pytest.mark.parametrize("node_id", [999, "bogus", 1.5, True])
def test_invalid_supplied_node_id_is_rejected_not_snapped(repaired_network, node_id):
    graph = engine._build_graph(engine._read_links(), 7)
    places = engine._read_places()
    places["node_id"] = places.node_id.astype(object)
    places.loc[places.place_id == "home", "node_id"] = node_id
    with pytest.raises(ValueError, match="node|Node"):
        engine._resolve_node(graph, places, "home")


def test_missing_node_id_uses_reliably_reconciled_geometry(repaired_network):
    graph = engine._build_graph(engine._read_links(), 7)
    places = engine._read_places().drop(columns="node_id")
    places.loc[places.place_id == "home", "geometry"] = Point(101., 3.)
    assert engine._resolve_node(graph, places, "home") == "node:1"


def test_ambiguous_single_edge_rejects_fallback_but_accepts_explicit_id(repaired_network):
    graph = engine._build_graph(engine._read_links().iloc[[0]], 7)
    assert set(graph.graph["unresolved_coordinate_nodes"]) == {"node:1", "node:2"}
    with pytest.raises(ValueError, match="ambiguous"):
        engine._snap(graph, Point(101., 3.))
    assert engine._resolve_node(graph, engine._read_places(), "home") == "node:1"


@pytest.mark.parametrize("budget", [0, 10000, 100000])
def test_cached_and_uncached_scalar_allocations_are_identical(repaired_network, budget):
    optimized = engine.priorities(budget)
    reference = engine.priorities(budget, use_cache=False)
    pd.testing.assert_frame_equal(optimized, reference, check_exact=True)
    assert optimized.attrs == reference.attrs
    assert optimized.cost_rm.sum() <= budget
    assert optimized.link_id.is_unique


def test_budget_independent_candidates_are_reused_and_returned_copies(repaired_network, monkeypatch):
    original = engine._compute_planning_candidates
    calls = []
    def counted(*, use_cache, **kwargs):
        calls.append(use_cache)
        return original(use_cache=use_cache, **kwargs)
    monkeypatch.setattr(engine, "_compute_planning_candidates", counted)
    baseline = engine.priorities(100000)
    engine.priorities(0)
    engine.priorities(10000)
    assert calls == [True]
    changed = engine.priorities(100000)
    changed.loc[0, "cost_rm"] = -1
    changed.attrs["area_before"] = -1
    demand = engine.walking_demand()
    demand.loc[0, "flow_day"] = -1
    pd.testing.assert_frame_equal(engine.priorities(100000), baseline)
    assert (engine.walking_demand().flow_day >= 0).all()


def test_cache_detects_same_size_content_change_with_restored_timestamp(repaired_network):
    path = repaired_network / "interventions.csv"
    first = engine.priorities(100000)
    stat = path.stat()
    contents = path.read_bytes()
    replacement = contents.replace(b"shade_sail,350,", b"shade_sail,370,")
    assert len(replacement) == len(contents) and replacement != contents
    path.write_bytes(replacement)
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
    second = engine.priorities(100000)
    assert not first.cost_rm.equals(second.cost_rm)


def test_cache_changes_when_demand_assumption_changes(repaired_network, monkeypatch):
    first = engine.walking_demand()
    monkeypatch.setattr(engine, "TRIPS_PER_HOUSEHOLD", {"transit": 1.8})
    second = engine.walking_demand()
    np.testing.assert_allclose(second.flow_day, 2 * first.flow_day)


def test_preview_never_changes_source_or_cached_recommendations(repaired_network):
    hashes = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
              for p in repaired_network.iterdir() if p.is_file()}
    first = engine.priorities(100000)
    engine.apply_fix("ab", "shade_trees")
    pd.testing.assert_frame_equal(engine.priorities(100000), first)
    assert hashes == {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in repaired_network.iterdir() if p.is_file()}


def test_proportional_gain_and_existing_correction_offset_are_preserved(repaired_network):
    row = engine._read_links().iloc[0].copy()
    fix = engine._read_fixes().set_index("fix", drop=False).loc["shade_trees"]
    radiation = engine._weather_radiation()
    baseline = engine._calculate_fix(row, fix, radiation)
    assert baseline["after"]["shade_by_hour"]["h13"] == pytest.approx(.5 + .5 * .35)
    for hour in engine.HOURS:
        row[f"heat_corr_h{hour:02d}"] = row[f"heat_h{hour:02d}"] + 1.25
    corrected = engine._calculate_fix(row, fix, radiation)
    for hour in engine.HOURS:
        key = f"h{hour:02d}"
        assert corrected["before"]["heat_by_hour"][key] - baseline["before"]["heat_by_hour"][key] == pytest.approx(1.25)
        assert corrected["after"]["heat_by_hour"][key] - baseline["after"]["heat_by_hour"][key] == pytest.approx(1.25)
    assert corrected["heat_drop"] == baseline["heat_drop"]


def test_forecast_rows_cannot_change_design_radiation_or_priorities(repaired_network):
    first = engine.priorities(100000)
    expected = engine._weather_radiation()
    weather = pd.read_csv(repaired_network / "weather.csv")
    forecast = weather.assign(day="forecast", date="2026-10-19", sw_wm2=12345.)
    pd.concat([weather, forecast]).to_csv(repaired_network / "weather.csv", index=False)
    assert engine._weather_radiation() == expected
    pd.testing.assert_frame_equal(engine.priorities(100000), first)


@pytest.mark.parametrize("problem", ["duplicate", "missing", "nan", "inf", "negative", "wrong_date"])
def test_invalid_design_radiation_is_rejected(repaired_network, problem):
    path = repaired_network / "weather.csv"
    weather = pd.read_csv(path)
    if problem == "duplicate":
        weather = pd.concat([weather, weather.iloc[[0]]])
    elif problem == "missing":
        weather = weather.iloc[1:]
    elif problem in ("nan", "inf", "negative"):
        weather.loc[0, "sw_wm2"] = {"nan": np.nan, "inf": np.inf, "negative": -1}[problem]
    else:
        weather.loc[0, "date"] = "2026-10-19"
    weather.to_csv(path, index=False)
    with pytest.raises(ValueError):
        engine._weather_radiation()
