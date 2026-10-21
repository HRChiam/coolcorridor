"""Shared heat contract, offline sensor policy and immutable bundle regressions."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

import numpy as np
import pandas as pd
import pytest
import geopandas as gpd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from heat_model import effective, sensor_correction as correction


def copy_inputs(root):
    directory = root / "data"
    directory.mkdir(parents=True)
    (root / "config").mkdir()
    for name in ("links.geojson", "weather.csv", "sensor_links.csv", "sensors_stream.csv"):
        shutil.copy2(ROOT / "data" / name, directory / name)
    shutil.copy2(ROOT / "config/sensor_simulation.json", root / "config/sensor_simulation.json")
    return directory


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    directory = copy_inputs(tmp_path_factory.mktemp("effective-bundle"))
    before = {p: p.read_bytes() for p in directory.iterdir() if p.is_file()}
    version = correction.generate_bundle(directory, activate=True)
    for path, content in before.items():
        assert path.read_bytes() == content
    return directory, version


def test_versioned_bundle_complete_reproducible_and_read_only(generated):
    directory, version = generated
    manifest = json.loads((version / "manifest.json").read_text())
    assert manifest["row_count"] == 1491 * 13
    assert manifest["link_count"] == 1491
    assert manifest["sensor_source"] == "simulated"
    assert manifest["simulation_seed"] == 20260906
    assert manifest["rejected_anomaly_samples"] == 1
    assert all(count == 8 for count in manifest["sensor_hours_per_hour"].values())
    assert len(pd.read_csv(version / "sensor_offsets.csv")) == 104
    assert len(pd.read_csv(version / "sensor_validation.csv")) == 96
    before = {p: p.read_bytes() for p in version.iterdir()}
    assert correction.generate_bundle(directory, activate=True) == version
    assert all(path.read_bytes() == content for path, content in before.items())
    for hour in effective.HOURS:
        frame = effective.effective_heat_at(hour, directory)
        assert len(frame) == 1491
        assert frame.heat_source.eq("corrected").all()
        assert frame.sensor_source.eq("simulated").all()
        assert frame.design_date.eq("2026-09-06").all()
        assert frame.hour.eq(hour).all()
        np.testing.assert_allclose(frame.heat, frame[f"heat_corr_h{hour:02d}"])
        np.testing.assert_allclose(frame.heat_model, frame[f"heat_h{hour:02d}"])


def test_outlier_rule_preserves_fault_csv_and_noon_window(generated):
    directory, version = generated
    readings = correction.load_readings(directory / "sensors_stream.csv", data_dir=directory)
    excluded = readings.loc[readings.anomaly]
    assert len(excluded) == 1
    assert excluded.iloc[0].sensor_id == "S01"
    assert excluded.iloc[0].timestamp.isoformat() == "2026-09-06T13:05:00+08:00"
    assert excluded.iloc[0].departure_c == pytest.approx(7.6825)
    assert excluded.iloc[0].air_temp_c == 43.738
    noon = pd.read_csv(version / "sensor_offsets.csv").query("sensor_id == 'S02' and hour == 12").iloc[0]
    assert noon.accepted_samples == 6  # 11:30..11:55 remains, despite 12:00..12:25 outage.
    assert noon.offset == pytest.approx(1.170)
    assert len(readings) == 1154
    from sensors_dashboard import load_sensor_data
    dashboard = load_sensor_data(directory, directory.parent / "config/sensor_simulation.json")
    np.testing.assert_array_equal(readings.anomaly, dashboard.readings.anomaly)


def test_validation_uses_previous_hour_air_residual_not_heat_index(generated):
    _, version = generated
    records = pd.read_csv(version / "sensor_validation.csv")
    np.testing.assert_allclose(records.error_before, records.air_offset_c.abs(), atol=1e-8)
    np.testing.assert_allclose(records.error_after,
                               (records.air_offset_c - records.previous_hour_correction_c).abs(), atol=1e-8)
    assert records.error_after.mean() < records.error_before.mean()


def test_forecast_rows_cannot_change_model_key_or_correction_bundle(generated, tmp_path):
    directory, _ = generated
    copied = tmp_path / "copy"
    shutil.copytree(directory.parent, copied)
    directory = copied / "data"
    old = effective.input_signature(directory)
    before = effective.effective_heat_at(14, directory)
    weather = pd.read_csv(directory / "weather.csv")
    weather.loc[weather.day == "forecast", ["air_temp_c", "sw_wm2"]] = 9876
    weather["rh_pct"] = weather.rh_pct.astype(float)
    weather.loc[weather.day == "forecast", "rh_pct"] = 99.5
    weather["sun_azim_deg"] = weather.sun_azim_deg.astype(str)
    weather.loc[weather.day == "forecast", "sun_azim_deg"] = "irrelevant-forecast-value"
    weather = pd.concat([weather, weather.loc[weather.day == "forecast"]], ignore_index=True)
    weather.to_csv(directory / "weather.csv", index=False)
    assert effective.input_signature(directory) == old
    after = effective.effective_heat_at(14, directory)
    np.testing.assert_array_equal(before.heat, after.heat)


@pytest.mark.parametrize("problem", ["duplicate", "missing", "wrong_date", "nan", "infinite", "negative"])
def test_strict_design_weather_rejects_invalid_rows(tmp_path, problem):
    weather = pd.read_csv(ROOT / "data/weather.csv")
    if problem == "duplicate":
        weather.loc[1, "hour"] = 7
    elif problem == "missing":
        weather = weather.drop(index=1)
    elif problem == "wrong_date":
        weather.loc[0, "date"] = "2026-09-07"
    else:
        weather.loc[0, "sw_wm2"] = {"nan": np.nan, "infinite": np.inf, "negative": -1}[problem]
    path = tmp_path / "weather.csv"
    weather.to_csv(path, index=False)
    with pytest.raises(ValueError):
        effective.design_weather(path)


@pytest.mark.parametrize("problem", ["source", "mapping", "nan_air", "naive", "duplicate", "nanosecond"])
def test_bad_sensor_inputs_rejected(tmp_path, problem):
    readings = pd.read_csv(ROOT / "data/sensors_stream.csv")
    if problem == "source":
        readings.loc[0, "source"] = "measured"
    elif problem == "mapping":
        readings.loc[0, "link_id"] = "unknown"
    elif problem == "nan_air":
        readings.loc[0, "air_temp_c"] = np.nan
    elif problem == "naive":
        readings.loc[0, "timestamp"] = "2026-09-06T07:00:00"
    elif problem == "nanosecond":
        readings["timestamp"] = readings.timestamp.str.replace("00+08:00", "00.000000001+08:00", regex=False)
    else:
        readings = pd.concat([readings, readings.iloc[[0]]], ignore_index=True)
    path = tmp_path / "readings.csv"
    readings.to_csv(path, index=False)
    with pytest.raises(ValueError):
        correction.load_readings(path)


def test_other_date_is_filtered_without_hour_contamination(tmp_path):
    readings = pd.read_csv(ROOT / "data/sensors_stream.csv")
    extra = readings.iloc[[0]].copy()
    extra["timestamp"] = "2026-09-07T07:00:00+08:00"
    extra["air_temp_c"] = 100
    path = tmp_path / "readings.csv"
    pd.concat([readings, extra], ignore_index=True).to_csv(path, index=False)
    selected = correction.load_readings(path)
    assert len(selected) == 1154
    assert selected.attrs["ignored_outside_design_window"] == 1
    assert selected.timestamp.dt.strftime("%Y-%m-%d").eq(effective.DESIGN_DATE).all()


def test_insufficient_hour_retains_complete_explicit_baseline_fallback(tmp_path, monkeypatch):
    directory = copy_inputs(tmp_path / "fallback")
    readings = pd.read_csv(directory / "sensors_stream.csv")
    # Remove the entire nearest-hour window for 14:00: 13:30 <= t < 14:30.
    times = pd.to_datetime(readings.timestamp, utc=True).dt.tz_convert(effective.TZ)
    minutes = times.dt.hour * 60 + times.dt.minute
    readings.loc[~minutes.between(13 * 60 + 30, 14 * 60 + 29)].to_csv(directory / "sensors_stream.csv", index=False)
    correction.generate_bundle(directory, activate=True)
    frame = effective.effective_heat_at(14, directory)
    assert len(frame) == 1491
    assert frame.heat_source.eq("baseline").all()
    assert frame.sensor_source.isna().all()
    np.testing.assert_array_equal(frame.heat, frame.heat_model)
    import engine
    monkeypatch.setattr(engine, "DATA_DIR", directory)
    routed = engine.heat_at(14)
    assert routed.attrs["heat_source"] == "baseline"
    assert routed.attrs["sensor_corrected"] is False
    assert routed.heat_source.eq("baseline").all()
    np.testing.assert_array_equal(routed.heat, routed.heat_model)
    shutil.copy2(ROOT / "data/places.geojson", directory / "places.geojson")
    route = engine.route("P043", "P066", 14, "shortest")
    assert route["heat_source"] == "baseline"


@pytest.mark.parametrize("problem", ["output_hash", "input_hash", "partial", "nonfinite"])
def test_invalid_bundles_fail_closed(generated, tmp_path, problem):
    directory, version = generated
    copied = tmp_path / "copy"
    shutil.copytree(directory.parent, copied)
    directory, version = copied / "data", copied / "data/corrections" / version.name
    if problem == "input_hash":
        path = directory / "sensors_stream.csv"
        path.write_text(path.read_text() + "\n")
    else:
        values = pd.read_csv(version / "corrected_heat.csv")
        if problem == "partial":
            values = values.iloc[1:]
        elif problem == "nonfinite":
            values.loc[0, "heat"] = np.inf
        else:
            values.loc[0, "heat"] += 1
        values.to_csv(version / "corrected_heat.csv", index=False)
        if problem != "output_hash":
            # Even a structurally re-signed invalid bundle must fail validation.
            manifest_path = version / "manifest.json"
            manifest = json.loads(manifest_path.read_text())
            manifest["outputs"]["corrected_heat.csv"] = effective.sha256_file(version / "corrected_heat.csv")
            manifest_path.write_text(json.dumps(manifest))
            pointer = json.loads((directory / "corrections/current.json").read_text())
            pointer["manifest_sha256"] = effective.sha256_file(manifest_path)
            (directory / "corrections/current.json").write_text(json.dumps(pointer))
    with pytest.raises(ValueError):
        effective.load_effective_links(directory)


def test_baseline_is_explicit_and_embedded_partial_corrections_reject(tmp_path):
    directory = copy_inputs(tmp_path / "baseline")
    baseline = effective.effective_heat_at(14, directory)
    assert baseline.heat_source.eq("baseline").all()
    np.testing.assert_array_equal(baseline.heat, baseline.heat_model)
    payload = json.loads((directory / "links.geojson").read_text())
    payload["features"][0]["properties"]["heat_corr_h14"] = 40
    (directory / "links.geojson").write_text(json.dumps(payload))
    with pytest.raises(ValueError, match="incomplete"):
        effective.load_effective_links(directory)


def test_nearest_available_sensor_and_zero_coverage_preserve_original_model():
    weights = pd.DataFrame({"S01": [1, .4, 0], "S02": [.8, .6, 0]}, index=["A", "B", "C"])
    offsets = pd.Series({"S01": 2., "S02": -1.})
    np.testing.assert_allclose(correction.correction(weights, offsets), [2., -.6, 0])
    np.testing.assert_allclose(correction.correction(weights, pd.Series(dtype=float)), [0, 0, 0])


def test_projected_source_normalizes_to_shared_longitude_latitude(tmp_path):
    directory = copy_inputs(tmp_path / "projected")
    source = gpd.read_file(directory / "links.geojson")
    source.to_crs(32647).to_file(directory / "links.geojson", driver="GeoJSON")
    frame = effective.effective_heat_at(14, directory)
    assert frame.crs.to_epsg() == 4326
    np.testing.assert_allclose(frame.total_bounds, source.to_crs(4326).total_bounds, atol=1e-8)


@pytest.mark.skipif(os.name != "nt", reason="Windows workspace ACL regression")
def test_generated_bundle_inherits_workspace_permissions(generated):
    _, version = generated
    escaped = str(version).replace("'", "''")
    script = (f"$bundleAcl = Get-Acl -LiteralPath '{escaped}'; "
              "@{protected=$bundleAcl.AreAccessRulesProtected; "
              "inherited=@($bundleAcl.Access | Where-Object { $_.IsInherited }).Count} | ConvertTo-Json -Compress")
    process = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                             capture_output=True, text=True, check=True)
    acl = json.loads(process.stdout)
    assert acl["protected"] is False
    assert acl["inherited"] > 0


def test_failed_build_removes_only_owned_staging_and_preserves_inputs(tmp_path, monkeypatch):
    directory = copy_inputs(tmp_path / "failed-build")
    before = {path: path.read_bytes() for path in directory.iterdir()}
    def failed_write(*args, **kwargs):
        raise OSError("Simulated write failure")
    monkeypatch.setattr(pd.DataFrame, "to_csv", failed_write)
    with pytest.raises(OSError, match="Simulated write failure"):
        correction.generate_bundle(directory)
    assert not list((directory / "corrections").glob(".build-*"))
    assert not (directory / "corrections/current.json").exists()
    assert all(path.read_bytes() == content for path, content in before.items())
