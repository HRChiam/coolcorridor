"""Byte-preserving deployment and isolated first-run tests; never regenerate data."""

import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import deployment_package as package


def copy_package(destination):
    destination.mkdir()
    manifest = package.verify_package()
    for name in ("package_manifest.json", manifest["package"]):
        shutil.copyfile(ROOT / "deployment" / name, destination / name)
    return destination / "package_manifest.json"


def test_reviewed_package_has_only_required_bytes_and_preserves_model():
    manifest = package.verify_package()
    assert len(manifest["files"]) == 24
    assert manifest["link_count"] * len(manifest["hours"]) == 19383
    assert manifest["heat_source"] == "corrected" and manifest["sensor_source"] == "simulated"
    with zipfile.ZipFile(ROOT / "deployment" / manifest["package"]) as archive:
        for name, meta in manifest["files"].items():
            assert archive.read(name) == (ROOT / name).read_bytes()
            assert meta["sha256"] == package.digest(archive.read(name))
            assert not any(part in name for part in ("cache/", ".git/", "secrets", ".env", "results/"))


def test_build_is_reproducible_and_refuses_overwrite(tmp_path):
    first = package.build_package(output_dir=tmp_path / "a")
    second = package.build_package(output_dir=tmp_path / "b")
    assert first.read_bytes() == second.read_bytes()
    assert package.verify_package(first)["package_sha256"] == package.verify_package()["package_sha256"]
    with pytest.raises(FileExistsError):
        package.build_package(output_dir=first.parent)


@pytest.mark.parametrize("damage", ["missing_manifest", "missing_zip", "corrupt_zip", "missing_required_file", "bad_date"])
def test_missing_or_corrupt_deployment_artifacts_fail_closed(tmp_path, damage):
    path = copy_package(tmp_path / "package")
    manifest = json.loads(path.read_text())
    if damage == "missing_manifest":
        path.unlink()
    elif damage == "missing_zip":
        (path.parent / manifest["package"]).unlink()
    elif damage == "corrupt_zip":
        with (path.parent / manifest["package"]).open("ab") as stream:
            stream.write(b"changed")
    else:
        if damage == "missing_required_file":
            del manifest["files"]["data/sensors_stream.csv"]
        else:
            manifest["design_date"] = "2026-10-19"
        path.write_text(json.dumps(manifest))
    with pytest.raises((ValueError, FileNotFoundError)):
        package.prepare_runtime(path, tmp_path / "runtime")
    assert not (tmp_path / "runtime").exists()


def test_extraction_reuses_verified_bytes_and_detects_corruption(tmp_path):
    runtime = package.prepare_runtime(runtime_root=tmp_path / "runtime")
    assert package.prepare_runtime(runtime_root=tmp_path / "runtime") == runtime
    file = runtime / "data/sensors_stream.csv"
    with file.open("ab") as stream:
        stream.write(b"changed")
    with pytest.raises(ValueError, match="corrupt"):
        package.prepare_runtime(runtime_root=tmp_path / "runtime")
    assert file.read_bytes().endswith(b"changed")  # No silent repair/regeneration.


@pytest.mark.parametrize("name", ["../outside", "/absolute", "C:/windows", "a\\b", "a/../b"])
def test_unsafe_archive_paths_rejected(name):
    with pytest.raises(ValueError):
        package._safe_name(name)


def test_packaged_model_provenance_survives_isolated_checkout(tmp_path):
    path = copy_package(tmp_path / "package")
    # Git may normalize outer checkout source. The archived numerical source
    # stays byte-identical and passes the original correction manifest.
    runtime = package.prepare_runtime(path, tmp_path / "runtime")
    command = [sys.executable, "-B", "-c",
               "from heat_model.effective import effective_heat_at; "
               "f=effective_heat_at(14); assert len(f)==1491; "
               "assert f.heat_source.eq('corrected').all(); print(f.attrs['correction_version'])"]
    result = subprocess.run(command, cwd=runtime, capture_output=True, text=True, check=True)
    assert package.verify_package(path)["correction_version"] in result.stdout


def test_corrupt_internal_correction_manifest_is_rejected(tmp_path):
    runtime = package.prepare_runtime(runtime_root=tmp_path / "runtime")
    manifest = package.verify_package()
    path = runtime / "data/corrections" / manifest["correction_version"] / "manifest.json"
    path.write_text("{}")
    command = [sys.executable, "-B", "-c", "from heat_model.effective import effective_heat_at; effective_heat_at(14)"]
    result = subprocess.run(command, cwd=runtime, capture_output=True, text=True)
    assert result.returncode != 0
    assert "manifest" in result.stderr.lower()


def test_first_run_cloud_entrypoint_without_repository_data_or_cache(tmp_path):
    minimal = tmp_path / "checkout"
    minimal.mkdir()
    for name in ("streamlit_app.py", "deployment_package.py"):
        shutil.copyfile(ROOT / name, minimal / name)
    copy_package(minimal / "deployment")
    assert not (minimal / "cache").exists() and not (minimal / "data").exists()
    temporary = tmp_path / "temporary"
    temporary.mkdir()
    env = os.environ.copy()
    env.pop("COOLCORRIDOR_DATA_DIR", None)
    env["TEMP"] = env["TMP"] = env["TMPDIR"] = str(temporary)
    code = """
import json,time
from streamlit.testing.v1 import AppTest
started=time.perf_counter()
app=AppTest.from_file('streamlit_app.py',default_timeout=90).run()
assert not app.exception, str(app.exception)
assert not app.error, [error.value for error in app.error]
assert app.title[0].value=='COOLNEX'
assert [t.label for t in app.tabs]==['Cool Route','Heat Map','Sensors','Planner']
assert all(t.get('deck_gl_json_chart') for t in app.tabs)
assert app.tabs[3].metric[0].value=='RM 99,818.00'
assert app.tabs[3].metric[2].value=='6'
print(json.dumps({'cold_app_seconds':time.perf_counter()-started,'tabs':4,'maps':4}))
"""
    result = subprocess.run([sys.executable, "-B", "-c", code], cwd=minimal, env=env,
                            capture_output=True, text=True, timeout=120)
    assert result.returncode == 0, result.stderr + result.stdout
    assert '"maps": 4' in result.stdout
    assert not (minimal / "data").exists() and not (minimal / "cache").exists()
