"""Visible COOLNEX branding must survive the byte-preserving deployment path."""

import ast
import json
from pathlib import Path
import re
import zipfile

from deployment_package import verify_package


ROOT = Path(__file__).resolve().parents[1]


def test_local_and_packaged_app_titles_use_official_brand():
    manifest = verify_package()
    with zipfile.ZipFile(ROOT / "deployment" / manifest["package"]) as archive:
        sources = [ROOT.joinpath("app.py").read_text(encoding="utf-8"),
                   archive.read("app.py").decode("utf-8")]
    for source in sources:
        calls = [node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.Call)
                 and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name)
                 and node.func.value.id == "st"]
        page = next(call for call in calls if call.func.attr == "set_page_config")
        assert ast.literal_eval(next(k.value for k in page.keywords if k.arg == "page_title")) == "COOLNEX"
        titles = [ast.literal_eval(call.args[0]) for call in calls if call.func.attr == "title"]
        assert titles == ["COOLNEX"]
        assert not re.search(r"cool[ -]?corridor", source, re.I)


def test_rebrand_keeps_reviewed_calculations_and_correction_version():
    previous = json.loads((ROOT / "deployment/archive/package_manifest-f5d9e8d1e2f6a281ec6c.json").read_text())
    current = verify_package()
    assert current["correction_version"] == previous["correction_version"]
    changed = {name for name in current["files"]
               if current["files"][name] != previous["files"][name]}
    assert changed == {"app.py"}
    with zipfile.ZipFile(ROOT / "deployment" / previous["package"]) as old:
        with zipfile.ZipFile(ROOT / "deployment" / current["package"]) as new:
            for name in current["files"]:
                if name != "app.py":
                    assert old.read(name) == new.read(name)
