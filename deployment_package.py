"""Build/verify the reviewed runtime without changing data or numerical code.

The ZIP preserves original source/input bytes through Git and Linux checkout.
Only the explicit runtime allowlist is included; no cache, secrets or archives.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import tempfile
import time
from uuid import uuid4
import zipfile

ROOT = Path(__file__).resolve().parent
MANIFEST = ROOT / "deployment/package_manifest.json"
RUNTIME_FILES = (
    "app.py", "app_data.py", "cool_route.py", "engine.py", "heat_map.py",
    "planner.py", "sensors_dashboard.py", "simulate_sensors.py",
    "heat_model/effective.py", "heat_model/heat.py", "heat_model/sensor_correction.py",
    "data/links.geojson", "data/places.geojson", "data/weather.csv",
    "data/sensor_links.csv", "data/sensors_stream.csv", "data/interventions.csv",
    "data/corrections/current.json", "config/sensor_simulation.json",
)
CORRECTION_FILES = ("manifest.json", "corrected_heat.csv", "sensor_offsets.csv",
                    "sensor_validation.csv", "rejected_samples.csv")
MAX_UNPACKED_BYTES = 64 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def _safe_name(name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or "\\" in name or ":" in name
            or path.is_absolute() or any(p in (".", "..") for p in name.split("/"))
            or not name or name.endswith("/")):
        raise ValueError("Deployment file paths must be safe relative POSIX paths")
    return path


def _runtime_names(root, version):
    if (not isinstance(version, str) or not version.startswith("v1-")
            or PurePosixPath(version).name != version or "\\" in version
            or ":" in version):
        raise ValueError("Invalid correction version")
    return (*RUNTIME_FILES,
            *(f"data/corrections/{version}/{name}" for name in CORRECTION_FILES))


def build_package(root=ROOT, output_dir=None):
    """Explicit build only; an existing manifest/package is never overwritten."""
    root = Path(root).resolve()
    output = Path(output_dir).resolve() if output_dir else root / "deployment"
    manifest_path = output / "package_manifest.json"
    if manifest_path.exists():
        raise FileExistsError("Deployment manifest exists; use a new unused --output directory")
    # Use the current model validator before packaging. This does not regenerate.
    from heat_model.effective import load_effective_links
    links = load_effective_links(root / "data")
    version = links.attrs.get("correction_version")
    if (links.attrs.get("heat_source") != "corrected"
            or links.attrs.get("design_date") != "2026-09-06"):
        raise ValueError("Deployment requires the reviewed active corrected design-day bundle")
    names = _runtime_names(root, version)
    payloads = {}
    for name in names:
        _safe_name(name)
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"Required deployment artifact is absent or a symlink: {name}")
        payloads[name] = path.read_bytes()
    files = {name: {"sha256": digest(data), "bytes": len(data)}
             for name, data in sorted(payloads.items())}
    identity = digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
    filename = f"coolcorridor-{identity[:20]}.zip"
    output.mkdir(parents=True, exist_ok=True)
    package = output / filename
    with zipfile.ZipFile(package, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name, data in sorted(payloads.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data, compresslevel=9)
    manifest = {"schema_version": 1, "package": filename,
                "package_sha256": digest(package.read_bytes()),
                "package_bytes": package.stat().st_size,
                "unpacked_bytes": sum(v["bytes"] for v in files.values()),
                "content_version": identity, "correction_version": version,
                "design_date": "2026-09-06", "sensor_source": "simulated",
                "heat_source": "corrected", "link_count": len(links),
                "hours": list(range(7, 20)), "files": files}
    with manifest_path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(manifest, stream, indent=2, sort_keys=True)
        stream.write("\n")
    verify_package(manifest_path)
    return manifest_path


def verify_package(manifest_path=MANIFEST):
    """Verify every packaged byte; never load or execute an unverified ZIP."""
    manifest_path = Path(manifest_path)
    if not manifest_path.is_file():
        raise FileNotFoundError("Deployment manifest is missing; build and include deployment/package_manifest.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    filename = manifest.get("package", "")
    _safe_name(filename)
    if PurePosixPath(filename).name != filename or not filename.endswith(".zip"):
        raise ValueError("Invalid deployment ZIP filename")
    package = manifest_path.parent / filename
    if not package.is_file():
        raise FileNotFoundError(f"Deployment ZIP is missing: {filename}")
    if (manifest.get("schema_version") != 1 or manifest.get("design_date") != "2026-09-06"
            or manifest.get("sensor_source") != "simulated"
            or manifest.get("heat_source") != "corrected"
            or manifest.get("link_count") != 1491 or manifest.get("hours") != list(range(7, 20))
            or manifest.get("package_bytes") != package.stat().st_size
            or manifest.get("package_sha256") != digest(package.read_bytes())):
        raise ValueError("Deployment package integrity, source or design-day metadata is invalid")
    expected = set(_runtime_names(None, manifest.get("correction_version")))
    files = manifest.get("files", {})
    if set(files) != expected:
        raise ValueError("Deployment manifest is missing required runtime artifacts")
    if (sum(item["bytes"] for item in files.values()) != manifest.get("unpacked_bytes")
            or not 0 < manifest["unpacked_bytes"] <= MAX_UNPACKED_BYTES):
        raise ValueError("Deployment unpacked size is invalid")
    identity = digest(json.dumps(files, sort_keys=True, separators=(",", ":")).encode())
    if manifest.get("content_version") != identity:
        raise ValueError("Deployment content version disagrees with file manifest")
    with zipfile.ZipFile(package) as archive:
        if len(archive.namelist()) != len(expected) or set(archive.namelist()) != expected:
            raise ValueError("Deployment ZIP contents disagree with required artifacts")
        for item in archive.infolist():
            _safe_name(item.filename)
            if item.file_size != files[item.filename]["bytes"] or item.external_attr >> 16 & 0o170000 == 0o120000:
                raise ValueError("Deployment ZIP file size or type disagrees with its manifest")
            data = archive.read(item)
            if (len(data) != files[item.filename]["bytes"]
                    or digest(data) != files[item.filename]["sha256"]):
                raise ValueError(f"Deployment artifact changed: {item.filename}")
    return manifest


def prepare_runtime(manifest_path=MANIFEST, runtime_root=None):
    """Extract verified bytes into an ephemeral version directory, never sources.

    Existing extracted files are rechecked; corrupt runtimes are rejected, not
    repaired behind the operator's back. Nothing depends on ignored cache/.
    """
    manifest_path = Path(manifest_path)
    manifest = verify_package(manifest_path)
    base = Path(runtime_root) if runtime_root else Path(tempfile.gettempdir()) / "coolcorridor-runtime"
    base = base.resolve()
    base.mkdir(parents=True, exist_ok=True)
    # Keep nested Windows workspace/temp paths practical; full file SHA-256
    # checks below still reject any prefix collision or stale extraction.
    target = base / manifest["content_version"][:20]
    if not target.exists():
        staging = base / (".extract-" + uuid4().hex)
        staging.mkdir()
        try:
            with zipfile.ZipFile(manifest_path.parent / manifest["package"]) as archive:
                for name in manifest["files"]:
                    dest = staging.joinpath(*_safe_name(name).parts)
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    with dest.open("xb") as stream:
                        stream.write(archive.read(name))
            for attempt in range(8):
                try:
                    staging.rename(target)
                    break
                except OSError as exc:
                    if target.is_dir():  # Another session published verified bytes.
                        break
                    # Windows scanners/watchers can briefly retain a newly
                    # written file handle and deny directory promotion. Bound
                    # retries; persistent permission errors still fail closed.
                    if os.name != "nt" or not isinstance(exc, PermissionError) or attempt == 7:
                        raise
                    time.sleep(.05 * (attempt + 1))
        finally:
            if staging.exists():
                if staging.resolve().parent != base or not staging.name.startswith(".extract-"):
                    raise ValueError("Unsafe staging cleanup path")
                shutil.rmtree(staging)
    for name, meta in manifest["files"].items():
        path = target.joinpath(*_safe_name(name).parts)
        if not path.is_file() or path.is_symlink() or digest(path.read_bytes()) != meta["sha256"]:
            raise ValueError(f"Extracted deployment artifact is missing or corrupt: {name}")
    return target


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", action="store_true", help="Explicitly build a new reviewed package")
    parser.add_argument("--output", type=Path, help="New package directory; never overwrite")
    parser.add_argument("--manifest", type=Path, default=MANIFEST)
    args = parser.parse_args()
    path = build_package(output_dir=args.output) if args.build else args.manifest
    result = verify_package(path)
    print(json.dumps({"manifest": str(path), "package": result["package"],
                      "package_bytes": result["package_bytes"],
                      "unpacked_bytes": result["unpacked_bytes"],
                      "files": len(result["files"]), "correction_version": result["correction_version"]}, indent=2))


if __name__ == "__main__":
    main()
