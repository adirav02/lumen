"""Check distribution identity and require v<package-version> for tag builds."""

from email.parser import BytesParser
import os
from pathlib import Path
import tarfile
import zipfile


def check_distributions(dist_dir: Path, ref_type: str = "", ref_name: str = "") -> str:
    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one source distribution")
    with zipfile.ZipFile(wheels[0]) as wheel:
        metadata_paths = [p for p in wheel.namelist() if p.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1:
            raise ValueError("Expected one wheel metadata record")
        wheel_metadata = BytesParser().parsebytes(wheel.read(metadata_paths[0]))
    with tarfile.open(sdists[0]) as sdist:
        if any(member.uid or member.gid or member.uname or member.gname
               for member in sdist.getmembers()):
            raise ValueError('Source archive ownership is not anonymous; use scripts/build_public.py')
        metadata_paths = [m for m in sdist.getmembers() if len(Path(m.name).parts) == 2 and m.name.endswith("/PKG-INFO")]
        if len(metadata_paths) != 1:
            raise ValueError("Expected one source distribution metadata record")
        with sdist.extractfile(metadata_paths[0]) as metadata_file:
            sdist_metadata = BytesParser().parse(metadata_file)
    identities = [(m.get("Name"), m.get("Version")) for m in (wheel_metadata, sdist_metadata)]
    if identities[0] != identities[1] or identities[0][0] != "lumen" or not identities[0][1]:
        raise ValueError(f"Invalid or inconsistent distribution identity: {identities}")
    version = identities[0][1]
    if ref_type == "tag" and ref_name != f"v{version}":
        raise ValueError(f"Tag {ref_name!r} must match package version v{version}")
    return version


if __name__ == "__main__":
    version = check_distributions(Path("dist"), os.environ.get("GITHUB_REF_TYPE", ""), os.environ.get("GITHUB_REF_NAME", ""))
    print(f"Validated lumen {version} distribution identity")
