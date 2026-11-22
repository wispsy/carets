"""Validate release identity, license inclusion, wheel RECORD and source bytes."""
import argparse
import base64
import csv
from email.parser import BytesParser
import hashlib
import io
from pathlib import Path
import tarfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def check(directory, tag):
    version = tag.removeprefix('v')
    assert tag == 'v'+version and version == '0.2.0', 'Unexpected release tag'
    wheel = directory/f'carets-{version}-py3-none-any.whl'
    source = directory/f'carets-{version}.tar.gz'
    assert {p for p in directory.iterdir() if p.name != '.gitignore'} == {wheel, source}, 'Publish only the intended pair'
    with zipfile.ZipFile(wheel) as archive:
        files = {name: archive.read(name) for name in archive.namelist() if not name.endswith('/')}
        prefix = f'carets-{version}.dist-info/'
        metadata = BytesParser().parsebytes(files[prefix+'METADATA'])
        assert all(name.startswith(('carets/', prefix)) for name in files), 'Unexpected wheel payload'
        assert metadata['Name'] == 'carets' and metadata['Version'] == version
        assert metadata['Requires-Python'] == '>=3.10'
        assert metadata['License-Expression'] == 'MIT AND Unicode-3.0'
        assert not metadata.get_all('Requires-Dist'), 'Core must stay dependency-free'
        for name in ('LICENSE', 'UNICODE_LICENSE.txt'):
            assert files[prefix+'licenses/'+name] == (ROOT/name).read_bytes()
        assert b'__version__ = "0.2.0"' in files['carets/__init__.py']
        for name in files:
            if name.startswith('carets/'):
                assert '__pycache__' not in name and name.endswith('.py'), name
                assert files[name] == (ROOT/'src'/name).read_bytes(), name
        records = list(csv.reader(io.StringIO(files[prefix+'RECORD'].decode())))
        assert {row[0] for row in records} == set(files)
        for name, encoded, size in records:
            if name == prefix+'RECORD':
                assert not encoded and not size
                continue
            digest = base64.urlsafe_b64encode(hashlib.sha256(files[name]).digest()).rstrip(b'=').decode()
            assert encoded == 'sha256='+digest and int(size) == len(files[name]), name
    with tarfile.open(source) as archive:
        entries = {member.name: archive.extractfile(member).read() for member in archive.getmembers() if member.isfile()}
        prefix = f'carets-{version}/'
        assert all(name.startswith(prefix) and '..' not in Path(name).parts for name in entries)
        for name in ('LICENSE', 'UNICODE_LICENSE.txt', 'requirements-tables.txt', 'docs/components.md', 'docs/releases.md'):
            assert entries[prefix+name] == (ROOT/name).read_bytes(), name
        for name, data in files.items():
            if name.startswith('carets/'):
                assert entries[prefix+'src/'+name] == data, name
    hashes = {file.name: hashlib.sha256(file.read_bytes()).hexdigest() for file in (wheel, source)}
    print('\n'.join(value+'  '+name for name, value in sorted(hashes.items())))
    return hashes


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    parser.add_argument('--tag', required=True)
    args = parser.parse_args()
    check(args.directory.resolve(), args.tag)
