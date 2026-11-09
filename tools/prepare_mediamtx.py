"""Download and verify the pinned official Windows MediaMTX release into ignored tools."""
import hashlib
import io
import json
from pathlib import Path
import urllib.request
import zipfile

VERSION='1.21.3'
ROOT=Path(__file__).resolve().parents[1]/'.local-run'/'media-tools'


def main():
    ROOT.mkdir(parents=True,exist_ok=True)
    base=f'https://github.com/bluenviron/mediamtx/releases/download/v{VERSION}/'
    name=f'mediamtx_v{VERSION}_windows_amd64.zip'
    with urllib.request.urlopen(base+name,timeout=60) as response:data=response.read()
    with urllib.request.urlopen(base+'checksums.sha256',timeout=30) as response:checks=response.read().decode()
    expected=next(line.split()[0] for line in checks.splitlines() if line.split()[-1].lstrip('*')==name)
    actual=hashlib.sha256(data).hexdigest()
    if actual!=expected:raise ValueError('MediaMTX checksum mismatch')
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        (ROOT/'mediamtx.exe').write_bytes(archive.read('mediamtx.exe'))
    (ROOT/'provenance.json').write_text(json.dumps({'version':VERSION,'sha256':actual,'source':base+name},indent=2))
    print('Verified official MediaMTX release:',VERSION)


if __name__=='__main__':main()
