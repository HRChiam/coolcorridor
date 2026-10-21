"""Regression contracts for combining main's budget fix with corrected heat."""

import hashlib
import itertools
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import engine
from heat_model.effective import effective_heat_at, load_effective_links
from heat_model import results


ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("budget", [0, 49, 100, 150])
def test_optimizer_matches_exhaustive_search_on_rounded_grid(budget):
    groups = [
        [{"link_id": "A", "fix": "tree", "cost_rm": 49.01, "person_min_saved_day": 60},
         {"link_id": "A", "fix": "sail", "cost_rm": 99.01, "person_min_saved_day": 90}],
        [{"link_id": "B", "fix": "sail", "cost_rm": 50, "person_min_saved_day": 55}],
    ]
    options = [option for group in groups for option in group]
    feasible = []
    for choice in itertools.product(*[[None, *group] for group in groups]):
        selected = [option for option in choice if option]
        cost = sum(np.ceil(option["cost_rm"] / 10) * 10 for option in selected)
        if cost <= (budget // 10) * 10:
            feasible.append(sum(option["person_min_saved_day"] for option in selected))
    picked = engine._best_mix(options, budget)
    assert sum(option["person_min_saved_day"] for option in picked) == max(feasible)
    assert sum(option["cost_rm"] for option in picked) <= budget
    assert len({option["link_id"] for option in picked}) == len(picked)


def test_horizon_cache_and_budget_outputs_agree_with_reference():
    ten = engine.priorities(100000, horizon_years=10)
    one = engine.priorities(100000, horizon_years=1)
    pd.testing.assert_frame_equal(ten, engine.priorities(100000, horizon_years=10))
    assert one.attrs["horizon_years"] == 1
    assert ten.attrs["area_after"] < one.attrs["area_after"]
    assert ten.attrs["area_before"] == one.attrs["area_before"]
    assert ten.attrs["area_before"] - ten.attrs["area_after"] == pytest.approx(
        ten.benefit_over_horizon.sum(), abs=.001)
    assert ten.attrs["upkeep_rm_per_year"] == pytest.approx(ten.upkeep_rm_per_year.sum())
    pd.testing.assert_frame_equal(one, engine.priorities(100000, horizon_years=1, use_cache=False))
    quick = engine.priorities(100000, quick_wins_only=True)
    assert quick.quick_win.all()


def test_rebased_provenance_preserves_all_frozen_correction_outputs():
    pointer = json.loads((ROOT / "data/corrections/current.json").read_text())
    active = ROOT / "data/corrections" / pointer["version"]
    previous = ROOT / "data/corrections/v1-20260906-2487cdd6cca7ef71"
    for name in ("corrected_heat.csv", "sensor_offsets.csv", "sensor_validation.csv", "rejected_samples.csv"):
        assert hashlib.sha256((active / name).read_bytes()).digest() == hashlib.sha256(
            (previous / name).read_bytes()).digest()
    links = load_effective_links(ROOT / "data")
    assert len(links) == 1491
    assert {"unsafe", "confidence"}.issubset(links)
    for hour in engine.HOURS:
        a = effective_heat_at(hour, ROOT / "data").set_index("link_id").heat
        b = engine.heat_at(hour).set_index("link_id").heat
        pd.testing.assert_series_equal(a, b)
        np.testing.assert_array_equal(results.best_heat(links, hour), links[f"heat_corr_h{hour:02d}"])


def test_merged_routes_keep_authoritative_nodes_and_safe_default():
    places = engine._read_places()
    graph = engine._build_graph(engine._read_links(), 14)
    assert len(graph) == 1034 and not graph.graph["unresolved_coordinate_nodes"]
    assert len(places) == 66
    for row in places.itertuples():
        assert engine._resolve_node(graph, places, row.place_id) == f"node:{int(row.node_id)}"
    for mode in engine.ROUTE_MODES:
        route = engine.route("P043", "P066", 14, mode)
        assert route["heat_source"] == "corrected"
        assert not route["uses_unsafe"]
        assert route["distance_m"] == pytest.approx(824.5 if mode == "shortest" else 826.3)
