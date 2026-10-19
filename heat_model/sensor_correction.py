"""Heat model step 6: correct the heat score with the (simulated) sensor readings.

A sensor's offset at an hour = the median air temperature it read within ±30 min
of the hour, minus the model's air temperature (Open-Meteo design day). The median
ignores a sensor that spikes; a silent sensor simply has no offset that hour.
Links within RADIUS_M of a sensor are nudged by its offset, weighted by distance:
  correction = w * offset,  w = 1 - d / RADIUS_M,  from the nearest sensor only
(nearest only, so e.g. the covered-walkway sensor doesn't pull the exposed LRT
sensor's link 62 m away, which reads the opposite way). The heat score moves
one-for-one with air temperature, so corrected heat = heat + correction.

Validation (a results number): the model's error at each sensor-hour is |offset|
before correction. After correction, each hour is corrected with the previous
hour's readings, so the error is measured on readings the correction hasn't seen.

Writes heat_corr_h07..heat_corr_h19 into data/links.geojson (heat_at() serves them)
and per-sensor errors to data/sensor_validation.csv.

Run after heat.py:
  .venv/Scripts/python heat_model/sensor_correction.py [--readings data/sensors_stream.csv]
"""

import argparse
from pathlib import Path

import geopandas as gpd
import numpy as np
import pandas as pd

from heat import HOURS, TZ, design_weather

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
RADIUS_M = 150


def load_readings(path):
    readings = pd.read_csv(path)
    ts = pd.to_datetime(readings.timestamp, utc=True).dt.tz_convert(TZ)
    readings["hour"] = (ts + pd.Timedelta(minutes=30)).dt.floor("h").dt.hour  # nearest whole hour
    return readings


def sensor_offsets(readings, model_air):
    """Rows: sensor_id, link_id, hour, air_temp_c (median), offset vs the model's air temperature."""
    g = readings.groupby(["sensor_id", "link_id", "hour"]).air_temp_c.median().reset_index()
    g = g[g.hour.isin(model_air.index)].copy()
    g["offset"] = g.air_temp_c - g.hour.map(model_air)
    return g


def sensor_weights(links, sensors):
    """DataFrame (link_id x sensor_id): 1 at the sensor's link midpoint, falling to 0 at RADIUS_M."""
    lu = links.to_crs(links.estimate_utm_crs()).set_index("link_id")
    points = lu.geometry.loc[sensors.link_id].interpolate(0.5, normalized=True)
    d = np.column_stack([lu.geometry.distance(p).values for p in points])
    return pd.DataFrame(np.clip(1 - d / RADIUS_M, 0, None), index=lu.index, columns=sensors.sensor_id.values)


def correction(weights, offsets):
    """offsets: Series sensor_id -> °C for one hour. Returns Series link_id -> °C."""
    w = weights[offsets.index].to_numpy()
    nearest = w.argmax(axis=1)
    return pd.Series(w.max(axis=1) * offsets.to_numpy()[nearest], index=weights.index)


def validate(weights, offsets, sensors):
    """Error at each sensor-hour before correction, and after correcting with the previous hour."""
    by_hour = offsets.pivot(index="hour", columns="sensor_id", values="offset")
    rows = []
    for hour in by_hour.index:
        if hour - 1 not in by_hour.index:
            continue
        prev = by_hour.loc[hour - 1].dropna()
        corr = correction(weights, prev)
        for sensor_id, offset in by_hour.loc[hour].dropna().items():
            link_id = sensors.set_index("sensor_id").link_id[sensor_id]
            rows.append((sensor_id, hour, abs(offset), abs(offset - corr[link_id])))
    return pd.DataFrame(rows, columns=["sensor_id", "hour", "error_before", "error_after"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--readings", default=str(DATA / "sensors_stream.csv"))
    args = parser.parse_args()
    if not Path(args.readings).exists():
        raise SystemExit(f"No readings at {args.readings}: run Person 3's simulate_sensors.py first.")

    links = gpd.read_file(DATA / "links.geojson")
    readings = load_readings(args.readings)
    model_air = design_weather().air_temp_c
    offsets = sensor_offsets(readings, model_air)
    sensors = offsets[["sensor_id", "link_id"]].drop_duplicates("sensor_id").sort_values("sensor_id")
    unknown = sensors[~sensors.link_id.isin(links.link_id)]
    if len(unknown):
        raise SystemExit(f"Sensor links not in links.geojson: {unknown.to_dict('records')}")
    weights = sensor_weights(links, sensors)

    for hour in HOURS:
        at_hour = offsets[offsets.hour == hour].set_index("sensor_id").offset
        corr = correction(weights, at_hour).reindex(links.link_id).fillna(0).values if len(at_hour) else 0.0
        links[f"heat_corr_h{hour:02d}"] = (links[f"heat_h{hour:02d}"] + corr).round(2)
    links.to_file(DATA / "links.geojson", driver="GeoJSON")

    v = validate(weights, offsets, sensors)
    per_sensor = v.groupby("sensor_id")[["error_before", "error_after"]].mean().round(2)
    per_sensor["mean_offset_c"] = offsets.groupby("sensor_id").offset.mean().round(2)
    per_sensor.to_csv(DATA / "sensor_validation.csv")

    expected = len(sensors) * len(HOURS)
    print(f"{len(readings)} readings from {len(sensors)} sensors; {len(offsets)} of {expected} sensor-hours usable")
    print(per_sensor.to_string())
    print(f"\nModel error vs sensors (mean absolute, °C): before {v.error_before.mean():.2f}, "
          f"after {v.error_after.mean():.2f} (corrected with the previous hour's readings, {len(v)} sensor-hours)")
    touched = (weights.max(axis=1) > 0).sum()
    print(f"Wrote heat_corr_h07..heat_corr_h19 ({touched} links within {RADIUS_M} m of a sensor) and sensor_validation.csv")


if __name__ == "__main__":
    main()
