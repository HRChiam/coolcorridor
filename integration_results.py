"""Recompute integration results without replacing frozen inputs or prior reports.

Run from the repository root with the project Python.  The default destination
is a new content-versioned directory below data/results/.  Repeating identical
inputs requires an explicitly supplied, unused --output directory.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from time import perf_counter

import numpy as np
import pandas as pd

import engine
from cool_route import default_place_ids
from heat_model.effective import HOURS, TZ, input_signature, load_effective_links

ROOT = Path(__file__).resolve().parent
SCHEMA_VERSION = 1
BUDGETS = (0.0, 10000.0, 100000.0)
INPUT_FILES = ("links.geojson", "places.geojson", "weather.csv", "interventions.csv",
               "sensor_links.csv", "sensors_stream.csv")
SOURCE_FILES = ("engine.py", "heat_model/effective.py", "heat_model/heat.py",
                "heat_model/sensor_correction.py", "integration_results.py")
UNITS = {
    "heat": "degree-C-labelled modelled heat index; not measured air temperature",
    "heat_exposure": "degree-C-minutes above comfort threshold per trip",
    "population_exposure": "person-degree-C-minutes above comfort threshold per day",
    "investment": "RM; assumed costs, not verified construction quotations",
    "flow_day": "link traversals per day, not unique people or trips",
    "validation_error": "degrees C; held-out simulated air residual, not field heat-index accuracy",
    "minutes_above_comfort": "count of hourly samples above comfort times 60; discrete model indicator",
}


def _digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _records(table):
    """Missing optional names stay JSON null; numerical heat is validated upstream."""
    return table.astype(object).where(pd.notna(table), None).to_dict("records")


def input_hashes(data_dir):
    """Include raw frozen inputs and the exact active correction artifacts."""
    directory = Path(data_dir).resolve()
    files = {name: directory / name for name in INPUT_FILES}
    files["../config/sensor_simulation.json"] = directory.parent / "config/sensor_simulation.json"
    # This validates the correction pointer before returning artifact paths.
    for name, _ in input_signature(directory):
        if name.startswith("corrections/"):
            files[name] = directory / name
    return {name: _digest(path) for name, path in sorted(files.items()) if path.is_file()}


def source_hashes():
    return {name: _digest(ROOT / name) for name in SOURCE_FILES if (ROOT / name).is_file()}


def results_version(inputs, sources, settings):
    encoded = json.dumps({"schema_version": SCHEMA_VERSION, "inputs": inputs,
                          "sources": sources, "settings": settings}, sort_keys=True).encode()
    return "integration-" + hashlib.sha256(encoded).hexdigest()[:20]


@contextmanager
def _data_directory(directory):
    original = engine.DATA_DIR
    engine.set_data_dir(directory)
    try:
        yield
    finally:
        engine.set_data_dir(original)


def _assert_same_recommendations(left, right):
    """Compare the repaired cached and scalar paths, including result metadata."""
    pd.testing.assert_frame_equal(left, right, check_exact=False, rtol=1e-10, atol=1e-8)
    if left.attrs.keys() != right.attrs.keys():
        raise AssertionError("Cached and uncached recommendation metadata differ")
    for key, value in left.attrs.items():
        other = right.attrs[key]
        if isinstance(value, (int, float, np.number)) and not isinstance(value, bool):
            if not np.isclose(value, other, rtol=1e-10, atol=1e-8):
                raise AssertionError(f"Cached and uncached metadata differ: {key}")
        elif value != other:
            raise AssertionError(f"Cached and uncached metadata differ: {key}")


def benchmark_budget(budget, data_dir):
    """Time one cold engine-cache call, a warm call and an uncached reference.

    The CLI executes this function in a fresh Python subprocess per budget.
    Timings exclude interpreter startup and do not flush operating-system caches.
    """
    with _data_directory(data_dir):
        engine.clear_caches()
        started = perf_counter()
        fresh = engine.priorities(budget)
        fresh_seconds = perf_counter() - started
        started = perf_counter()
        cached = engine.priorities(budget)
        cached_seconds = perf_counter() - started
        started = perf_counter()
        reference = engine.priorities(budget, use_cache=False)
        reference_seconds = perf_counter() - started
        _assert_same_recommendations(fresh, cached)
        _assert_same_recommendations(fresh, reference)
        return {"budget_rm": float(budget), "fresh_seconds": fresh_seconds,
                "cached_seconds": cached_seconds, "uncached_reference_seconds": reference_seconds,
                "outputs_equal": True, "selected_count": len(fresh),
                "spent_rm": float(fresh.attrs["spent_rm"])}


def benchmark_planner(data_dir, budgets=BUDGETS):
    rows = []
    for budget in budgets:
        command = [sys.executable, "-B", str(Path(__file__).resolve()),
                   "--data", str(Path(data_dir).resolve()), "--benchmark-budget", str(budget)]
        completed = subprocess.run(command, capture_output=True, text=True, check=True)
        rows.append(json.loads(completed.stdout))
    return pd.DataFrame(rows)


def hottest_links(hourly_heat, demand, *, top=10, walked_only=False):
    """Rank actual effective heat; break ties by assumed household walking load."""
    joined = hourly_heat.merge(demand[["link_id", "flow_day"]], on="link_id", validate="many_to_one")
    if walked_only:
        joined = joined.loc[joined.flow_day > 0].copy()
    joined["walking_load_m_day"] = joined.flow_day * joined.length_m
    joined = joined.sort_values(["hour", "heat", "walking_load_m_day", "link_id"],
                                ascending=[True, False, False, True])
    joined = joined.groupby("hour", sort=True).head(top).copy()
    joined.insert(0, "rank", joined.groupby("hour").cumcount() + 1)
    return joined.reset_index(drop=True)


def _correction_results(directory, links):
    version = links.attrs.get("correction_version")
    if version is None:
        return {"available": False, "heat_source": "baseline", "validation": None}, {}
    bundle = directory / "corrections" / version
    manifest = links.attrs["correction_manifest"]
    validation = pd.read_csv(bundle / "sensor_validation.csv")
    tables = {"sensor_validation": validation,
              "sensor_offsets": pd.read_csv(bundle / "sensor_offsets.csv"),
              "rejected_samples": pd.read_csv(bundle / "rejected_samples.csv")}
    return {"available": True, "bundle": str(bundle), "correction_version": version,
            "manifest": manifest, "validation": manifest.get("validation"),
            "validation_description": UNITS["validation_error"]}, tables


def collect_results(data_dir=None, *, budget=100000.0, route_hour=14,
                    include_benchmarks=True):
    """Compute every reported value from the current public engine interfaces."""
    directory = Path(data_dir if data_dir is not None else engine.DATA_DIR).resolve()
    before = input_hashes(directory)
    sources = source_hashes()
    settings = {"budget_rm": float(budget), "route_hour": route_hour,
                "route_summary_hours": list(HOURS), "route_summary_sample_limit": None,
                "benchmark_budgets_rm": list(BUDGETS) if include_benchmarks else []}
    with _data_directory(directory):
        links = load_effective_links(directory)
        places = engine._read_places()
        graph = engine._build_graph(links, HOURS[0])
        node_rows = []
        for place in places.itertuples():
            resolved = engine._resolve_node(graph, places, place.place_id)
            supplied = getattr(place, "node_id", None)
            authoritative = engine._node_key(supplied) if pd.notna(supplied) else None
            if authoritative is not None and resolved != authoritative:
                raise AssertionError(f"Exported node_id was not honored for {place.place_id}")
            position = graph.nodes[resolved]["xy"]
            node_rows.append({"place_id": place.place_id, "exported_node_id": supplied,
                              "resolved_node": resolved, "used_exported_node": authoritative is not None,
                              "longitude": position[0] if position is not None else None,
                              "latitude": position[1] if position is not None else None})
        origin, destination = default_place_ids(places)
        settings.update(origin_id=str(origin), destination_id=str(destination))
        routes = {mode: engine.route(origin, destination, route_hour, mode)
                  for mode in ("shortest", "coolest")}
        demand = engine.walking_demand()
        hourly = []
        for hour in HOURS:
            at_hour = engine.heat_at(hour)
            columns = [column for column in ("link_id", "hour", "design_date", "heat_model", "heat",
                       "heat_source", "sensor_source", "shade", "length_m", "covered", "canopy",
                       "surface", "albedo", "name") if column in at_hour]
            hourly.append(pd.DataFrame(at_hour[columns]))
        heat = pd.concat(hourly, ignore_index=True)
        above = heat.assign(minutes_above_comfort=(heat.heat > engine.COMFORT_C).astype(int) * 60)
        minutes = above.groupby("link_id", as_index=False).minutes_above_comfort.sum()
        heat = heat.merge(minutes, on="link_id", validate="many_to_one")
        exposed = heat.merge(demand, on="link_id", validate="many_to_one")
        exposed["flow"] = [row[f"flow_h{int(row['hour']):02d}"] for _, row in exposed.iterrows()]
        exposed["population_exposure"] = (exposed.flow * exposed.length_m /
                                           engine.WALKING_METRES_PER_MIN *
                                           (exposed.heat - engine.COMFORT_C).clip(lower=0))
        exposed["baseline_population_exposure"] = (exposed.flow * exposed.length_m /
                                                    engine.WALKING_METRES_PER_MIN *
                                                    (exposed.heat_model - engine.COMFORT_C).clip(lower=0))
        exposure_by_hour = exposed.groupby("hour", as_index=False)[
            ["population_exposure", "baseline_population_exposure"]].sum()
        picks = engine.priorities(budget)
        spent = float(picks.cost_rm.sum())
        if spent > float(budget) + 1e-7 or not np.isclose(spent, picks.attrs["spent_rm"], rtol=0, atol=.005):
            raise AssertionError("Planner spending is inconsistent with its selected interventions")
        if not np.isclose(exposure_by_hour.population_exposure.sum(), picks.attrs["area_before"], rtol=0, atol=.00051):
            raise AssertionError("Planner and per-link effective-heat population exposure disagree")
        preview = None
        if not picks.empty:
            first = picks.iloc[0]
            preview = engine.apply_fix(first.link_id, first.fix)
        # Deliberately no sampling: every eligible home/category pair, all 13 hours.
        summary = engine.route_summary(sample_limit=None, hour=None)
        hottest_all = hottest_links(heat, demand)
        hottest_walked = hottest_links(heat, demand, walked_only=True)
        correction, correction_tables = _correction_results(directory, links)
        households = pd.to_numeric(places.loc[places.kind == "home", "households"], errors="raise")
        report = {"schema_version": SCHEMA_VERSION, "settings": settings, "units": UNITS,
                  "design_date": links.attrs.get("design_date"), "timezone": TZ,
                  "heat_source": links.attrs.get("heat_source"),
                  "sensor_source": links.attrs.get("sensor_source"),
                  "correction_version": links.attrs.get("correction_version"),
                  "input_hashes": before, "source_hashes": sources,
                  "routes": routes, "route_summary": summary,
                  "network": {"link_count": len(links), "place_count": len(places),
                              "households": float(households.sum()),
                              "graph_node_count": graph.number_of_nodes(),
                              "authoritative_place_nodes_checked": sum(row["used_exported_node"] for row in node_rows),
                              "unresolved_coordinate_nodes": list(graph.graph.get("unresolved_coordinate_nodes", ()))},
                  "walking_demand": {"flow_day_link_traversals": float(demand.flow_day.sum()),
                                     "links_with_positive_flow": int((demand.flow_day > 0).sum()),
                                     "baseline_population_exposure": float(exposure_by_hour.baseline_population_exposure.sum()),
                                     "effective_population_exposure": float(exposure_by_hour.population_exposure.sum()),
                                     "description": UNITS["flow_day"]},
                  "planner": {"budget_rm": float(budget), "selected_count": len(picks),
                              "spent_rm": spent, "remaining_rm": float(budget) - spent,
                              "area_before": picks.attrs["area_before"],
                              "area_after": picks.attrs["area_after"],
                              "exposure_saved": picks.attrs["area_before"] - picks.attrs["area_after"],
                              "metadata": dict(picks.attrs), "recommendations": _records(picks)},
                  "preview": preview, "correction": correction,
                  "hottest_walked_links_at_13": _records(hottest_walked.loc[hottest_walked.hour == 13]),
                  "hottest_network_links_at_13": _records(hottest_all.loc[hottest_all.hour == 13])}
        tables = {"walking_demand": demand, "effective_heat_by_hour": heat,
                  "population_exposure_by_hour": exposure_by_hour,
                  "place_node_resolutions": pd.DataFrame(node_rows),
                  "hottest_links_by_hour": hottest_all, "hottest_walked_links_by_hour": hottest_walked,
                  "priorities": picks, **correction_tables}
    if include_benchmarks:
        tables["planner_benchmarks"] = benchmark_planner(directory)
        report["planner_benchmarks"] = {
            "method": "Fresh Python subprocess per budget; cold engine caches, then warm call, then same repaired calculation with use_cache=False. Interpreter startup excluded; OS caches not flushed.",
            "rows": _records(tables["planner_benchmarks"])}
    if before != input_hashes(directory) or sources != source_hashes():
        raise RuntimeError("Inputs or source changed during results generation; no report may be published")
    report["output_version"] = results_version(before, sources, settings)
    report["generated_at_utc"] = datetime.now(timezone.utc).isoformat()
    return report, tables


def _json_default(value):
    if isinstance(value, (Path, datetime)):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(f"Unsupported results value {type(value).__name__}")


def write_results(report, tables, *, data_dir=None, output_dir=None):
    """Create an unused output directory; never overwrite an existing report."""
    directory = Path(data_dir if data_dir is not None else engine.DATA_DIR).resolve()
    output = Path(output_dir).resolve() if output_dir is not None else directory / "results" / report["output_version"]
    # Validate serialization before reserving a destination or writing any files.
    encoded = json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False, default=_json_default) + "\n"
    for name in tables:
        if not name.replace("_", "").isalnum():
            raise ValueError(f"Invalid results table name {name!r}")
    output.mkdir(parents=True, exist_ok=False)
    for name, table in tables.items():
        with (output / f"{name}.csv").open("x", encoding="utf-8", newline="") as handle:
            table.to_csv(handle, index=False)
    with (output / "results.json").open("x", encoding="utf-8") as handle:
        handle.write(encoded)
    return output


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, default=engine.DATA_DIR)
    parser.add_argument("--output", type=Path, help="An unused directory; existing paths are never replaced")
    parser.add_argument("--budget", type=float, default=100000.0)
    parser.add_argument("--route-hour", type=int, choices=HOURS, default=14)
    parser.add_argument("--skip-benchmarks", action="store_true", help="Omit optional subprocess timings")
    parser.add_argument("--benchmark-budget", type=float, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)
    if args.benchmark_budget is not None:
        print(json.dumps(benchmark_budget(args.benchmark_budget, args.data), allow_nan=False))
        return
    if args.output is not None and args.output.exists():
        parser.error(f"Output already exists; choose an unused directory: {args.output}")
    report, tables = collect_results(args.data, budget=args.budget, route_hour=args.route_hour,
                                     include_benchmarks=not args.skip_benchmarks)
    output = write_results(report, tables, data_dir=args.data, output_dir=args.output)
    print(f"Results: {output}")
    print(f"Heat source: {report['heat_source']}; sensors: {report['sensor_source']}")
    planner = report["planner"]
    print(f"RM{planner['budget_rm']:,.2f}: {planner['selected_count']} interventions; "
          f"spent RM{planner['spent_rm']:,.2f}; remaining RM{planner['remaining_rm']:,.2f}")
    print(f"Modelled exposure saved: {planner['exposure_saved']:,.3f} person-degree-C-min/day")


if __name__ == "__main__":
    main()
