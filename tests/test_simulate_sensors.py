"""Sensor contract, physics, faults and read-only teammate integration checks."""

import json
from dataclasses import replace
from pathlib import Path
import runpy
import sys

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import simulate_sensors as simulator


@pytest.fixture
def model(monkeypatch):
    """Known weather/shade inputs, while retaining all eight actual sensor sites."""
    sites = pd.read_csv(simulator.SITES_PATH)
    weather = pd.DataFrame({
        "hour": list(range(7, 20)), "date": "2026-09-06",
        "air_temp_c": np.arange(7, 20) + 20.0,
        "rh_pct": 80.0 - np.arange(7, 20),
        "sw_wm2": np.arange(7, 20) * 50.0,
    }).set_index("hour")

    def heat(hour):
        return pd.DataFrame({
            "link_id": sites.link_id,
            "shade": np.where(sites.sensor_id == "S05", 1.0, (hour - 7) / 20),
            "albedo": np.where(sites.sensor_id == "S05", 0.3, 0.1),
        })

    monkeypatch.setattr(simulator, "design_weather", lambda: weather.copy())
    monkeypatch.setattr(simulator, "heat_at", heat)
    return sites, weather, heat


def no_noise():
    return replace(simulator.load_config(), air_noise_c=0, rh_noise_pct=0, surface_noise_c=0)


def reading(frame, sensor, clock):
    return frame.loc[(frame.sensor_id == sensor) & frame.timestamp.str.contains(f"T{clock}:")].iloc[0]


def test_daily_contract_and_real_site_mapping(model):
    sites, _, _ = model
    result = simulator.generate_readings(simulator.load_config(), faults=False)
    assert list(result.columns) == simulator.SENSOR_COLUMNS
    assert len(result) == 1160
    assert result.groupby("sensor_id").size().eq(145).all()
    assert not result.duplicated(["sensor_id", "timestamp"]).any()
    assert result.source.eq("simulated").all()
    assert np.isfinite(result[["air_temp_c", "rh_pct", "surface_temp_c"]]).all().all()
    assert result.rh_pct.between(0, 100).all()
    assert dict(result.groupby("sensor_id").link_id.first()) == dict(zip(sites.sensor_id, sites.link_id))
    timestamps = pd.to_datetime(result.timestamp)
    assert timestamps.min().isoformat() == "2026-09-06T07:00:00+08:00"
    assert timestamps.max().isoformat() == "2026-09-06T19:00:00+08:00"
    assert result.timestamp.str.endswith("+08:00").all()
    for _, group in result.groupby("sensor_id"):
        assert pd.to_datetime(group.timestamp).diff().dropna().eq(pd.Timedelta(minutes=5)).all()


def test_formula_interpolation_and_hourly_shade(model):
    result = simulator.generate_readings(no_noise(), faults=False)
    row = reading(result, "S01", "13:30")
    # At 13:30: interpolated weather = 33.5 C, RH 66.5%, sunlight 675 W/m2.
    # Use hour 13's shade (0.3), rather than interpolating it toward hour 14.
    assert row.air_temp_c == 35.0  # Site offset +1.5.
    assert row.rh_pct == 66.5
    assert row.surface_temp_c == pytest.approx(35 + 0.7 * 675 / 1000 * 25 * 0.9, abs=0.0005)
    next_hour = reading(result, "S01", "14:00")
    assert next_hour.surface_temp_c == pytest.approx(35.5 + 0.65 * 700 / 1000 * 25 * 0.9, abs=0.00051)
    covered = result.loc[result.sensor_id == "S05"]
    assert (covered.air_temp_c == covered.surface_temp_c).all()


def test_noise_bounds_and_determinism(model):
    config = simulator.load_config()
    result = simulator.generate_readings(config, faults=False)
    pd.testing.assert_frame_equal(result, simulator.generate_readings(config, faults=False))
    other = simulator.generate_readings(replace(config, seed=config.seed + 1), faults=False)
    assert not result.air_temp_c.equals(other.air_temp_c)
    expected = simulator.generate_readings(no_noise(), faults=False)
    air_noise = result.air_temp_c - expected.air_temp_c
    assert air_noise.abs().max() <= config.air_noise_c + 0.001
    assert (result.rh_pct - expected.rh_pct).abs().max() <= config.rh_noise_pct + 0.001
    # Surface includes the noisy sensor air, plus independent surface noise.
    surface_noise = result.surface_temp_c - expected.surface_temp_c - air_noise
    assert surface_noise.abs().max() <= config.surface_noise_c + 0.002


def test_humidity_is_clipped_to_physical_bounds(model, monkeypatch):
    _, weather, _ = model
    for humidity in (0.0, 100.0):
        weather["rh_pct"] = humidity
        monkeypatch.setattr(simulator, "design_weather", lambda: weather.copy())
        result = simulator.generate_readings(simulator.load_config(), faults=False)
        assert result.rh_pct.between(0, 100).all()
        assert result.rh_pct.eq(humidity).any()


def test_faults_remove_six_readings_and_change_exactly_one_sample(model):
    config = simulator.load_config()
    baseline = simulator.generate_readings(config, faults=False).set_index(["sensor_id", "timestamp"])
    faulty = simulator.generate_readings(config).set_index(["sensor_id", "timestamp"])
    assert len(faulty) == 1154
    assert faulty.groupby(level="sensor_id").size()["S02"] == 139
    missing = baseline.index.difference(faulty.index)
    assert list(missing) == [("S02", f"2026-09-06T12:{m:02d}:00+08:00") for m in range(0, 30, 5)]
    assert ("S02", "2026-09-06T12:30:00+08:00") in faulty.index
    expected = baseline.loc[faulty.index].copy()
    spike = ("S01", "2026-09-06T13:05:00+08:00")
    expected.loc[spike, ["air_temp_c", "surface_temp_c"]] += 8
    pd.testing.assert_frame_equal(faulty, expected)


def test_offsets_and_fault_choices_are_configurable(model):
    config = replace(no_noise(), offset_overrides_c={"S08": -2}, silent_sensor="S04",
                     silent_start="10:00", spike_sensor="S03", spike_time="14:10", spike_delta_c=4)
    result = simulator.generate_readings(config)
    assert reading(result, "S08", "13:00").air_temp_c == 31
    assert result.groupby("sensor_id").size()["S04"] == 139
    assert reading(result, "S03", "14:10").air_temp_c == pytest.approx(37.167)


@pytest.mark.parametrize("changes", [
    {"seed": -1}, {"seed": True}, {"air_noise_c": -0.1}, {"rh_noise_pct": float("nan")},
    {"offset_overrides_c": {"unknown": 1}}, {"offset_overrides_c": {"S08": float("inf")}},
    {"silent_sensor": "S99"}, {"spike_sensor": "S02"}, {"silent_minutes": 31},
    {"silent_start": "18:45"}, {"spike_time": "13:02"}, {"spike_time": "13:05:30"},
    {"spike_delta_c": -1},
])
def test_invalid_config_is_rejected(model, changes):
    with pytest.raises(ValueError):
        simulator.generate_readings(replace(simulator.load_config(), **changes))


def test_unknown_json_setting_is_rejected(tmp_path):
    path = tmp_path / "settings.json"
    path.write_text(json.dumps({"seeeed": 42}), encoding="utf-8")
    with pytest.raises(ValueError, match="Unknown config"):
        simulator.load_config(path)


def test_missing_link_is_rejected(model, monkeypatch):
    _, _, heat = model
    monkeypatch.setattr(simulator, "heat_at", lambda h: heat(h).iloc[1:])
    with pytest.raises(ValueError, match="missing from heat model"):
        simulator.generate_readings(simulator.load_config())


def test_duplicate_sites_are_rejected(model, monkeypatch, tmp_path):
    sites, _, _ = model
    sites.loc[1, "sensor_id"] = sites.loc[0, "sensor_id"]
    path = tmp_path / "sites.csv"
    sites.to_csv(path, index=False)
    monkeypatch.setattr(simulator, "SITES_PATH", path)
    with pytest.raises(ValueError, match="eight unique"):
        simulator.generate_readings(simulator.load_config())


def test_missing_weather_hour_is_rejected(model, monkeypatch):
    _, weather, _ = model
    monkeypatch.setattr(simulator, "design_weather", lambda: weather.drop(index=13))
    with pytest.raises(ValueError, match="hours 07..19"):
        simulator.generate_readings(simulator.load_config())


def test_cli_writes_repeatable_csv_and_accepts_overrides(model, tmp_path, capsys):
    output = tmp_path / "stream.csv"
    assert simulator.main(["--output", str(output)]) == 0
    first = output.read_bytes()
    assert simulator.main(["--output", str(output)]) == 0
    assert output.read_bytes() == first
    assert pd.read_csv(output).shape == (1154, 7)
    assert simulator.main(["--no-faults", "--seed", "123", "--output", str(output)]) == 0
    assert len(pd.read_csv(output)) == 1160
    assert "Simulated data only" in capsys.readouterr().out


def test_writer_refuses_to_overwrite_unrelated_csv(model, tmp_path):
    output = tmp_path / "weather.csv"
    original = b"hour,air_temp_c\n13,34\n"
    output.write_bytes(original)
    with pytest.raises(ValueError, match="non-sensor CSV"):
        simulator.write_readings(simulator.generate_readings(no_noise()), output)
    assert output.read_bytes() == original


def test_person2_latest_sensor_adapter(model, tmp_path, monkeypatch):
    import engine

    monkeypatch.setattr(engine, "DATA_DIR", tmp_path)
    result = simulator.generate_readings(simulator.load_config())
    simulator.write_readings(result, tmp_path / "sensors_stream.csv")
    latest = engine.latest_sensors()
    assert list(latest.columns) == simulator.SENSOR_COLUMNS
    assert len(latest) == 8
    assert latest.timestamp.eq("2026-09-06T19:00:00+08:00").all()


def test_real_data_and_correction_reader_compatibility(tmp_path, monkeypatch):
    # Exercise Person 1's public reader with actual prepared data, without running
    # main() or writing corrected heat. This also protects all shared input bytes.
    protected = [ROOT / "engine.py", *(ROOT / "heat_model").glob("*.py"),
                 *(ROOT / "data").glob("*.geojson"),
                 *(p for p in (ROOT / "data").glob("*.csv") if p.name != "sensors_stream.csv")]
    before = {p: p.read_bytes() for p in protected}
    result = simulator.generate_readings(simulator.load_config())
    assert len(result) == 1154
    output = tmp_path / "sensors_stream.csv"
    simulator.write_readings(result, output)
    monkeypatch.syspath_prepend(str(ROOT / "heat_model"))
    correction = runpy.run_path(str(ROOT / "heat_model" / "sensor_correction.py"))
    loaded = correction["load_readings"](output)
    offsets = correction["sensor_offsets"](loaded, simulator.design_weather().air_temp_c)
    assert len(offsets) == 8 * 13
    assert set(offsets.sensor_id) == {f"S{i:02d}" for i in range(1, 9)}
    assert np.isfinite(offsets.offset).all()
    for path, original in before.items():
        assert path.read_bytes() == original, f"Shared input changed: {path}"
