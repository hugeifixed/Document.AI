"""The optional asset step accepts a pinned artifact and never extracts archive paths."""

import base64
import hashlib
import importlib.util
import io
import tarfile
from pathlib import Path

import pytest


@pytest.fixture
def installer():
    path = Path(__file__).resolve().parents[3] / "scripts/install_scalar.py"
    spec = importlib.util.spec_from_file_location("install_scalar", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_modified_asset_is_rejected_before_writing(installer, tmp_path):
    package = tmp_path / "unapproved.tgz"
    package.write_bytes(b"not the approved package")
    output = tmp_path / "output/standalone.js"
    with pytest.raises(ValueError, match="unmodified"):
        installer.install(package, output)
    assert not output.parent.exists()


def test_installer_only_copies_named_regular_bundle(installer, tmp_path, monkeypatch):
    package = tmp_path / "fixture.tgz"
    with tarfile.open(package, "w:gz") as archive:
        for name in ["package/dist/browser/standalone.js", "../escape.js"]:
            info = tarfile.TarInfo(name)
            info.size = len(b"fixture bundle")
            archive.addfile(info, io.BytesIO(b"fixture bundle"))
    monkeypatch.setattr(
        installer,
        "INTEGRITY",
        base64.b64encode(hashlib.sha512(package.read_bytes()).digest()).decode(),
    )
    output = tmp_path / "output/standalone.js"
    installer.install(package, output)
    assert output.read_bytes() == b"fixture bundle"
    assert output.with_name("LICENSE.txt").read_text().startswith("MIT License")
    assert not (tmp_path / "escape.js").exists()
