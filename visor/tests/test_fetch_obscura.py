"""Tests for visor.installer.fetch_obscura -- the build-time vendoring step
that stages the (optional, non-pip) obscura headless-render binary into a
frozen Visor build. No network/real download here: httpx.stream is mocked
throughout, using small real archives built in-memory so the tar/zip
extraction + sha256 verification logic is exercised for real.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import tarfile
import zipfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from visor.installer.fetch_obscura import (
    OBSCURA_VERSION,
    ObscuraUnsupportedPlatformError,
    ObscuraVerificationError,
    _sha256,
    ensure_obscura,
)


def _make_tar_gz(binary_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        info = tarfile.TarInfo(name=binary_name)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _make_zip(binary_name: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(binary_name, content)
    return buf.getvalue()


@contextlib.contextmanager
def _mock_stream_response(body: bytes):
    response = MagicMock()
    response.raise_for_status = MagicMock()
    response.iter_bytes = MagicMock(return_value=iter([body]))
    yield response


class TestEnsureObscura:
    def test_unsupported_platform_raises(self, tmp_path: Path) -> None:
        with patch(
            "visor.installer.fetch_obscura._platform_key",
            return_value=("Plan9", "risc-v"),
        ):
            with pytest.raises(ObscuraUnsupportedPlatformError, match="no pinned obscura asset"):
                ensure_obscura(tmp_path)

    def test_returns_existing_binary_without_network_call(self, tmp_path: Path) -> None:
        versioned = tmp_path / OBSCURA_VERSION
        versioned.mkdir(parents=True)
        (versioned / "obscura").write_bytes(b"already staged")
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Linux", "x86_64")
        ), patch("visor.installer.fetch_obscura.httpx.stream") as mock_stream:
            result = ensure_obscura(tmp_path)
        mock_stream.assert_not_called()
        assert result == versioned / "obscura"
        assert result.read_bytes() == b"already staged"

    def test_network_failure_raises_unsupported_platform_not_verification_error(
        self, tmp_path: Path
    ) -> None:
        """A transient fetch failure (GitHub outage, rate limit, ...) must
        degrade to "skip bundling" (ObscuraUnsupportedPlatformError), the
        same as an unpinned platform -- not ObscuraVerificationError, which
        visor.spec deliberately does NOT catch and would hard-fail the
        build over a problem that has nothing to do with the binary's
        integrity."""
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Linux", "x86_64")
        ), patch(
            "visor.installer.fetch_obscura.httpx.stream",
            side_effect=httpx.ConnectError("connection refused"),
        ):
            with pytest.raises(ObscuraUnsupportedPlatformError, match="failed to fetch"):
                ensure_obscura(tmp_path)
        assert not (tmp_path / OBSCURA_VERSION / "obscura").exists()

    def test_sha256_mismatch_raises_verification_error_and_does_not_stage(
        self, tmp_path: Path
    ) -> None:
        archive = _make_tar_gz("obscura", b"fake binary content")
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Linux", "x86_64")
        ), patch(
            "visor.installer.fetch_obscura._ASSETS",
            {("Linux", "x86_64"): ("obscura-x86_64-linux.tar.gz", "0" * 64, "obscura")},
        ), patch(
            "visor.installer.fetch_obscura.httpx.stream",
            return_value=_mock_stream_response(archive),
        ):
            with pytest.raises(ObscuraVerificationError, match="sha256 mismatch"):
                ensure_obscura(tmp_path)
        assert not (tmp_path / OBSCURA_VERSION / "obscura").exists()

    def test_missing_archive_member_raises_verification_error(self, tmp_path: Path) -> None:
        """A future obscura release renaming its binary out from under a
        stale pin must surface as a verification problem, not vanish as an
        uncaught KeyError (which visor.spec's except clause wouldn't catch
        either, but for the wrong reason)."""
        archive = _make_tar_gz("some-other-name", b"fake binary content")
        real_sha256 = hashlib.sha256(archive).hexdigest()
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Linux", "x86_64")
        ), patch(
            "visor.installer.fetch_obscura._ASSETS",
            {("Linux", "x86_64"): ("obscura-x86_64-linux.tar.gz", real_sha256, "obscura")},
        ), patch(
            "visor.installer.fetch_obscura.httpx.stream",
            return_value=_mock_stream_response(archive),
        ):
            with pytest.raises(ObscuraVerificationError, match="not found in"):
                ensure_obscura(tmp_path)

    def test_successful_tar_gz_fetch_verifies_and_extracts(self, tmp_path: Path) -> None:
        content = b"#!/bin/sh\necho fake obscura\n"
        archive = _make_tar_gz("obscura", content)
        real_sha256 = hashlib.sha256(archive).hexdigest()
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Linux", "x86_64")
        ), patch(
            "visor.installer.fetch_obscura._ASSETS",
            {("Linux", "x86_64"): ("obscura-x86_64-linux.tar.gz", real_sha256, "obscura")},
        ), patch(
            "visor.installer.fetch_obscura.httpx.stream",
            return_value=_mock_stream_response(archive),
        ):
            result = ensure_obscura(tmp_path)
        assert result == tmp_path / OBSCURA_VERSION / "obscura"
        assert result.read_bytes() == content
        assert result.stat().st_mode & 0o111  # executable bit set

    def test_successful_zip_fetch_verifies_and_extracts(self, tmp_path: Path) -> None:
        content = b"fake windows exe bytes"
        archive = _make_zip("obscura.exe", content)
        real_sha256 = hashlib.sha256(archive).hexdigest()
        with patch(
            "visor.installer.fetch_obscura._platform_key", return_value=("Windows", "AMD64")
        ), patch(
            "visor.installer.fetch_obscura._ASSETS",
            {("Windows", "AMD64"): ("obscura-x86_64-windows.zip", real_sha256, "obscura.exe")},
        ), patch(
            "visor.installer.fetch_obscura.httpx.stream",
            return_value=_mock_stream_response(archive),
        ):
            result = ensure_obscura(tmp_path)
        assert result == tmp_path / OBSCURA_VERSION / "obscura.exe"
        assert result.read_bytes() == content


class TestSha256Helper:
    def test_matches_hashlib_directly(self, tmp_path: Path) -> None:
        f = tmp_path / "data.bin"
        f.write_bytes(b"some content to hash")
        assert _sha256(f) == hashlib.sha256(b"some content to hash").hexdigest()
