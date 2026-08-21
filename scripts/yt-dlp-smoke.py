#!/usr/bin/env python3
"""Local yt-dlp extractor smoke test.

Downloads a tiny, stable YouTube test video with the pinned Python yt-dlp
package. This intentionally exercises the real extractor and media download
path, not only import/version checks, so dependency updates can be checked
before a broken extractor reaches users.

The argv carries the same hardening flags the application spawns, with one
documented divergence. Since 2026.08.19 YouTube extraction needs the EJS
challenge-solver script to recover signatures and the n parameter. The
official standalone builds Astra downloads and manages ship that script
inside the executable, so ``--no-remote-components`` costs them nothing and
is asserted here against the managed binary. The PyPI wheel does not bundle
it, and under ``--no-remote-components`` every format is filtered out and the
run dies with "Requested format is not available" — so when the smoke runs
the wheel it opts the solver fetch back in instead.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path


DEFAULT_SMOKE_URL = "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
MAX_BYTES = 25 * 1024 * 1024
TIMEOUT_SECONDS = 300
EJS_SOLVER_SOURCE = "ejs:github"


def run_command(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args,
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=TIMEOUT_SECONDS,
        check=False,
    )


def managed_binary_path() -> str:
    """Resolve the managed yt-dlp the application spawns, or an empty string.

    ``--managed`` is the flag npm's smoke:yt-dlp:managed passes; the
    environment variable stays supported so a release run can point at a
    staged build instead of the installed one.
    """
    configured = os.environ.get("ASTRA_YTDLP_SMOKE_BINARY", "").strip()
    if configured:
        return configured
    if "--managed" not in sys.argv[1:]:
        return ""
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if not local_app_data:
        return ""
    return str(Path(local_app_data) / "AstraDownloader" / "yt-dlp.exe")


def uses_managed_binary() -> bool:
    """True when the smoke runs the standalone build, not the wheel."""
    return bool(managed_binary_path())


def hardening_flags() -> list[str]:
    """Mirror YTDLP_HARDENING_FLAGS, minus what the wheel cannot honour."""
    if uses_managed_binary():
        return ["--no-plugin-dirs", "--no-remote-components"]
    return ["--no-plugin-dirs", "--remote-components", EJS_SOLVER_SOURCE]


def yt_dlp_command(*args: str) -> list[str]:
    """Use the managed executable when one is selected."""
    configured = managed_binary_path()
    executable = configured or sys.executable
    prefix = [executable] if configured else [executable, "-m", "yt_dlp"]
    return prefix + list(args)


def main() -> int:
    smoke_url = os.environ.get("ASTRA_YTDLP_SMOKE_URL", DEFAULT_SMOKE_URL)
    managed = managed_binary_path()
    if managed and not Path(managed).is_file():
        sys.stderr.write(
            f"managed yt-dlp not found: {managed}\n"
            "Run the application once so it provisions the managed binary, or set "
            "ASTRA_YTDLP_SMOKE_BINARY to a staged build.\n"
        )
        return 1
    with tempfile.TemporaryDirectory(prefix="astra-ytdlp-smoke-") as tmp:
        output_dir = Path(tmp)
        version = run_command(yt_dlp_command("--version"), output_dir)
        if version.returncode != 0:
            sys.stderr.write(version.stderr or version.stdout)
            return version.returncode or 1

        result = run_command(
            yt_dlp_command(
                *hardening_flags(),
                "--no-playlist",
                "--no-progress",
                "--max-filesize",
                str(MAX_BYTES),
                "-f",
                "worst[filesize<25M]/worst",
                "--paths",
                str(output_dir),
                "-o",
                "%(id)s.%(ext)s",
                smoke_url,
            ),
            output_dir,
        )
        if result.returncode != 0:
            sys.stderr.write(result.stderr or result.stdout)
            return result.returncode or 1

        media_files = [
            path for path in output_dir.iterdir()
            if path.is_file() and path.suffix not in {".part", ".ytdl"}
        ]
        if not media_files:
            sys.stderr.write("yt-dlp smoke produced no media file\n")
            return 1

        largest = max(media_files, key=lambda path: path.stat().st_size)
        size = largest.stat().st_size
        if size <= 0:
            sys.stderr.write(f"yt-dlp smoke produced an empty file: {largest.name}\n")
            return 1
        if size > MAX_BYTES:
            sys.stderr.write(f"yt-dlp smoke exceeded max size: {size} > {MAX_BYTES}\n")
            return 1

        print(json.dumps({
            "ok": True,
            "ytDlpVersion": version.stdout.strip(),
            "url": smoke_url,
            "artifact": largest.name,
            "bytes": size,
            "hardening": hardening_flags(),
            "managedBinary": uses_managed_binary(),
        }, sort_keys=True))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
