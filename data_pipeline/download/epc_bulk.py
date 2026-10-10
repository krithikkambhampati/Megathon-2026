"""Fast, resumable download of the national domestic EPC CSV zip via the official API.

The API (GET /api/files/domestic/csv) answers with a 302 redirect to a pre-signed S3 URL.
S3 supports HTTP range requests, so we download the file in fixed-size chunks with many
parallel connections (a single browser stream is throttled to a few hundred KB/s).
Chunks are saved as separate part files, so an interrupted run resumes where it left off.
When the signed URL expires (HTTP 403), a fresh one is requested with the bearer token.

Token: copy it from your account page on get-energy-performance-data.communities.gov.uk and
put EPC_API_TOKEN=... in Megathon-2026/.env (git-ignored). The token is never printed.

Usage: python -m data_pipeline.download.epc_bulk [--workers 16]
Output: data/raw/epc/domestic-csv.zip
"""
from __future__ import annotations

import argparse
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "epc" / "domestic-csv.zip"
PARTS = OUT.parent / ".parts"
API = "https://api.get-energy-performance-data.communities.gov.uk/api/files/domestic/csv"
CHUNK = 32 * 1024 * 1024


def load_token() -> str:
    tok = os.environ.get("EPC_API_TOKEN")
    env = ROOT / ".env"
    if not tok and env.exists():
        for line in env.read_text().splitlines():
            if line.strip().startswith("EPC_API_TOKEN="):
                tok = line.split("=", 1)[1].strip().strip('"').strip("'")
    if not tok:
        raise SystemExit("Set EPC_API_TOKEN in Megathon-2026/.env (see module docstring)")
    return tok


class SignedUrl:
    """Thread-safe holder for the pre-signed S3 URL, refreshed on expiry."""

    def __init__(self, token: str):
        self.token = token
        self.lock = threading.Lock()
        self.url = ""
        self.refresh()

    def refresh(self, stale: str | None = None) -> None:
        """Get a new signed URL. If `stale` is given and another thread already replaced it, do nothing."""
        with self.lock:
            if stale is not None and self.url != stale:
                return
            r = requests.get(API, allow_redirects=False, timeout=180,
                             headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"})
            if r.status_code != 302 or "location" not in r.headers:
                raise SystemExit(f"API did not return a download link (HTTP {r.status_code}). "
                                 "Check the token is current.")
            self.url = r.headers["location"]


def total_size(url: str) -> int:
    r = requests.get(url, headers={"Range": "bytes=0-0"}, timeout=60)
    r.raise_for_status()
    return int(r.headers["Content-Range"].split("/")[1])


def fetch_chunk(src: SignedUrl, i: int, start: int, end: int) -> int:
    part = PARTS / f"{i:05d}"
    want = end - start + 1
    if part.exists() and part.stat().st_size == want:
        return 0
    for attempt in range(6):
        try:
            url = src.url
            r = requests.get(url, headers={"Range": f"bytes={start}-{end}"}, stream=True, timeout=120)
            if r.status_code == 403:  # signed URL expired: refresh once, shared by all threads
                src.refresh(stale=url)
                continue
            r.raise_for_status()
            tmp = part.with_suffix(".tmp")
            with tmp.open("wb") as f:
                for b in r.iter_content(1 << 20):
                    f.write(b)
            if tmp.stat().st_size != want:
                raise IOError(f"chunk {i}: got {tmp.stat().st_size} bytes, expected {want}")
            tmp.rename(part)
            return want
        except (requests.RequestException, IOError) as e:
            print(f"  chunk {i} attempt {attempt + 1}: {e}")
            time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"chunk {i} failed repeatedly")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()

    src = SignedUrl(load_token())
    size = total_size(src.url)
    PARTS.mkdir(parents=True, exist_ok=True)
    ranges = [(i, s, min(s + CHUNK, size) - 1) for i, s in enumerate(range(0, size, CHUNK))]
    print(f"file size {size / 1e9:.2f} GB in {len(ranges)} chunks, {args.workers} parallel connections")

    done, t0 = 0, time.time()
    with ThreadPoolExecutor(args.workers) as ex:
        futs = [ex.submit(fetch_chunk, src, *r) for r in ranges]
        for k, fut in enumerate(as_completed(futs), 1):
            done += fut.result()
            if k % 10 == 0 or k == len(futs):
                rate = done / max(time.time() - t0, 1e-6) / 1e6
                print(f"{k}/{len(futs)} chunks, {rate:.1f} MB/s this run")

    with OUT.open("wb") as f:
        for i, _, _ in ranges:
            f.write((PARTS / f"{i:05d}").read_bytes())
    assert OUT.stat().st_size == size, "assembled size mismatch"
    for p in PARTS.iterdir():
        p.unlink()
    PARTS.rmdir()
    print(f"saved {OUT} ({size / 1e9:.2f} GB)")


if __name__ == "__main__":
    main()
