"""Reproducible reports, real engine calculations and non-destructive exports."""

import json
from pathlib import Path
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import engine
import integration_results as results


@pytest.fixture(scope="module")
def real_report():
    return results.collect_results(ROOT / "data", include_benchmarks=False)


def test_real_report_covers_complete_day_and_reproduces_engine(real_report):
    report, tables = real_report
    heat = tables["effective_heat_by_hour"]
    demand = tables["walking_demand"]
    assert len(heat) == report["network"]["link_count"] * 13
    assert heat.groupby("hour").size().index.tolist() == list(range(7, 20))
    assert not heat.duplicated(["link_id", "hour"]).any()
    assert np.isfinite(heat[["heat", "heat_model", "shade", "length_m"]]).all().all()
    assert report["settings"]["route_summary_sample_limit"] is None
    assert report["route_summary"]["evaluated_home_destination_pairs"] > 0
    assert report["route_summary"]["hour"] == "07:00-19:00 demand-weighted"
    assert report["walking_demand"]["flow_day_link_traversals"] == pytest.approx(demand.flow_day.sum())
    assert report["network"]["authoritative_place_nodes_checked"] == report["network"]["place_count"]
    assert not report["network"]["unresolved_coordinate_nodes"]
    assert tables["place_node_resolutions"].used_exported_node.all()
    assert tables["place_node_resolutions"].longitude.between(-180, 180).all()
    assert tables["place_node_resolutions"].latitude.between(-90, 90).all()
    assert tables["population_exposure_by_hour"].population_exposure.sum() == pytest.approx(
        report["planner"]["area_before"], abs=.00051)
    selected = tables["priorities"]
    assert selected.link_id.is_unique
    assert selected.cost_rm.sum() == pytest.approx(report["planner"]["spent_rm"])
    assert report["planner"]["spent_rm"] <= 100000
    assert report["planner"]["remaining_rm"] == pytest.approx(100000 - selected.cost_rm.sum())
    assert report["planner"]["metadata"]["shade_gain_rule"] == "proportional_remaining_sunlight"
    indexed = heat.loc[heat.hour == report["settings"]["route_hour"]].set_index("link_id")
    for route in report["routes"].values():
        walked = indexed.loc[route["link_ids"]]
        expected = (walked.length_m / engine.WALKING_METRES_PER_MIN *
                    (walked.heat - engine.COMFORT_C).clip(lower=0)).sum()
        assert route["heat_exposure"] == pytest.approx(expected, abs=.00051)
    assert report["input_hashes"] == results.input_hashes(ROOT / "data")


def test_results_export_preserves_inputs_and_rejects_overwrite(tmp_path, real_report):
    report, tables = real_report
    before = results.input_hashes(ROOT / "data")
    output = results.write_results(report, tables, data_dir=ROOT / "data", output_dir=tmp_path / "new-report")
    exported = json.loads((output / "results.json").read_text(encoding="utf-8"))
    assert exported["output_version"] == report["output_version"]
    pd.testing.assert_frame_equal(pd.read_csv(output / "priorities.csv"),
                                  tables["priorities"], check_dtype=False, check_exact=False)
    original = (output / "results.json").read_bytes()
    with pytest.raises(FileExistsError):
        results.write_results(report, tables, output_dir=output)
    assert (output / "results.json").read_bytes() == original
    assert results.input_hashes(ROOT / "data") == before


def test_real_planner_reference_matches_cached_path():
    before = results.input_hashes(ROOT / "data")
    measured = results.benchmark_budget(10000, ROOT / "data")
    assert measured["outputs_equal"] is True
    assert measured["spent_rm"] <= 10000
    assert all(measured[key] >= 0 for key in
               ("fresh_seconds", "cached_seconds", "uncached_reference_seconds"))
    assert results.input_hashes(ROOT / "data") == before


def test_results_version_changes_for_data_code_or_settings():
    original = results.results_version({"network": "a"}, {"engine": "a"}, {"budget": 100000})
    assert results.results_version({"network": "a"}, {"engine": "a"}, {"budget": 100000}) == original
    for inputs, code, settings in [({"network": "b"}, {"engine": "a"}, {"budget": 100000}),
                                    ({"network": "a"}, {"engine": "b"}, {"budget": 100000}),
                                    ({"network": "a"}, {"engine": "a"}, {"budget": 10000})]:
        assert results.results_version(inputs, code, settings) != original


def test_hottest_links_ties_use_walking_load_and_actual_hour():
    heat = pd.DataFrame([
        {"link_id": "a", "hour": 7, "heat": 30., "length_m": 100},
        {"link_id": "b", "hour": 7, "heat": 30., "length_m": 50},
        {"link_id": "c", "hour": 7, "heat": 35., "length_m": 80},
        {"link_id": "a", "hour": 14, "heat": 40., "length_m": 100},
        {"link_id": "b", "hour": 14, "heat": 38., "length_m": 50},
        {"link_id": "c", "hour": 14, "heat": 37., "length_m": 80}])
    demand = pd.DataFrame({"link_id": ["a", "b", "c"], "flow_day": [1., 3., 0.]})
    ranked = results.hottest_links(heat, demand, top=2)
    assert ranked.loc[ranked.hour == 7, "link_id"].tolist() == ["c", "b"]
    walked = results.hottest_links(heat, demand, top=2, walked_only=True)
    assert walked.loc[walked.hour == 7, "link_id"].tolist() == ["b", "a"]
    assert walked.loc[walked.hour == 14, "link_id"].tolist() == ["a", "b"]
    assert walked.groupby("hour")["rank"].apply(list).tolist() == [[1, 2], [1, 2]]


def test_scalar_reference_comparison_detects_metadata_change():
    expected = pd.DataFrame({"cost_rm": [100.]})
    expected.attrs["area_before"] = 123.
    altered = expected.copy()
    altered.attrs["area_before"] = 124.
    with pytest.raises(AssertionError, match="metadata"):
        results._assert_same_recommendations(expected, altered)


def test_export_rejects_unsafe_table_name_without_creating_directory(tmp_path):
    output = tmp_path / "new"
    with pytest.raises(ValueError, match="table name"):
        results.write_results({"output_version": "test"}, {"../escape": pd.DataFrame()}, output_dir=output)
    assert not output.exists()


def test_cli_rejects_existing_output_before_calculation(tmp_path, monkeypatch):
    (tmp_path / "keep.txt").write_text("user work", encoding="utf-8")
    def unexpected(*args, **kwargs):
        raise AssertionError("Calculation should not run when an explicit output already exists")
    monkeypatch.setattr(results, "collect_results", unexpected)
    with pytest.raises(SystemExit) as error:
        results.main(["--output", str(tmp_path)])
    assert error.value.code == 2
    assert (tmp_path / "keep.txt").read_text(encoding="utf-8") == "user work"


def test_data_directory_restores_after_failure(tmp_path):
    original = engine.DATA_DIR
    with pytest.raises(RuntimeError):
        with results._data_directory(tmp_path):
            raise RuntimeError("independent read failure")
    assert engine.DATA_DIR == original
