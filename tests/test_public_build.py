"""Public packages must preserve source bytes without publishing owner identities."""
import importlib.util
import io
from pathlib import Path
import tarfile

import pytest

from test_release_version import distributions, release

spec = importlib.util.spec_from_file_location('build_public', Path(__file__).resolve().parents[1] / 'development/scripts/build_public.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)


def test_anonymize_preserves_content_long_names_and_links(tmp_path):
    archive = tmp_path / 'source.tar.gz'
    name = 'package/' + 'long-name-' * 20 + '.txt'
    with tarfile.open(archive, 'w:gz') as output:
        file = tarfile.TarInfo(name)
        file.uid, file.gid, file.uname, file.gname = 123, 456, 'fixture-owner', 'fixture-group'
        file.mtime = 123456
        file.pax_headers = {'comment': 'fixture-owner', 'atime': '123456'}
        file.size = 7
        output.addfile(file, io.BytesIO(b'payload'))
        link = tarfile.TarInfo('package/link')
        link.type, link.linkname = tarfile.SYMTYPE, name
        output.addfile(link)
    build.anonymize_sdist(archive)
    with tarfile.open(archive) as result:
        members = result.getmembers()
        assert result.extractfile(members[0]).read() == b'payload'
        assert members[0].name == name
        assert members[1].issym() and members[1].linkname == name
        for member in members:
            assert not any((member.uid, member.gid, member.uname, member.gname, member.mtime))
            assert set(member.pax_headers) <= {'path', 'linkpath'}
    before = archive.read_bytes()
    build.anonymize_sdist(archive)
    assert archive.read_bytes() == before


def test_release_rejects_owner_metadata_until_public_build_normalizes_it(tmp_path):
    distributions(tmp_path)
    archive = tmp_path / 'lumen.tar.gz'
    with tarfile.open(archive) as source:
        member = source.getmembers()[0]
        payload = source.extractfile(member).read()
    member.uname = 'fixture-owner'
    with tarfile.open(archive, 'w:gz') as output:
        output.addfile(member, io.BytesIO(payload))
    with pytest.raises(ValueError, match='ownership is not anonymous'):
        release.check_distributions(tmp_path)
    build.anonymize_sdist(archive)
    assert release.check_distributions(tmp_path) == '0.1.0'
