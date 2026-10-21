"""Generate a reproducible, synthetic design-day sensor CSV (no heat writes).

Run from the repository root:
    .venv/Scripts/python.exe simulate_sensors.py

Provisional noise, offsets and fault settings live in config/sensor_simulation.json.
See docs/sensor_simulator.md for the formulas and verification commands.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import tempfile
from dataclasses import dataclass, field, fields, replace
from datetime import time
from pathlib import Path

import numpy as np
import pandas as pd

from heat_model.heat import HOURS, TZ, design_weather, heat_at

ROOT = Path(__file__).resolve().parent
SITES_PATH = ROOT / "data" / "sensor_links.csv"
DEFAULT_CONFIG = ROOT / "config" / "sensor_simulation.json"
DEFAULT_OUTPUT = ROOT / "data" / "sensors_stream.csv"
SENSOR_COLUMNS = [
    "sensor_id", "link_id", "timestamp", "air_temp_c", "rh_pct",
    "surface_temp_c", "source",
]


@dataclass(frozen=True)
class SimulationConfig:
    """Provisional defaults; JSON fields and CLI seed can override them."""

    seed: int = 20260906
    offset_overrides_c: dict[str, float] = field(default_factory=lambda: {"S08": 0.5})
    air_noise_c: float = 0.3
    rh_noise_pct: float = 2.0
    surface_noise_c: float = 1.0
    silent_sensor: str = "S02"
    silent_start: str = "12:00"
    silent_minutes: int = 30
    spike_sensor: str = "S01"
    spike_time: str = "13:05"
    spike_delta_c: float = 8.0


def load_config(path: Path = DEFAULT_CONFIG) -> SimulationConfig:
    """Reject misspelled settings instead of silently ignoring them."""
    values = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(values, dict):
        raise ValueError("Simulation config must be a JSON object")
    unknown = values.keys() - {f.name for f in fields(SimulationConfig)}
    if unknown:
        raise ValueError(f"Unknown config settings: {sorted(unknown)}")
    return SimulationConfig(**values)


def _finite_number(value, label: str, *, nonnegative: bool = False) -> None:
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value) or (nonnegative and value < 0)):
        raise ValueError(f"{label} must be a finite {'nonnegative ' if nonnegative else ''}number")


def _clock_minutes(value: str) -> int:
    try:
        clock = time.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid fault time {value!r}; use HH:MM") from exc
    if (clock.tzinfo is not None or clock.second or clock.microsecond
            or clock.minute % 5 or not 7 * 60 <= clock.hour * 60 + clock.minute <= 19 * 60):
        raise ValueError("Fault times must be local five-minute steps from 07:00 to 19:00")
    return clock.hour * 60 + clock.minute


def _validate_config(config: SimulationConfig, sensor_ids: set[str]) -> None:
    if type(config.seed) is not int or config.seed < 0:
        raise ValueError("seed must be a nonnegative integer")
    for name in ("air_noise_c", "rh_noise_pct", "surface_noise_c"):
        _finite_number(getattr(config, name), name, nonnegative=True)
    _finite_number(config.spike_delta_c, "spike_delta_c", nonnegative=True)
    if not isinstance(config.offset_overrides_c, dict):
        raise ValueError("offset_overrides_c must map sensor IDs to offsets")
    for sensor_id, offset in config.offset_overrides_c.items():
        if sensor_id not in sensor_ids:
            raise ValueError(f"Unknown sensor in offset override: {sensor_id}")
        _finite_number(offset, f"Offset for {sensor_id}")
    if config.silent_sensor not in sensor_ids or config.spike_sensor not in sensor_ids:
        raise ValueError("Fault sensor IDs must exist in sensor_links.csv")
    if config.silent_sensor == config.spike_sensor:
        raise ValueError("Use different sensors for the silence and spike faults")
    start = _clock_minutes(config.silent_start)
    _clock_minutes(config.spike_time)
    if (type(config.silent_minutes) is not int or config.silent_minutes <= 0
            or config.silent_minutes % 5 or start + config.silent_minutes > 19 * 60):
        raise ValueError("silent_minutes must be a positive multiple of 5 ending by 19:00")


def generate_readings(config: SimulationConfig, *, faults: bool = True) -> pd.DataFrame:
    """Read shared model inputs and return readings without writing any files.

    Weather is linearly interpolated; shade uses the reading's whole local hour.
    All noise is generated before faults, so --no-faults preserves other readings.
    """
    sites = pd.read_csv(SITES_PATH)
    required = {"sensor_id", "link_id", "offset_c"}
    if not required.issubset(sites.columns):
        raise ValueError(f"Sensor sites need columns {sorted(required)}")
    if (len(sites) != 8 or sites[list(required)].isna().any().any()
            or sites.sensor_id.duplicated().any() or sites.link_id.duplicated().any()):
        raise ValueError("Expected eight unique sensors on eight distinct links, without missing values")
    sites = sites.sort_values("sensor_id").reset_index(drop=True)
    sites["offset_c"] = pd.to_numeric(sites.offset_c, errors="raise")
    if not np.isfinite(sites.offset_c).all():
        raise ValueError("Site offsets must be finite")
    _validate_config(config, set(sites.sensor_id))

    weather = design_weather().sort_index()
    if (list(weather.index) != list(HOURS) or weather.date.isna().any()
            or weather.date.nunique() != 1):
        raise ValueError("Design weather must contain one date with hours 07..19 exactly once")
    weather_values = weather[["air_temp_c", "rh_pct", "sw_wm2"]].to_numpy(dtype=float)
    if not np.isfinite(weather_values).all():
        raise ValueError("Design weather must have finite air temperature, humidity and sunlight")
    if ((weather.rh_pct < 0) | (weather.rh_pct > 100)).any() or (weather.sw_wm2 < 0).any():
        raise ValueError("Weather humidity must be 0..100 and sunlight nonnegative")
    date = pd.Timestamp(weather.date.iloc[0]).date().isoformat()
    times = pd.date_range(f"{date} 07:00", f"{date} 19:00", freq="5min", tz=TZ)
    fractional_hours = times.hour + times.minute / 60
    air, humidity, sun = (
        np.interp(fractional_hours, weather.index, weather[col])
        for col in ("air_temp_c", "rh_pct", "sw_wm2")
    )

    # Use Person 1's public reader; never regenerate or rewrite its heat output.
    model = {}
    for hour in HOURS:
        links = heat_at(hour)
        if links.link_id.duplicated().any():
            raise ValueError("Heat model link IDs must be unique")
        unknown = set(sites.link_id) - set(links.link_id)
        if unknown:
            raise ValueError(f"Sensor links missing from heat model: {sorted(unknown)}")
        selected = links.set_index("link_id").loc[sites.link_id, ["shade", "albedo"]]
        values = selected.to_numpy(dtype=float)
        if not np.isfinite(values).all() or ((values < 0) | (values > 1)).any():
            raise ValueError("Sensor link shade and albedo must be finite values in 0..1")
        model[hour] = selected

    rng = np.random.default_rng(config.seed)
    frames = []
    for site in sites.itertuples(index=False):
        offset = config.offset_overrides_c.get(site.sensor_id, site.offset_c)
        shade = np.array([model[h].loc[site.link_id, "shade"] for h in times.hour])
        albedo = np.array([model[h].loc[site.link_id, "albedo"] for h in times.hour])
        sensor_air = air + offset + rng.uniform(-config.air_noise_c, config.air_noise_c, len(times))
        sensor_rh = np.clip(humidity + rng.uniform(-config.rh_noise_pct, config.rh_noise_pct, len(times)), 0, 100)
        surface = (sensor_air + (1 - shade) * sun / 1000 * 25 * (1 - albedo)
                   + rng.uniform(-config.surface_noise_c, config.surface_noise_c, len(times)))
        if faults and site.sensor_id == config.spike_sensor:
            spike = times.hour * 60 + times.minute == _clock_minutes(config.spike_time)
            sensor_air[spike] += config.spike_delta_c
            surface[spike] += config.spike_delta_c
        frame = pd.DataFrame({
            "sensor_id": site.sensor_id, "link_id": site.link_id,
            "timestamp": [t.isoformat() for t in times],
            "air_temp_c": sensor_air, "rh_pct": sensor_rh,
            "surface_temp_c": surface, "source": "simulated",
        })
        if faults and site.sensor_id == config.silent_sensor:
            start = _clock_minutes(config.silent_start)
            minutes = times.hour * 60 + times.minute
            frame = frame.loc[~((minutes >= start) & (minutes < start + config.silent_minutes))]
        frames.append(frame)
    readings = pd.concat(frames, ignore_index=True)
    readings[["air_temp_c", "rh_pct", "surface_temp_c"]] = readings[
        ["air_temp_c", "rh_pct", "surface_temp_c"]
    ].round(3)
    return readings.sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)[SENSOR_COLUMNS]


def write_readings(readings: pd.DataFrame, output: Path) -> None:
    """Atomically write a sensor CSV; refuse to overwrite other CSV contracts."""
    output = Path(output).resolve()
    if output.suffix.lower() != ".csv":
        raise ValueError("Output must be a .csv file")
    if output.exists():
        with output.open(encoding="utf-8", newline="") as existing:
            if next(csv.reader(existing), None) != SENSOR_COLUMNS:
                raise ValueError(f"Refusing to overwrite a non-sensor CSV: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", newline="", suffix=".csv",
                                     dir=output.parent, delete=False) as staging:
        staging_path = Path(staging.name)
    try:
        readings.to_csv(staging_path, index=False, float_format="%.3f", lineterminator="\n")
        os.replace(staging_path, output)
    finally:
        staging_path.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="JSON simulation settings")
    parser.add_argument("--seed", type=int, help="Override the config's deterministic random seed")
    parser.add_argument("--no-faults", action="store_true", help="Generate all 1,160 scheduled readings")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="Sensor CSV output path")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
        if args.seed is not None:
            config = replace(config, seed=args.seed)
        readings = generate_readings(config, faults=not args.no_faults)
        write_readings(readings, args.output)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.error(str(exc))
    print("Simulated data only; offsets, noise and faults are provisional assumptions.")
    print(f"Seed: {config.seed}; {len(readings)} readings from {readings.sensor_id.nunique()} sensors")
    print(f"Local timestamps: {readings.timestamp.min()} to {readings.timestamp.max()}")
    if not args.no_faults:
        print(f"Silence: {config.silent_sensor} from {config.silent_start} for {config.silent_minutes} min (end excluded)")
        print(f"Spike: {config.spike_sensor} at {config.spike_time}, +{config.spike_delta_c:g} C to air and surface")
    else:
        print("Faults disabled")
    print("Readings per sensor: " + ", ".join(f"{k}={v}" for k, v in readings.groupby("sensor_id").size().items()))
    print(f"Wrote {args.output.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
