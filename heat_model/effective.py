"""Shared, read-only design-day heat contract and immutable correction reader.

The frozen network keeps the baseline index.  Optional corrections live in a
separate, hash-checked bundle; no caller silently combines partial corrections.
"""

from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re

import geopandas as gpd
import numpy as np
import pandas as pd

DATA = Path(__file__).resolve().parents[1] / "data"
DESIGN_DATE = "2026-09-06"
HOURS = tuple(range(7, 20))
TZ = "Asia/Kuala_Lumpur"
SCHEMA_VERSION = 1


def sha256_file(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def design_weather(path_or_dir=DATA, design_date=DESIGN_DATE):
    """Exactly one finite record per design hour; forecast data is never used."""
    path = Path(path_or_dir)
    if path.suffix.lower() != ".csv":
        path = path / "weather.csv"
    weather = pd.read_csv(path)
    required = {"day", "date", "hour", "air_temp_c", "rh_pct", "sw_wm2", "wind_ms"}
    if not required.issubset(weather.columns):
        raise ValueError("Weather is missing the shared design-day fields")
    selected = weather.loc[weather.day == "design"].copy()
    if (selected.empty or selected.date.isna().any()
            or not selected.date.astype(str).eq(design_date).all()):
        raise ValueError(f"Design weather must refer only to {design_date} in {TZ}")
    selected["hour"] = pd.to_numeric(selected.hour, errors="raise")
    selected = selected.sort_values("hour")
    if selected.hour.tolist() != list(HOURS):
        raise ValueError("Design weather must contain hours 07..19 exactly once")
    selected["hour"] = selected.hour.astype(int)
    for column in ("air_temp_c", "rh_pct", "sw_wm2", "wind_ms"):
        selected[column] = pd.to_numeric(selected[column], errors="raise").astype(float)
        if not np.isfinite(selected[column]).all():
            raise ValueError(f"Design weather contains invalid {column}")
    if (not selected.rh_pct.between(0, 100).all()
            or (selected[["sw_wm2", "wind_ms"]] < 0).any().any()):
        raise ValueError("Design weather humidity must be 0..100; radiation and wind must be nonnegative")
    # Forecast rows can change CSV-inferred dtypes. Canonicalise selected numeric
    # values so unrelated forecast int/float/string representations have no effect.
    for column in ("sun_elev_deg", "sun_azim_deg"):
        if column in selected:
            selected[column] = pd.to_numeric(selected[column], errors="raise").astype(float)
            if not np.isfinite(selected[column]).all():
                raise ValueError(f"Design weather contains invalid {column}")
    return selected.set_index("hour")


def design_weather_hash(path_or_dir=DATA):
    """Canonical selected rows, independent of forecast rows/order/CSV layout."""
    selected = design_weather(path_or_dir).sort_index().sort_index(axis=1)
    return hashlib.sha256(selected.to_json(orient="split", double_precision=15).encode()).hexdigest()


def _pointer(data_dir):
    path = Path(data_dir) / "corrections" / "current.json"
    if not path.exists():
        return None
    pointer = json.loads(path.read_text(encoding="utf-8"))
    version = pointer.get("version", "")
    if (pointer.get("schema_version") != SCHEMA_VERSION
            or not isinstance(version, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", version)
            or version in (".", "..")):
        raise ValueError("Invalid corrected-heat bundle pointer")
    directory = path.parent / version
    manifest_path = directory / "manifest.json"
    if not manifest_path.is_file() or pointer.get("manifest_sha256") != sha256_file(manifest_path):
        raise ValueError("Corrected-heat manifest is absent or its hash disagrees with the pointer")
    return pointer, directory


def input_signature(data_dir=DATA):
    """Content keys for caches; selected design weather ignores forecast changes."""
    directory = Path(data_dir).resolve()
    result = [("implementation/" + name, sha256_file(Path(__file__).with_name(name)))
              for name in ("effective.py", "sensor_correction.py", "heat.py")]
    for name in ("links.geojson", "weather.csv", "sensor_links.csv", "sensors_stream.csv",
                 "../config/sensor_simulation.json"):
        path = directory / name
        if path.is_file():
            digest = sha256_file(path)
            if name == "weather.csv":
                digest = design_weather_hash(path)
            result.append((name, digest))
    active = _pointer(directory)
    if active is not None:
        _, bundle = active
        result.append(("corrections/current.json", sha256_file(directory / "corrections/current.json")))
        for path in sorted(bundle.iterdir()):
            if path.is_file():
                result.append((str(path.relative_to(directory)), sha256_file(path)))
    return tuple(result)


def _validate_manifest(data_dir, directory, links):
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if (manifest.get("schema_version") != SCHEMA_VERSION
            or manifest.get("output_version") != directory.name
            or manifest.get("design_date") != DESIGN_DATE
            or manifest.get("timezone") != TZ
            or manifest.get("sensor_source") != "simulated"
            or manifest.get("hours") != list(HOURS)
            or manifest.get("link_count") != len(links)
            or manifest.get("row_count") != len(links) * len(HOURS)
            or manifest.get("sensor_count") != 8):
        raise ValueError("Corrected-heat manifest has inconsistent date, source, version or dimensions")
    implementation = manifest.get("implementation", {})
    if set(implementation) != {"sensor_correction.py", "effective.py", "heat.py"}:
        raise ValueError("Corrected-heat implementation provenance is incomplete")
    for name, digest in implementation.items():
        if (not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                or sha256_file(Path(__file__).with_name(name)) != digest):
            raise ValueError(f"Corrected-heat implementation differs: {name}; regenerate a reviewed version")
    inputs = manifest.get("inputs", {})
    required = {"links.geojson", "weather.csv", "sensor_links.csv", "sensors_stream.csv",
                "../config/sensor_simulation.json"}
    if set(inputs) != required:
        raise ValueError("Corrected-heat manifest has incomplete input provenance")
    for name, recorded in inputs.items():
        path = Path(data_dir) / name
        if not path.is_file():
            raise ValueError(f"Corrected-heat source is missing: {name}")
        actual = design_weather_hash(path) if name == "weather.csv" else sha256_file(path)
        expected = recorded.get("design_rows_sha256") if name == "weather.csv" else recorded.get("sha256")
        if actual != expected:
            raise ValueError(f"Corrected-heat bundle is stale: source hash differs for {name}")
    outputs = manifest.get("outputs", {})
    expected_outputs = {"corrected_heat.csv", "sensor_validation.csv", "sensor_offsets.csv", "rejected_samples.csv"}
    if set(outputs) != expected_outputs:
        raise ValueError("Corrected-heat manifest has incomplete output provenance")
    for name, digest in outputs.items():
        path = directory / name
        if not path.is_file() or sha256_file(path) != digest:
            raise ValueError(f"Corrected-heat output is missing or changed: {name}")
    coverage = manifest.get("sensor_hours_per_hour", {})
    if (set(coverage) != {str(h) for h in HOURS}
            or any(type(n) is not int or not 0 <= n <= 8 for n in coverage.values())):
        raise ValueError("Corrected-heat hourly sensor coverage is inconsistent")
    offsets = pd.read_csv(directory / "sensor_offsets.csv")
    required_offsets = {"sensor_id", "link_id", "hour", "offset", "accepted_samples"}
    if (not required_offsets.issubset(offsets.columns)
            or offsets.duplicated(["sensor_id", "hour"]).any()
            or not offsets.hour.isin(HOURS).all()):
        raise ValueError("Corrected-heat sensor-hour offsets are invalid")
    sites = pd.read_csv(Path(data_dir) / "sensor_links.csv").set_index("sensor_id").link_id
    if (not offsets.sensor_id.map(sites).eq(offsets.link_id).all()
            or not np.isfinite(pd.to_numeric(offsets.offset, errors="raise")).all()
            or not pd.to_numeric(offsets.accepted_samples, errors="raise").ge(1).all()):
        raise ValueError("Corrected-heat offsets require valid mappings and accepted observations")
    actual_coverage = {str(hour): int(offsets.hour.eq(hour).sum()) for hour in HOURS}
    if (coverage != actual_coverage
            or manifest.get("baseline_fallback_hours") != [h for h in HOURS if coverage[str(h)] == 0]):
        raise ValueError("Corrected-heat coverage disagrees with its sensor-hour observations")
    return manifest


@lru_cache(maxsize=8)
def _load_cached(data_dir, signature, bundle_override=None):
    directory = Path(data_dir)
    links = gpd.read_file(directory / "links.geojson")
    if links.empty or "link_id" not in links or links.link_id.isna().any() or links.link_id.duplicated().any():
        raise ValueError("Walking network must contain nonempty, unique link IDs")
    if (links.crs is None or links.geometry.isna().any() or links.geometry.is_empty.any()
            or not links.geometry.is_valid.all()):
        raise ValueError("Walking network requires valid geometry and a declared CRS")
    links = links.to_crs(4326)
    xmin, ymin, xmax, ymax = links.total_bounds
    if (not np.isfinite([xmin, ymin, xmax, ymax]).all()
            or xmin < -180 or xmax > 180 or ymin < -90 or ymax > 90):
        raise ValueError("Walking network coordinates must be valid EPSG:4326 longitude/latitude")
    links["link_id"] = links.link_id.astype(str)
    embedded = [c for c in links if c.startswith("heat_corr_h")]
    if embedded:
        raise ValueError("Unversioned or incomplete corrected heat columns are unsupported; use a validated correction bundle")
    date = None
    weather_path = directory / "weather.csv"
    if weather_path.is_file():
        date = str(design_weather(weather_path).date.iloc[0])
    links.attrs.update(heat_source="baseline", sensor_source=None, design_date=date,
                       correction_version=None, sensor_hours_per_hour={})
    active = (None, Path(bundle_override)) if bundle_override is not None else _pointer(directory)
    if active is None:
        return links
    _, bundle = active
    manifest = _validate_manifest(directory, bundle, links)
    values = pd.read_csv(bundle / "corrected_heat.csv")
    required = {"link_id", "hour", "heat_model", "correction_c", "heat"}
    if (not required.issubset(values.columns) or len(values) != len(links) * len(HOURS)
            or values.duplicated(["link_id", "hour"]).any()
            or set(values.link_id) != set(links.link_id) or set(values.hour) != set(HOURS)):
        raise ValueError("Corrected-heat bundle is incomplete or contains duplicate/unknown link-hours")
    for column in ("hour", "heat_model", "correction_c", "heat"):
        values[column] = pd.to_numeric(values[column], errors="raise")
        if not np.isfinite(values[column]).all():
            raise ValueError(f"Corrected-heat bundle contains invalid {column}")
    if not np.allclose(values.heat, values.heat_model + values.correction_c, rtol=0, atol=1e-8):
        raise ValueError("Corrected-heat values do not equal baseline plus correction")
    indexed = links.set_index("link_id")
    for hour in HOURS:
        hourly = values.loc[values.hour == hour].set_index("link_id")
        baseline = f"heat_h{hour:02d}"
        if (len(hourly) != len(links) or baseline not in links
                or not np.isfinite(pd.to_numeric(links[baseline], errors="raise")).all()
                or not np.allclose(hourly.loc[links.link_id, "heat_model"], links[baseline], rtol=0, atol=1e-9)):
            raise ValueError(f"Corrected-heat baseline or coverage disagrees at {hour:02d}:00")
        if manifest["sensor_hours_per_hour"][str(hour)] == 0 and not np.allclose(hourly.correction_c, 0):
            raise ValueError("An hour without usable sensors must retain explicit baseline fallback")
        links[f"heat_corr_h{hour:02d}"] = hourly.loc[indexed.index, "heat"].to_numpy()
    links.attrs.update(heat_source="corrected", sensor_source="simulated", design_date=DESIGN_DATE,
                       correction_version=manifest["output_version"],
                       sensor_hours_per_hour=manifest["sensor_hours_per_hour"],
                       correction_manifest=manifest)
    return links


def load_effective_links(data_dir=DATA):
    """Return a private snapshot with all baseline and validated effective columns."""
    directory = Path(data_dir).resolve()
    return _load_cached(str(directory), input_signature(directory)).copy(deep=True)


def validate_bundle(data_dir, bundle_dir):
    """Validate a staged immutable version completely before pointer activation."""
    directory, bundle = Path(data_dir).resolve(), Path(bundle_dir).resolve()
    if not bundle.is_relative_to(directory / "corrections"):
        raise ValueError("Correction bundle must stay inside data/corrections")
    # Include every byte from this version in its private cache key.
    signature = input_signature(directory) + tuple((str(path), sha256_file(path))
                                                   for path in sorted(bundle.iterdir()) if path.is_file())
    return _load_cached(str(directory), signature, str(bundle)).copy(deep=True)


def clear_effective_cache():
    _load_cached.cache_clear()


def effective_heat_at(hour, data_dir=DATA, *, links=None):
    """Common per-hour metadata.  Synthetic baseline-only fixtures remain usable."""
    if isinstance(hour, bool) or not isinstance(hour, (int, np.integer)) or hour not in HOURS:
        raise ValueError("Hour must be a whole hour from 07:00 to 19:00")
    out = load_effective_links(data_dir) if links is None else links.copy(deep=True)
    baseline = f"heat_h{hour:02d}"
    if baseline not in out:
        raise ValueError(f"Missing baseline {baseline}")
    out["heat_model"] = pd.to_numeric(out[baseline], errors="raise")
    corrected = f"heat_corr_h{hour:02d}"
    source = "corrected" if out.attrs.get("correction_version") is not None else "baseline"
    if source == "corrected" and out.attrs["sensor_hours_per_hour"].get(str(hour), 0) == 0:
        source = "baseline"
    out["heat"] = pd.to_numeric(out[corrected] if corrected in out else out[baseline], errors="raise")
    if not np.isfinite(out[["heat_model", "heat"]]).all().all():
        raise ValueError("Effective and baseline heat must be finite")
    shade = f"shade_h{hour:02d}"
    if shade in out:
        out["shade"] = pd.to_numeric(out[shade], errors="raise").clip(0, 1)
    else:
        out["shade"] = pd.to_numeric(out.get("canopy", pd.Series(0., index=out.index)), errors="raise").fillna(0).clip(0, 1) * .8
    if "covered" in out:
        covered = out.covered.map(lambda value: str(value).strip().lower() in ("true", "1", "yes", "covered"))
        out.loc[covered, "shade"] = 1.
    if not np.isfinite(out.shade).all():
        raise ValueError("Shade must be finite")
    out["hour"] = hour
    out["design_date"] = out.attrs.get("design_date")
    out["heat_source"] = source
    out["sensor_source"] = "simulated" if source == "corrected" else None
    out.attrs.update(heat_source=source, sensor_source="simulated" if source == "corrected" else None,
                     sensor_corrected=source == "corrected")
    return out
