"""Load a BEIR-format dataset (corpus.jsonl, queries.jsonl, qrels/<split>.tsv)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True, frozen=True)
class CorpusDoc:
    doc_id: str
    title: str
    text: str


def load_corpus(data_dir: Path) -> list[CorpusDoc]:
    docs = []
    with open(data_dir / "corpus.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            docs.append(CorpusDoc(row["_id"], row.get("title", ""), row.get("text", "")))
    return docs


def load_queries(data_dir: Path) -> dict[str, str]:
    queries = {}
    with open(data_dir / "queries.jsonl", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            queries[row["_id"]] = row.get("text", "")
    return queries


def load_qrels(data_dir: Path, split: str = "test") -> dict[str, set[str]]:
    qrels: dict[str, set[str]] = {}
    path = data_dir / "qrels" / f"{split}.tsv"
    with open(path, encoding="utf-8") as f:
        next(f)  # header: query-id corpus-id score
        for line in f:
            qid, docid, score = line.rstrip("\n").split("\t")
            if int(score) > 0:
                qrels.setdefault(qid, set()).add(docid)
    return qrels
