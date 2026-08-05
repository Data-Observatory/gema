# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for visor — builds two targets from one Analysis:

1. Visor/ (onedir) — the primary target, fed into the Windows/macOS
   installers. Faster startup, smaller AV/SmartScreen scan surface per
   launch. See visor/BUILD.md for why this is the recommended default.
2. Visor-portable(.exe) (onefile) — a single-file, no-install-step
   executable for locked-down machines (no admin rights, USB stick,
   etc). Self-extracts to a fresh temp dir on *every* launch, so startup
   is noticeably slower than the onedir build. Measured on the Linux
   build: smaller on disk than onedir (76MB vs 223MB) because the
   onefile archive is zlib-compressed as a whole, while onedir's
   COLLECT() step copies most files uncompressed — so the download-size
   trade-off actually favors onefile here; the real cost is the
   per-launch extraction time, not size. Pick per the "no install step"
   requirement, not as a strict upgrade over onedir.

Both build from a single `uv run pyinstaller visor/visor.spec` — PyInstaller
builds every EXE()/COLLECT()/BUNDLE() target defined in a spec file in one
run. Build via `make build-visor`, never a globally pip-installed
PyInstaller, so frozen deps match uv.lock.

Real Windows .exe / macOS .app installers are produced from the onedir
target by the CI workflow (.github/workflows/visor-build.yml) or a manual
build on that OS — PyInstaller does not cross-compile.
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

# Onefile portable build — exclude_binaries=False + no COLLECT() after is
# what tells PyInstaller to embed everything into the single executable
# instead of leaving it for a separate onedir step.
exe_portable = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="Visor-portable",
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

if sys.platform == "darwin":
    # onedir alone (COLLECT) is just a plain folder even on macOS — a real
    # double-clickable .app needs an explicit BUNDLE() with an Info.plist.
    app = BUNDLE(  # noqa: F821
        coll,
        name="Visor.app",
        icon=None,
        bundle_identifier="cl.dataobservatory.visor",
    )
