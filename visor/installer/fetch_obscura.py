"""Fetch + verify the ``obscura`` headless-render binary for bundling into a
frozen Visor build (see visor.spec's ``binaries`` staging step).

``obscura`` (https://github.com/h4ckf0r0day/obscura, Apache-2.0) is a
standalone Rust CLI used by content_fetcher.py's opt-in JS-render fallback
(``PipelineConfig.enable_js_render_fallback``) -- it is never a pip
dependency, so this script is Visor's own vendoring step, run at build time
on each platform's own CI runner (PyInstaller doesn't cross-compile, so this
never needs to fetch a *different* platform's asset than the one it's
running on).

Pinned to an exact release tag, with a hardcoded sha256 per asset (from
GitHub's own per-asset digest, since obscura publishes no separate
SHA256SUMS/signature file) -- verified before extraction, never after.

Two distinct failure modes, deliberately not conflated:
- A platform this repo has no pinned asset for, or a transient network
  failure fetching the release, degrades to "obscura not staged"
  (``ObscuraUnsupportedPlatformError``) -- visor.spec treats this as skip-
  bundling, not a build failure: the JS-render fallback is opt-in and off
  by default, so shipping a build without it is a degraded-but-working
  outcome, not a broken one.
- A sha256 mismatch or a missing expected member inside an otherwise-
  downloaded archive (``ObscuraVerificationError``) means either a
  corrupted download or a tampered/compromised release -- visor.spec does
  *not* catch this; it must fail the build loudly rather than silently
  ship (or silently omit) an unverified binary.
"""

from __future__ import annotations

import hashlib
import platform
import shutil
import stat
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path

import httpx

OBSCURA_VERSION = "v0.2.2"
_RELEASE_BASE = f"https://github.com/h4ckf0r0day/obscura/releases/download/{OBSCURA_VERSION}"

# (system, machine) -> (release asset filename, sha256 of that archive,
# extracted binary name inside it). Render-enabled, non-stealth variant only
# -- obscura also ships "-no-render"/"-stealth" builds; the former can't run
# JS at all (defeats the entire point), the latter (bot-challenge bypass)
# was deliberately ruled out on its own merits, unrelated to this pinning.
_ASSETS: dict[tuple[str, str], tuple[str, str, str]] = {
    ("Linux", "x86_64"): (
        "obscura-x86_64-linux.tar.gz",
        "9e5d9d081909ea983bc8c94999bb3d411fd6b74a9788504295b7e25f84310505",
        "obscura",
    ),
    ("Linux", "aarch64"): (
        "obscura-aarch64-linux.tar.gz",
        "fd422a9bc0cb38047d270c2d0ee393df5c4d54fa9d0130d39917e858cd7020ae",
        "obscura",
    ),
    ("Darwin", "x86_64"): (
        "obscura-x86_64-macos.tar.gz",
        "a60ad71a9e8d6ab1b8f51d3ddca8e043178b9c03c704719d6e717f77ead3ee43",
        "obscura",
    ),
    ("Darwin", "arm64"): (
        "obscura-aarch64-macos.tar.gz",
        "607471654d0c23799abd3bf45d1f4afd314a11fdbe1ee376e29018f32a2dfab9",
        "obscura",
    ),
    ("Windows", "AMD64"): (
        "obscura-x86_64-windows.zip",
        "db5a3c951f7172eb8f25e6d71bd7120c7128f70f6daed55a6cc4caaabe1674d6",
        "obscura.exe",
    ),
}


class ObscuraUnsupportedPlatformError(RuntimeError):
    """Raised when the running (system, machine) has no pinned asset, or a
    transient error prevented fetching it -- callers treat this as
    "skip bundling", never a hard build failure."""


class ObscuraVerificationError(RuntimeError):
    """Raised when a downloaded archive fails integrity verification (sha256
    mismatch) or doesn't contain the expected binary member. Both indicate a
    corrupted download or a tampered/compromised release, never something to
    silently degrade past -- callers must let this propagate and fail the
    build, unlike ObscuraUnsupportedPlatformError."""


def _platform_key() -> tuple[str, str]:
    return (platform.system(), platform.machine())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _extract_binary(archive: Path, binary_name: str, dest_dir: Path) -> Path:
    dest_binary = dest_dir / binary_name
    try:
        if archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                with zf.open(binary_name) as src, dest_binary.open("wb") as dst:
                    shutil.copyfileobj(src, dst)
        else:
            with tarfile.open(archive, "r:gz") as tf:
                member = tf.getmember(binary_name)
                extracted = tf.extractfile(member)
                if extracted is None:  # pragma: no cover -- defensive, member is a regular file
                    raise ObscuraVerificationError(
                        f"{binary_name} not extractable from {archive.name}"
                    )
                with extracted, dest_binary.open("wb") as dst:
                    shutil.copyfileobj(extracted, dst)
    except KeyError as exc:
        # zf.open()/tf.getmember() raise KeyError for a missing member --
        # e.g. a future obscura release renaming its binary out from under
        # a stale OBSCURA_VERSION/_ASSETS pin. A real integrity problem,
        # not "unsupported platform" -- must not be silently swallowed.
        raise ObscuraVerificationError(
            f"{binary_name!r} not found in {archive.name}: {exc}"
        ) from exc
    if sys.platform != "win32":
        dest_binary.chmod(dest_binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    return dest_binary


def ensure_obscura(vendor_dir: Path) -> Path:
    """Return a verified, executable obscura binary path under *vendor_dir*,
    downloading + verifying it first if not already present.

    Raises ``ObscuraUnsupportedPlatformError`` if the running platform has no
    pinned asset, or if fetching the release fails (network error/non-2xx) --
    callers (visor.spec) must treat both as "skip bundling", not a hard
    build failure. Raises ``ObscuraVerificationError`` (deliberately NOT
    caught by visor.spec) if the download's sha256 doesn't match the pinned
    value, or the archive doesn't contain the expected binary.
    """
    key = _platform_key()
    if key not in _ASSETS:
        raise ObscuraUnsupportedPlatformError(f"no pinned obscura asset for platform {key}")
    asset_name, expected_sha256, binary_name = _ASSETS[key]

    # Versioned path: bumping OBSCURA_VERSION always re-fetches, rather than
    # silently reusing a stale binary already staged under an older pin.
    versioned_dir = vendor_dir / OBSCURA_VERSION
    dest_binary = versioned_dir / binary_name
    if dest_binary.is_file():
        return dest_binary

    versioned_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=versioned_dir) as tmp_dir:
        tmp_path = Path(tmp_dir)
        archive_path = tmp_path / asset_name
        url = f"{_RELEASE_BASE}/{asset_name}"
        try:
            with httpx.stream("GET", url, follow_redirects=True, timeout=120.0) as response:
                response.raise_for_status()
                with archive_path.open("wb") as fh:
                    for chunk in response.iter_bytes():
                        fh.write(chunk)
        except httpx.HTTPError as exc:
            raise ObscuraUnsupportedPlatformError(
                f"failed to fetch {asset_name}: {exc}"
            ) from exc

        actual_sha256 = _sha256(archive_path)
        if actual_sha256 != expected_sha256:
            raise ObscuraVerificationError(
                f"sha256 mismatch for {asset_name}: expected {expected_sha256}, "
                f"got {actual_sha256} -- refusing to stage an unverified binary"
            )

        extracted = _extract_binary(archive_path, binary_name, tmp_path)
        # Verify-then-atomic-rename into the real destination -- never leave
        # a partially-written binary at dest_binary's final path.
        extracted.replace(dest_binary)

    return dest_binary


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dest",
        type=Path,
        default=Path(__file__).resolve().parent.parent.parent / "vendor" / "obscura",
        help="Directory to stage the verified binary into (default: <repo_root>/vendor/obscura)",
    )
    args = parser.parse_args()
    try:
        staged = ensure_obscura(args.dest)
    except (ObscuraUnsupportedPlatformError, ObscuraVerificationError) as exc:
        print(f"obscura not staged: {exc}", file=sys.stderr)
        sys.exit(1)
    print(f"obscura staged at {staged}")
