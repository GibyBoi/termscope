"""One-time downloader for a small offline Vosk English model.

Usage:
    python -m termscope.download_model           # download the default small model
    python -m termscope.download_model --url URL # use a specific model zip

After this runs once, transcription works fully offline. Downloads land in the
per-user models directory (see `python -m termscope.download_model --where`).
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

from . import paths

DEFAULT_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"


def _progress(block_num: int, block_size: int, total_size: int) -> None:
    if total_size <= 0:
        return
    done = min(block_num * block_size, total_size)
    pct = done * 100 // total_size
    bar = "#" * (pct // 4)
    sys.stdout.write(f"\r  [{bar:<25}] {pct:3d}%  ({done // 1_048_576} MB)")
    sys.stdout.flush()


def download(url: str = DEFAULT_URL) -> Path:
    target_dir = paths.models_dir()
    name = url.rsplit("/", 1)[-1]
    model_name = name[:-4] if name.endswith(".zip") else name
    extracted = target_dir / model_name
    if (extracted / "am").exists():
        print(f"Model already present: {extracted}")
        return extracted

    zip_path = target_dir / name
    print(f"Downloading {url}")
    urllib.request.urlretrieve(url, zip_path, _progress)  # noqa: S310 (trusted vosk host)
    print("\nExtracting...")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(target_dir)
    zip_path.unlink(missing_ok=True)

    if not (extracted / "am").exists():
        # Some archives nest differently; find the real model root.
        for d in target_dir.iterdir():
            if d.is_dir() and (d / "am").exists():
                extracted = d
                break
    print(f"Done. Model installed at: {extracted}")
    return extracted


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download a Vosk model for TermScope.")
    parser.add_argument("--url", default=DEFAULT_URL, help="model .zip URL")
    parser.add_argument("--where", action="store_true", help="print models dir and exit")
    args = parser.parse_args(argv)
    if args.where:
        print(paths.models_dir())
        return 0
    try:
        download(args.url)
    except Exception as exc:  # noqa: BLE001
        print(f"\nDownload failed: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
