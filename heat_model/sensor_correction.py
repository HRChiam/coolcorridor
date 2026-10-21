"""Reproducible offline correction into immutable, separately versioned artifacts.

Retains median nearest-hour windows and nearest-sensor linear150m influence.
Detected outliers use the documented Dashboard residual detector; injected fault
schedules never decide exclusion. Frozen network and raw sensor CSV stay intact.
Run: python -B -m heat_model.sensor_correction --activate
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
from uuid import uuid4

import geopandas as gpd
import numpy as np
import pandas as pd

try:
    from .effective import (DATA, DESIGN_DATE, HOURS, SCHEMA_VERSION, TZ,
                            clear_effective_cache, design_weather, design_weather_hash,
                            load_effective_links, sha256_file, validate_bundle)
except ImportError:
    from effective import (DATA, DESIGN_DATE, HOURS, SCHEMA_VERSION, TZ,
                           clear_effective_cache, design_weather, design_weather_hash,
                           load_effective_links, sha256_file, validate_bundle)

RADIUS_M = 150
AIR_ANOMALY_THRESHOLD_C = 3.
PARAMETERS = {
    "radius_m": RADIUS_M, "distance": "target link geometry to sensor link midpoint in local UTM",
    "spatial_weight": "max(0,1-distance_m/150); nearest available sensor only",
    "hour_window": "[hour-30min,hour+30min), Asia/Kuala_Lumpur",
    "aggregation": "median, minimum one accepted sample per sensor-hour",
    "outlier_policy": "existing dashboard causal residual departure detector",
    "anomaly_threshold_c": AIR_ANOMALY_THRESHOLD_C,
    "anomaly_baseline": "previous30min air-minus-interpolated-weather median, minimum3 readings",
    "no_sensor_hour": "zero correction; explicitly labelled baseline fallback",
    "heat_rounding_decimals": 2,
    "validation": "previous-hour correction against current-hour median air offset",
}


def load_sites(data_dir=DATA, links=None):
    directory = Path(data_dir)
    sensors = pd.read_csv(directory / "sensor_links.csv")
    required = {"sensor_id", "link_id", "lat", "lon"}
    if (not required.issubset(sensors.columns) or len(sensors) != 8
            or sensors[list(required)].isna().any().any()
            or sensors.sensor_id.duplicated().any() or sensors.link_id.duplicated().any()):
        raise ValueError("Correction requires eight unique sensor sites and sensor/link mappings")
    for name, low, high in (("lat", -90, 90), ("lon", -180, 180)):
        sensors[name] = pd.to_numeric(sensors[name], errors="raise")
        if not sensors[name].between(low, high).all():
            raise ValueError("Sensor coordinates must be finite EPSG:4326 longitude/latitude")
    links = gpd.read_file(directory / "links.geojson") if links is None else links
    if not sensors.link_id.isin(links.link_id).all():
        raise ValueError("Sensor mapping contains a link absent from the frozen network")
    return sensors.sort_values("sensor_id").reset_index(drop=True)


def _detect_air_anomalies(readings, model_air):
    """Same causal >3C / previous30min / min3 rule as the Dashboard."""
    parts = []
    for _, group in readings.groupby("sensor_id", sort=True):
        group = group.sort_values("timestamp").copy()
        clock = group.timestamp.dt.hour + group.timestamp.dt.minute / 60
        group["weather_air_c"] = np.interp(clock, model_air.index, model_air.to_numpy())
        residual = pd.Series((group.air_temp_c - group.weather_air_c).to_numpy(),
                             index=pd.DatetimeIndex(group.timestamp))
        baseline = residual.rolling("30min", closed="left", min_periods=3).median()
        group["departure_c"] = residual.to_numpy() - baseline.to_numpy()
        group["anomaly"] = group.departure_c.abs() > AIR_ANOMALY_THRESHOLD_C
        parts.append(group)
    if not parts:
        result = readings.copy()
        for name in ("weather_air_c", "departure_c"):
            result[name] = pd.Series(dtype=float)
        result["anomaly"] = pd.Series(dtype=bool)
        return result
    return pd.concat(parts, ignore_index=True).sort_values(["timestamp", "sensor_id"]).reset_index(drop=True)


def load_readings(path, *, data_dir=DATA, sensors=None, model_air=None):
    readings = pd.read_csv(path)
    required = {"sensor_id", "link_id", "timestamp", "air_temp_c", "source"}
    if not required.issubset(readings.columns):
        raise ValueError("Sensor readings are missing the correction input fields")
    sensors = load_sites(data_dir) if sensors is None else sensors
    if (not readings.source.eq("simulated").all()
            or not readings.sensor_id.map(sensors.set_index("sensor_id").link_id).eq(readings.link_id).all()):
        raise ValueError("Readings must be simulated and match valid sensor/link mappings")
    if not readings.timestamp.astype(str).str.contains(r"(?:[+-]\d{2}:\d{2}|Z)$", regex=True).all():
        raise ValueError("Sensor timestamps must be timezone-aware")
    readings["timestamp"] = pd.to_datetime(readings.timestamp, utc=True, errors="raise").dt.tz_convert(TZ)
    if readings.timestamp.isna().any() or readings.duplicated(["sensor_id", "timestamp"]).any():
        raise ValueError("Sensor timestamps must be valid and unique per sensor")
    readings["air_temp_c"] = pd.to_numeric(readings.air_temp_c, errors="raise")
    if not np.isfinite(readings.air_temp_c).all():
        raise ValueError("Sensor air temperatures must be finite")
    count = len(readings)
    readings = readings.loc[readings.timestamp.dt.strftime("%Y-%m-%d").eq(DESIGN_DATE)].copy()
    start, end = (pd.Timestamp(f"{DESIGN_DATE} {clock}", tz=TZ) for clock in ("07:00", "19:00"))
    readings = readings.loc[readings.timestamp.between(start, end)].copy()
    if (readings.timestamp.dt.minute.mod(5).ne(0) | readings.timestamp.dt.second.ne(0)
            | readings.timestamp.dt.microsecond.ne(0) | readings.timestamp.dt.nanosecond.ne(0)).any():
        raise ValueError("Sensor timestamps must follow the five-minute design-day schedule")
    model_air = design_weather(data_dir).air_temp_c if model_air is None else model_air
    readings = _detect_air_anomalies(readings, model_air)
    readings["hour"] = (readings.timestamp + pd.Timedelta(minutes=30)).dt.floor("h").dt.hour
    readings.attrs["ignored_outside_design_window"] = count - len(readings)
    return readings


def sensor_offsets(readings, model_air):
    """Median accepted air minus design weather; one sample is sufficient."""
    accepted = readings.loc[~readings.anomaly] if "anomaly" in readings else readings
    grouped = accepted.groupby(["sensor_id", "link_id", "hour"]).air_temp_c.agg(["median", "size"]).reset_index()
    grouped = grouped.rename(columns={"median": "air_temp_c", "size": "accepted_samples"})
    grouped = grouped.loc[grouped.hour.isin(model_air.index)].copy()
    grouped["model_air_c"] = grouped.hour.map(model_air)
    grouped["offset"] = grouped.air_temp_c - grouped.model_air_c
    return grouped


def sensor_weights(links, sensors):
    if links.crs is None or links.geometry.isna().any() or links.geometry.is_empty.any():
        raise ValueError("Correction requires valid georeferenced walking geometries")
    projected = links.to_crs(links.estimate_utm_crs()).set_index("link_id")
    points = projected.geometry.loc[sensors.link_id].interpolate(.5, normalized=True)
    distances = np.column_stack([projected.geometry.distance(point).to_numpy() for point in points])
    return pd.DataFrame(np.clip(1 - distances / RADIUS_M, 0, None),
                        index=projected.index, columns=sensors.sensor_id.to_numpy())


def correction(weights, offsets):
    offsets = offsets.dropna()
    if offsets.empty:
        return pd.Series(0., index=weights.index)
    matrix = weights[offsets.index].to_numpy()
    nearest = matrix.argmax(axis=1)
    return pd.Series(matrix.max(axis=1) * offsets.to_numpy()[nearest], index=weights.index)


def validate(weights, offsets, sensors):
    """Previous-hour calibration versus current-hour simulated AIR offset."""
    by_hour = offsets.pivot(index="hour", columns="sensor_id", values="offset")
    sensor_links = sensors.set_index("sensor_id").link_id
    rows = []
    for hour in by_hour.index:
        if hour - 1 not in by_hour.index:
            continue
        previous = by_hour.loc[hour - 1].dropna()
        if previous.empty:
            continue
        corr = correction(weights, previous)
        for sensor_id, offset in by_hour.loc[hour].dropna().items():
            link_id = sensor_links[sensor_id]
            applied = float(corr[link_id])
            rows.append((sensor_id, link_id, int(hour), float(offset), applied,
                         abs(float(offset)), abs(float(offset) - applied), "simulated"))
    return pd.DataFrame(rows, columns=["sensor_id", "link_id", "hour", "air_offset_c",
                                       "previous_hour_correction_c", "error_before", "error_after", "source"])


def _inputs(directory):
    inputs = {name: {"sha256": sha256_file(directory / name)} for name in
              ("links.geojson", "weather.csv", "sensor_links.csv", "sensors_stream.csv")}
    inputs["weather.csv"]["design_rows_sha256"] = design_weather_hash(directory)
    inputs["../config/sensor_simulation.json"] = {"sha256": sha256_file(directory / "../config/sensor_simulation.json")}
    return inputs


def _activate(directory, version_dir):
    validate_bundle(directory, version_dir)
    pointer = directory / "corrections/current.json"
    payload = {"schema_version": SCHEMA_VERSION, "version": version_dir.name,
               "manifest_sha256": sha256_file(version_dir / "manifest.json")}
    if pointer.exists():
        if json.loads(pointer.read_text(encoding="utf-8")) != payload:
            raise FileExistsError("Active pointer differs; review and explicitly archive/change it before activating another version")
        return
    with pointer.open("x", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, indent=2) + "\n")
    clear_effective_cache()
    load_effective_links(directory)


def generate_bundle(data_dir=DATA, *, activate=False):
    """Immutable derived version: never replaces canonical files or another pointer."""
    directory = Path(data_dir).resolve()
    inputs = _inputs(directory)
    numerical_inputs = {name: (meta.get("design_rows_sha256") if name == "weather.csv" else meta["sha256"])
                        for name, meta in inputs.items()}
    implementation = {name: sha256_file(Path(__file__).with_name(name)) for name in
                      ("sensor_correction.py", "effective.py", "heat.py")}
    identity = json.dumps({"schema": SCHEMA_VERSION, "design_date": DESIGN_DATE,
                           "inputs": numerical_inputs, "parameters": PARAMETERS,
                           "implementation": implementation}, sort_keys=True)
    version = "v1-20260906-" + hashlib.sha256(identity.encode()).hexdigest()[:16]
    versions, version_dir = directory / "corrections", directory / "corrections" / version
    if version_dir.exists():
        manifest = json.loads((version_dir / "manifest.json").read_text(encoding="utf-8"))
        if manifest.get("output_version") != version:
            raise ValueError("Existing version is inconsistent; refusing to replace it")
        for name, digest in manifest.get("outputs", {}).items():
            if sha256_file(version_dir / name) != digest:
                raise ValueError("Existing version is damaged; refusing to overwrite it")
        validate_bundle(directory, version_dir)
        if activate:
            _activate(directory, version_dir)
        return version_dir
    links = gpd.read_file(directory / "links.geojson")
    if (links.empty or links.link_id.isna().any() or links.link_id.duplicated().any()
            or any(c.startswith("heat_corr_h") for c in links)):
        raise ValueError("Correction input must be the frozen unique baseline network")
    weather = design_weather(directory)
    try:
        from .heat import heat_score
    except ImportError:
        from heat import heat_score
    for hour in HOURS:
        column = f"heat_h{hour:02d}"
        if column not in links or not np.isfinite(pd.to_numeric(links[column], errors="raise")).all():
            raise ValueError(f"Complete finite baseline heat is required: {column}")
        shade_column = f"shade_h{hour:02d}"
        if shade_column not in links or "albedo" not in links:
            raise ValueError("Frozen heat baseline needs matching shade and surface albedo")
        row = weather.loc[hour]
        expected = heat_score(row.air_temp_c, links[shade_column], row.sw_wm2, links.albedo, row.wind_ms)
        if not np.allclose(links[column], expected, rtol=0, atol=.00501):
            raise ValueError("Frozen baseline heat disagrees with selected design weather; no correction was generated")
    sensors = load_sites(directory, links)
    readings = load_readings(directory / "sensors_stream.csv", data_dir=directory,
                             sensors=sensors, model_air=weather.air_temp_c)
    offsets = sensor_offsets(readings, weather.air_temp_c)
    weights = sensor_weights(links, sensors)
    frames, coverage = [], {}
    for hour in HOURS:
        at_hour = offsets.loc[offsets.hour == hour].set_index("sensor_id").offset
        coverage[str(hour)] = len(at_hour)
        adjustment = correction(weights, at_hour).reindex(links.link_id).to_numpy()
        baseline = links[f"heat_h{hour:02d}"].to_numpy(dtype=float)
        heat = np.round(baseline + adjustment, 2)
        frames.append(pd.DataFrame({"link_id": links.link_id, "hour": hour, "heat_model": baseline,
                                    "correction_c": np.round(heat - baseline, 8), "heat": heat}))
    corrected = pd.concat(frames, ignore_index=True)
    validation = validate(weights, offsets, sensors)
    rejected = readings.loc[readings.anomaly].copy()
    mean = lambda column: float(validation[column].mean()) if not validation.empty else None
    manifest = {
        "schema_version": SCHEMA_VERSION, "output_version": version,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(), "design_date": DESIGN_DATE,
        "timezone": TZ, "sensor_source": "simulated", "heat_units": "Celsius-labelled modelled heat index",
        "inputs": inputs, "parameters": PARAMETERS, "hours": list(HOURS), "link_count": len(links),
        "implementation": implementation,
        "row_count": len(corrected), "sensor_count": len(sensors), "sensor_hours_per_hour": coverage,
        "baseline_fallback_hours": [int(h) for h, count in coverage.items() if count == 0],
        "reading_count_design_window": len(readings), "rejected_anomaly_samples": len(rejected),
        "ignored_outside_design_window": readings.attrs.get("ignored_outside_design_window", 0),
        "simulation_seed": json.loads((directory / "../config/sensor_simulation.json").read_text(encoding="utf-8")).get("seed"),
        "validation": {"method": "previous-hour calibration versus next-hour median simulated air offset",
                       "sensor_hours": len(validation), "mean_absolute_error_before_c": mean("error_before"),
                       "mean_absolute_error_after_c": mean("error_after"),
                       "limitation": "Synthetic demonstration, not real-world accuracy; adjacent centred windows are disjoint"},
    }
    versions.mkdir(parents=True, exist_ok=True)
    # TemporaryDirectory uses mode0700; on Python3.13/Windows that installs a
    # protected creator-only ACL which survives rename and hides the bundle from
    # the app's normal user. A regular mkdir inherits the workspace's normal ACL.
    staging = (versions / (".build-" + uuid4().hex)).resolve()
    if staging.parent != versions.resolve():
        raise ValueError("Staging directory escaped its intended root")
    staging.mkdir()
    try:
        frames = {"corrected_heat.csv": corrected, "sensor_validation.csv": validation,
                  "sensor_offsets.csv": offsets, "rejected_samples.csv": rejected}
        for name, frame in frames.items():
            frame.to_csv(staging / name, index=False, float_format="%.8f")
        manifest["outputs"] = {name: sha256_file(staging / name) for name in frames}
        (staging / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        staging.rename(version_dir)
    finally:
        # Delete only our newly-created, unused staging directory after a failed
        # build. The successfully renamed immutable version is always retained.
        if staging.exists():
            if (staging.resolve().parent != versions.resolve()
                    or not staging.name.startswith(".build-") or staging.is_symlink()):
                raise ValueError("Refusing cleanup outside the owned correction staging directory")
            shutil.rmtree(staging)
    if activate:
        _activate(directory, version_dir)
    return version_dir


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=DATA)
    parser.add_argument("--activate", action="store_true", help="Create a new active pointer; never replace a different pointer")
    args = parser.parse_args()
    version = generate_bundle(args.data_dir, activate=args.activate)
    manifest = json.loads((version / "manifest.json").read_text(encoding="utf-8"))
    print(f"Created/verified {version}")
    print(f"{manifest['link_count']} links x13 hours; {manifest['rejected_anomaly_samples']} detected outlier excluded; raw readings unchanged")
    print(json.dumps(manifest["validation"], indent=2))
    print("ACTIVE" if args.activate else "Not activated; use --activate after reviewing the bundle")


if __name__ == "__main__":
    main()
