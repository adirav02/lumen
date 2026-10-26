"""Release gating must reject mismatched artifacts and tags before publication."""

import importlib.util
import io
from pathlib import Path
import tarfile
import zipfile

import pytest

spec = importlib.util.spec_from_file_location("check_release_version", Path(__file__).resolve().parents[1] / "development/scripts/check_release_version.py")
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


def distributions(directory, wheel_version="0.1.0", sdist_version="0.1.0"):
    with zipfile.ZipFile(directory / "lumen.whl", "w") as wheel:
        wheel.writestr("lumen.dist-info/METADATA", f"Name: lumen\nVersion: {wheel_version}\n")
    content = f"Name: lumen\nVersion: {sdist_version}\n".encode()
    with tarfile.open(directory / "lumen.tar.gz", "w:gz") as sdist:
        member = tarfile.TarInfo("lumen/PKG-INFO")
        member.size = len(content)
        sdist.addfile(member, io.BytesIO(content))


def test_release_accepts_matching_artifacts_and_tag(tmp_path):
    distributions(tmp_path)
    assert release.check_distributions(tmp_path, "tag", "v0.1.0") == "0.1.0"
    assert release.check_distributions(tmp_path, "branch", "main") == "0.1.0"


def test_release_rejects_different_tag(tmp_path):
    distributions(tmp_path)
    with pytest.raises(ValueError, match="must match package version"):
        release.check_distributions(tmp_path, "tag", "v9.0.0")


def test_release_rejects_inconsistent_artifacts(tmp_path):
    distributions(tmp_path, sdist_version="0.2.0")
    with pytest.raises(ValueError, match="inconsistent distribution identity"):
        release.check_distributions(tmp_path)


def test_release_rejects_missing_artifact(tmp_path):
    with pytest.raises(ValueError, match="exactly one wheel"):
        release.check_distributions(tmp_path)
