# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for visor — onedir build, not onefile (see visor/BUILD.md
for why). Build via `make build-visor` (wraps `uv run pyinstaller
visor/visor.spec`), never a globally pip-installed PyInstaller, so frozen
deps match uv.lock.

Real Windows .exe / macOS .app installers are produced from this spec's
onedir output by the CI workflow (.github/workflows/visor-build.yml) or a
manual build on that OS — PyInstaller does not cross-compile.
"""

import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

# PyInstaller execs this file without __file__ in scope — it injects
# SPECPATH (the directory containing this .spec) into the namespace instead.
repo_root = Path(SPECPATH).resolve().parent  # noqa: F821

datas = [
    (str(repo_root / "src" / "metadata_enricher" / "data" / "iana_media_types.json"), "metadata_enricher/data"),
    (str(repo_root / "config" / "agents.yaml"), "visor_default_config"),
]
binaries = []
hiddenimports = []

# instructor/openai do conditional/lazy per-provider imports PyInstaller's
# static analysis misses; nicegui/uvicorn ship static assets and conditional
# transport backends. collect_all is what `--collect-all` calls under the hood.
for _pkg in ("uvicorn", "nicegui", "instructor", "openai"):
    _pkg_datas, _pkg_binaries, _pkg_hiddenimports = collect_all(_pkg)
    datas += _pkg_datas
    binaries += _pkg_binaries
    hiddenimports += _pkg_hiddenimports

a = Analysis(  # noqa: F821 - PyInstaller injects these names at spec exec time
    [str(repo_root / "visor" / "app.py")],
    pathex=[str(repo_root), str(repo_root / "src")],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Visor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name="Visor",
)

if sys.platform == "darwin":
    # onedir alone (COLLECT) is just a plain folder even on macOS — a real
    # double-clickable .app needs an explicit BUNDLE() with an Info.plist.
    app = BUNDLE(  # noqa: F821
        coll,
        name="Visor.app",
        icon=None,
        bundle_identifier="cl.dataobservatory.visor",
    )
