"""Download the *original* SciFact release (claims with SUPPORT/CONTRADICT labels and
cited evidence sentences) — a different file from the BEIR corpus/queries/qrels used by
run_benchmark.py. BEIR's qrels.tsv only has binary relevance, not verification labels;
this is what claim_verification.py needs.

Source: https://github.com/allenai/scifact (schema: doc/data.md).
"""

from __future__ import annotations

import argparse
import sys
import tarfile
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data" / "scifact_claims"
URL = "https://scifact.s3-us-west-2.amazonaws.com/release/latest/data.tar.gz"


def download(data_dir: Path = DATA_DIR, force: bool = False) -> Path:
    target = data_dir / "data"
    if target.exists() and not force and (target / "claims_dev.jsonl").exists():
        print(f"[download_claims] already present at {target}")
        return target
    data_dir.mkdir(parents=True, exist_ok=True)
    archive = data_dir / "data.tar.gz"
    print(f"[download_claims] fetching {URL}")
    urllib.request.urlretrieve(URL, archive)  # noqa: S310 - fixed, known host
    print(f"[download_claims] extracting -> {data_dir}")
    with tarfile.open(archive) as tf:
        tf.extractall(data_dir, filter="data")
    archive.unlink(missing_ok=True)
    if not (target / "claims_dev.jsonl").exists():
        raise RuntimeError(f"expected {target / 'claims_dev.jsonl'} after extraction")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    path = download(force=args.force)
    print(f"[download_claims] ready: {path}")


if __name__ == "__main__":
    sys.exit(main())
