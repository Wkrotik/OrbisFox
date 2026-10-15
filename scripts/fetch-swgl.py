#!/usr/bin/env python3
"""Fetch the pinned Firefox SWGL sources and shader compiler (no full checkout)."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import urllib.request

REVISION = '83cebcf5a522bf49667fd07084f04e8497de0eba'
ROOT = Path(__file__).resolve().parent.parent
DEST = ROOT / '.deps/firefox-wr'
TREES = {
    'swgl': 'ad887b1aeabe722c50a9201e5be0ae79f095f6ea',
    'glsl-to-cxx': '88646102eaa5b1c7d96bd38d1949efe9204646c6',
    'webrender_build': '7a78b5e3cc1285d6be5720066206c665c27d1fac',
    'webrender': 'c6a63bd99f178706ce922867ffd064cca0b8556c',
}


def download(url):
    request = urllib.request.Request(url, headers={'User-Agent': 'OrbisFox-build'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read()


def main():
    files = []
    for name, tree in TREES.items():
        listing = json.loads(download(f'https://api.github.com/repos/mozilla-firefox/firefox/git/trees/{tree}?recursive=1'))
        if listing.get('truncated'):
            raise RuntimeError('Truncated source listing')
        for item in listing['tree']:
            if item['type'] != 'blob':
                continue
            relative = item['path']
            if name == 'webrender' and not relative.startswith('res/'):
                continue
            if name == 'glsl-to-cxx' and not (relative.startswith('src/') or relative == 'Cargo.toml'):
                continue
            if name == 'webrender_build' and not (relative.startswith('src/') or relative == 'Cargo.toml'):
                continue
            files.append((name, relative, item['sha']))

    def fetch(item):
        name, relative, expected = item
        path = DEST / name / relative
        if path.exists():
            data = path.read_bytes()
        else:
            data = download(f'https://raw.githubusercontent.com/mozilla-firefox/firefox/{REVISION}/gfx/wr/{name}/{relative}')
        actual = hashlib.sha1(f'blob {len(data)}\0'.encode() + data).hexdigest()
        if actual != expected:
            raise RuntimeError(f'Git blob mismatch: {path}')
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(fetch, files))
    # Isolated host workspace: Rust is used only to generate shaders here.
    (DEST / 'Cargo.toml').write_text('''[workspace]
resolver = "2"
members = ["swgl", "glsl-to-cxx", "webrender_build"]
[workspace.dependencies]
gleam = "0.16"
[profile.dev.package.glsl]
opt-level = 2
''')
    print(f'Fetched {len(files)} verified Firefox blobs at {REVISION}')


if __name__ == '__main__':
    main()
