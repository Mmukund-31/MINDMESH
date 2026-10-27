"""Build Studio into the Python package, so ``pip install mindmesh`` + ``mindmesh serve`` serves it (no Node needed).

    python scripts/build_studio.py           # rebuild src/mindmesh/server/studio/
    python scripts/build_studio.py --check   # exit 1 if the bundle is older than the Studio sources

The bundle records a hash of the Studio sources in BUILD_INFO.json; the test suite runs ``--check``, so a Studio
change without a rebuild fails CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
STUDIO = ROOT / "studio"
TARGET = ROOT / "src" / "mindmesh" / "server" / "studio"
INPUTS = ["src", "public", "index.html", "package.json", "package-lock.json", "vite.config.ts", "tsconfig.json"]


def source_hash() -> str:
    h = hashlib.sha256()
    for name in INPUTS:
        p = STUDIO / name
        files = sorted(f for f in p.rglob("*") if f.is_file() and ".test." not in f.name) if p.is_dir() else [p]
        for f in files:
            if "test" in f.relative_to(STUDIO).parts:
                continue
            h.update(f.relative_to(STUDIO).as_posix().encode())
            h.update(f.read_bytes().replace(b"\r\n", b"\n"))  # same hash on Windows and Linux checkouts
    return h.hexdigest()


def check() -> int:
    info = TARGET / "BUILD_INFO.json"
    if not info.exists() or not (TARGET / "index.html").exists():
        print(f"no Studio bundle in {TARGET}; run: python scripts/build_studio.py")
        return 1
    if json.loads(info.read_text())["source_sha256"] != source_hash():
        print("the bundled Studio is out of date with studio/; run: python scripts/build_studio.py")
        return 1
    print("bundled Studio is up to date")
    return 0


def build() -> int:
    npx = shutil.which("npx")
    if npx is None:
        print("Node.js (npx) is required to build Studio")
        return 1
    out = STUDIO / "dist-package"
    # Same-origin build with the local development key as default: the server that ships it serves the API too.
    # Environment variables beat .env files in Vite: blank them so no deployment's URL or key leaks in.
    env = {**os.environ, "VITE_API_URL": "", "VITE_DEFAULT_API_KEY": ""}
    subprocess.run([npx, "vite", "build", "--outDir", str(out), "--emptyOutDir"], cwd=STUDIO, env=env, check=True)
    shutil.rmtree(TARGET, ignore_errors=True)  # a running server may hold files open on Windows
    for stale in (TARGET / "assets").glob("*") if TARGET.exists() else []:
        stale.unlink(missing_ok=True)
    shutil.copytree(out, TARGET, dirs_exist_ok=True)
    shutil.rmtree(out)
    (TARGET / "BUILD_INFO.json").write_text(json.dumps({"source_sha256": source_hash()}, indent=2) + "\n")
    print(f"Studio bundled into {TARGET.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    sys.exit(check() if parser.parse_args().check else build())
