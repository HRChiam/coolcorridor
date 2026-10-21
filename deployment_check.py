"""Read-only smoke/benchmark of the exact packaged runtime in a fresh process."""

import argparse
import ctypes
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import sys
from time import perf_counter

from deployment_package import MANIFEST, prepare_runtime, verify_package


def process_memory():
    """Native process RSS/working set, excluding browser and other processes."""
    if os.name == "nt":
        from ctypes import wintypes
        class Counters(ctypes.Structure):
            _fields_ = [("cb", wintypes.DWORD), ("faults", wintypes.DWORD)] + [
                (name, ctypes.c_size_t) for name in (
                    "peak", "current", "peak_paged", "paged", "peak_nonpaged", "nonpaged", "pagefile", "peak_pagefile")]
        data = Counters()
        data.cb = ctypes.sizeof(data)
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetCurrentProcess.restype = wintypes.HANDLE
        psapi = ctypes.WinDLL("psapi", use_last_error=True)
        psapi.GetProcessMemoryInfo.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
        if not psapi.GetProcessMemoryInfo(kernel.GetCurrentProcess(), ctypes.byref(data), data.cb):
            raise OSError(ctypes.get_last_error(), "GetProcessMemoryInfo failed")
        return {"working_set_mib": data.current / 1048576, "peak_working_set_mib": data.peak / 1048576}
    import resource
    return {"peak_rss_mib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024}


def run_checks(manifest_path=MANIFEST, *, runtime_root=None, app_test=False):
    started = perf_counter()
    manifest = verify_package(manifest_path)
    runtime = prepare_runtime(manifest_path, runtime_root)
    preparation_seconds = perf_counter() - started
    sys.path.insert(0, str(runtime))
    import engine
    import heat_map
    import sensors_dashboard as sensors
    from heat_model.effective import load_effective_links
    if Path(engine.__file__).resolve().parent != runtime:
        raise RuntimeError("Run deployment_check.py in a fresh Python process; an unrelated engine is already loaded")
    if Path(engine.DATA_DIR).resolve() != runtime / "data":
        raise ValueError("Unset COOLCORRIDOR_DATA_DIR: packaged tabs must use the same frozen inputs")
    links = load_effective_links(runtime / "data")
    if links.attrs["heat_source"] != "corrected" or links.attrs["correction_version"] != manifest["correction_version"]:
        raise ValueError("Packaged runtime did not load its reviewed corrected heat")
    model_ready_seconds = perf_counter() - started
    timed = {}
    at = perf_counter()
    heat = heat_map.load_heat_data(14)
    timed["heat_map_1491_links_seconds"] = perf_counter() - at
    at = perf_counter()
    routes = {mode: engine.route("P043", "P066", 14, mode) for mode in ("shortest", "coolest")}
    timed["both_default_routes_seconds"] = perf_counter() - at
    at = perf_counter()
    data = sensors.load_sensor_data()
    states = {}
    for minute, site in ((785, "S01"), (730, "S02"), (750, "S02")):
        snapshot = sensors.sensor_statuses(data, sensors.replay_target(data, minute)).set_index("sensor_id")
        states[f"{site}_{minute // 60:02d}:{minute % 60:02d}"] = snapshot.loc[site, "status"]
    timed["sensor_load_and_three_replays_seconds"] = perf_counter() - at
    engine.clear_caches()
    at = perf_counter()
    plan = engine.priorities(100000)
    timed["planner_fresh_100k_seconds"] = perf_counter() - at
    at = perf_counter()
    again = engine.priorities(100000)
    timed["planner_cached_100k_seconds"] = perf_counter() - at
    if not plan.equals(again) or plan.attrs != again.attrs:
        raise AssertionError("Planner cache changed numerical results or metadata")
    app_result = None
    if app_test:
        from streamlit.testing.v1 import AppTest
        at = perf_counter()
        # Execute the extracted genuine app. The cloud bootstrap itself is tested
        # separately in an isolated first-run subprocess test.
        app = AppTest.from_file(str(runtime / "app.py"), default_timeout=90).run()
        if app.exception or app.error:
            raise AssertionError("Packaged Streamlit app reported an error")
        if [tab.label for tab in app.tabs] != ["Cool Route", "Heat Map", "Sensors", "Planner"]:
            raise AssertionError("Packaged app did not render all four tabs")
        if not all(tab.get("deck_gl_json_chart") for tab in app.tabs):
            raise AssertionError("A packaged app tab has no map")
        app_result = {"seconds": perf_counter() - at, "tabs": 4, "maps": 4}
    result = {"checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "python": platform.python_version(), "platform": platform.platform(),
              "package_sha256": manifest["package_sha256"],
              "correction_version": links.attrs["correction_version"],
              "design_date": links.attrs["design_date"], "heat_source": links.attrs["heat_source"],
              "sensor_source": links.attrs["sensor_source"], "links": len(heat),
              "corrected_link_hours": len(links) * len(manifest["hours"]),
              "sensor_sites": len(data.sites), "sensor_readings": len(data.readings),
              "replay_statuses": states, "preparation_seconds": preparation_seconds,
              "model_ready_seconds": model_ready_seconds, "timings": timed,
              "routes": {mode: {key: route[key] for key in (
                  "distance_m", "walking_time_min", "minutes_in_sun", "heat_exposure", "heat_avoided")}
                  for mode, route in routes.items()},
              "planner": {"selected": len(plan), "spent_rm": plan.attrs["spent_rm"],
                          "remaining_rm": 100000 - plan.attrs["spent_rm"],
                          "saving": float(plan.person_min_saved_day.sum()),
                          "area_before": plan.attrs["area_before"], "area_after": plan.attrs["area_after"]},
              "app_test": app_result, "memory": process_memory(),
              "dependency_versions": {name: importlib.metadata.version(name) for name in (
                  "streamlit", "pydeck", "geopandas", "shapely", "pyproj", "pyogrio", "networkx", "numpy", "pandas")}}
    if states != {"S01_13:05": "Anomaly", "S02_12:10": "Missing", "S02_12:30": "Active"}:
        raise AssertionError("Packaged sensor faults do not match the frozen dataset")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    parser.add_argument("--runtime-root", type=Path)
    parser.add_argument("--app-test", action="store_true")
    parser.add_argument("--output", type=Path, help="New JSON evidence file; refuses overwrite")
    args = parser.parse_args()
    if args.output and args.output.exists():
        parser.error("Output already exists; choose a new unused path")
    result = run_checks(args.manifest, runtime_root=args.runtime_root, app_test=args.app_test)
    output = json.dumps(result, indent=2)
    if args.output:
        with args.output.open("x", encoding="utf-8") as stream:
            stream.write(output + "\n")
    print(output)


if __name__ == "__main__":
    main()
