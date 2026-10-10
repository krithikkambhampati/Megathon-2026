"""Download every public dataset listed in sources.yaml into data/raw/<dataset>/.

Idempotent: files that already exist (non-empty) are skipped. Each download is
recorded in data/raw/DOWNLOADS.json with url, size, sha256 and access time so
the data report can cite exactly what was used.

Usage:  python -m data_pipeline.download.download_public [--only ppd,need]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
import yaml

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw"
SOURCES = Path(__file__).with_name("sources.yaml")
LOG = RAW / "DOWNLOADS.json"


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def fetch(url: str, dest: Path, retries: int = 3) -> None:
    tmp = dest.with_suffix(dest.suffix + ".part")
    for attempt in range(1, retries + 1):
        try:
            with requests.get(
                url, stream=True, timeout=120, headers={"User-Agent": "greenhome-megathon/1.0"}
            ) as r:
                r.raise_for_status()
                with tmp.open("wb") as f:
                    for chunk in r.iter_content(1 << 20):
                        f.write(chunk)
            tmp.rename(dest)
            return
        except Exception as e:  # noqa: BLE001 - report and retry any network error
            print(f"  attempt {attempt} failed: {e}", file=sys.stderr)
            time.sleep(5 * attempt)
    raise RuntimeError(f"failed to download {url}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="comma-separated dataset keys")
    args = ap.parse_args()
    only = {s for s in args.only.split(",") if s}

    sources = yaml.safe_load(SOURCES.read_text())
    log = json.loads(LOG.read_text()) if LOG.exists() else {}

    for key, spec in sources.items():
        if only and key not in only:
            continue
        out_dir = RAW / key
        out_dir.mkdir(parents=True, exist_ok=True)
        for item in spec["files"]:
            dest = out_dir / item["name"]
            rel = str(dest.relative_to(RAW))
            if dest.exists() and dest.stat().st_size > 0:
                print(f"skip  {rel}")
                continue
            print(f"fetch {rel}")
            fetch(item["url"], dest)
            log[rel] = {
                "url": item["url"],
                "bytes": dest.stat().st_size,
                "sha256": sha256(dest),
                "accessed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "licence": spec.get("licence", ""),
            }
            LOG.write_text(json.dumps(log, indent=2))
    print("done")


if __name__ == "__main__":
    main()
