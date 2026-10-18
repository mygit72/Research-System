"""Download a BEIR retrieval dataset (default: SciFact) into eval/beir/data/.

Standalone: stdlib only (urllib + zipfile), no extra dependencies.
"""

from __future__ import annotations

import argparse
import sys
import urllib.request
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA_DIR = HERE / "data"
BASE_URL = "https://public.ukp.informatik.tu-darmstadt.de/thakur/BEIR/datasets/{name}.zip"


def download(dataset: str, data_dir: Path = DATA_DIR, force: bool = False) -> Path:
    target = data_dir / dataset
    if target.exists() and not force and (target / "corpus.jsonl").exists():
        print(f"[download] {dataset} already present at {target}")
        return target
    data_dir.mkdir(parents=True, exist_ok=True)
    zip_path = data_dir / f"{dataset}.zip"
    url = BASE_URL.format(name=dataset)
    print(f"[download] fetching {url}")
    urllib.request.urlretrieve(url, zip_path)  # noqa: S310 - fixed, known BEIR host
    print(f"[download] extracting {zip_path} -> {data_dir}")
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(data_dir)
    zip_path.unlink(missing_ok=True)
    if not (target / "corpus.jsonl").exists():
        raise RuntimeError(f"expected {target / 'corpus.jsonl'} after extraction")
    return target


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", default="scifact")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    path = download(args.dataset, force=args.force)
    print(f"[download] ready: {path}")


if __name__ == "__main__":
    sys.exit(main())
