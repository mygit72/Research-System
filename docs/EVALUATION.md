# Evaluation

The Evaluation page (`/evaluation`, for technical users) measures how well search finds
the passages that answer a question, how faithful the generated answers are, and what that
costs in time and tokens — on your own papers and questions, so configurations can be
compared on the data that matters to you.

## Datasets

A dataset is a list of questions, each with its **expected evidence**: the passages that
answer it.

- **Expected evidence is stored as spans, not chunk ids**: `document_id`, `version_id`,
  `char_start`/`char_end`, page, title and the quoted text. A retrieved passage counts as
  relevant when it is from the same paper version and overlaps the span — or, after the
  paper was re-processed into a new version, when it contains the start of the quote. So a
  dataset keeps working after you re-chunk or re-embed, which is exactly when you want to
  compare.
- **Adding a question by hand**: write the question, search for the passages that answer it,
  tick them. Only your own passages can be expected evidence.
- **Drafting questions with the model**: the model writes one question per sampled passage,
  and that passage becomes the expected evidence. Passages are sampled round-robin across
  papers (fixed seed), from body text of at least 60 tokens, skipping references,
  acknowledgements, front matter and text that isn't prose (figure labels, table cells:
  fewer than half the words are plain lowercase words — about 5% of passages here, all of
  them figure or table text).
- **Drafts don't count until accepted.** A model-written question can be vague, answerable
  from many places, or about a figure label. Runs use verified questions only; the API
  returns 422 "no verified questions" otherwise.

## Retrieval metrics

Computed per question from the ranked passages, then averaged. `S` is the set of expected
spans; a span is counted once even if several passages cover it.

| Metric | Definition |
|---|---|
| Recall@K | spans covered by the top K / \|S\| |
| Precision@K | relevant passages in the top K / K |
| MRR | 1 / rank of the first relevant passage (0 if none) |
| nDCG@K | DCG with binary gains, where a passage only gains if it covers a span not already covered above it; ideal DCG over min(K, \|S\|) |
| Paper recall@K | expected papers appearing in the top K / expected papers |

Unit tests check the definitions on hand-worked cases and nDCG against scikit-learn's
`ndcg_score` on rankings without duplicate coverage. K ∈ {1, 3, 5, 10} are stored; the
page shows Recall@10, Precision@5, MRR, nDCG@10 and Paper recall@5.

## Answer (RAG) metrics

A RAG run answers each question with the same pipeline as chat (context selection, prompt,
citation validation) and then checks the answer — up to 25 questions per run, since each
takes 20–60 s on a CPU.

| Metric | How |
|---|---|
| Faithfulness | answer split into claims; each claim checked against the passages by the entailment (NLI) model: supported by any passage = 1 (also when it cites the wrong one or none), partial = 0.5 |
| Citation correctness | of the claims that cite a passage, the share whose cited passage supports them (0 when the answer cites nothing) |
| Context recall | expected spans that reached the model's context |
| Context precision | context passages that are expected evidence |
| Answer relevance | cosine similarity of question and answer embeddings — a proxy for "on topic", not for correctness |

Answers that say the passages aren't enough are counted (`insufficient` rate) and left out
of faithfulness, citation correctness and answer relevance rather than scored as 0 or 1.

**Why not an LLM judge?** A 3B local model grading its own answers is the weakest link
there is: it shares the generator's blind spots, is sensitive to answer length and order,
and isn't reproducible across model versions. The NLI model is small, deterministic and
already used to check every chat answer, so the evaluation measures the same thing the
product shows the user. Its limits apply here too: one claim against one passage, so
cross-passage comparisons tend to score as unsupported.

## System metrics

Search latency p50 / p95, total latency per question p50 / p95, throughput (questions per
minute, end to end), input / output tokens, and cost from
`LLM_PRICE_INPUT_PER_MILLION` / `LLM_PRICE_OUTPUT_PER_MILLION` (0 for local models).

## Runs and comparisons

A run fixes a configuration — retriever (BM25 / dense / hybrid), reranking on or off,
candidates per retriever (`top_k`), `rerank_candidates`, RRF `k`, context passages — applied
to a copy of the settings for that run only. The run records a snapshot of everything else
it depended on: papers indexed, embedding model(s), chunking strategy, reranker, LLM and
verifier. Embedding model and chunking are properties of the index, so compare them by
re-indexing and running again; the snapshot shows which index each run used.

Compare (2–4 runs) shows a grouped bar chart of the quality metrics, a table with every
value and the difference from the first run, and the questions where the runs disagree on
finding the expected evidence. With tens of questions, a difference of a few hundredths
is noise; the per-question list shows whether a gap is consistent.

## Walkthrough results (2026-10-02, 12 papers, qwen2.5:3b, CPU)

Question drafting: 12 drafts in 85 s. 8 accepted; rejected: two about figure-label text
(which led to the prose filter above), one not answerable from its passage, one vague.
Plus 2 hand-written questions with two expected passages each — 10 questions.

| Run | Recall@10 | Precision@5 | MRR | nDCG@10 | Search p50 |
|---|---|---|---|---|---|
| Hybrid + rerank | 0.90 | 0.22 | **0.85** | 0.863 | 2030 ms |
| Hybrid, no rerank | 0.90 | 0.22 | 0.75 | 0.789 | 46 ms |
| BM25 | **1.00** | 0.24 | 0.82 | **0.865** | 13 ms |
| Dense | 0.90 | 0.18 | 0.63 | 0.691 | 43 ms |
| Hybrid, RRF k = 10 | 0.90 | 0.22 | 0.75 | 0.789 | 44 ms |

- Reranking moves the relevant passage up (MRR 0.75 → 0.85) at ~2 s per query on CPU.
- BM25 wins on this set — expected for **model-drafted questions, which reuse the passage's
  words**. That's a known bias of synthetic evaluation sets; hand-written paraphrased
  questions are needed before concluding anything about dense retrieval.
- RRF k = 10 vs 60: 5 of 10 top-5 lists changed, but not where the relevant passage was, so
  every metric is identical — the override is applied; the setting just doesn't matter here.

### Answer quality — and what the evaluation found in the checker

RAG run, hybrid + rerank, 10 questions, qwen2.5:3b (~1 question per minute on CPU):

| | Faithfulness | Citation correctness | Context recall | Context precision | Answer relevance | Verify time (10 answers) |
|---|---|---|---|---|---|---|
| First run | 0.13 | 0.22 | 0.85 | 0.15 | 0.72 | 81 s |
| After the fixes below | **0.67** | **0.44** | 0.85 | 0.15 | 0.74 | 112 s |

Reading the answers behind a faithfulness of 0.13 showed that most were right and the
measurement was wrong — three problems, each confirmed before fixing:

1. **The checker missed verbatim claims.** "QLoRA reduces the average memory requirements of
   finetuning a 65B parameter model from >780GB … to <48GB" (copied from its passage) scored
   0.19 in its 60-word window and 0.99 against its own sentence: the small NLI model loses a
   long hypothesis in a multi-sentence premise. Fix (in the shared checker, so chat, summaries
   and reports benefit): a cited claim the windows don't support gets a second look against
   single sentences and sentence pairs of the passages it cites. Offline A/B on the stored
   answers: 0.133 → 0.272 with no score lowered.
2. **The metric ignored "supported, but not cited".** Correct uncited sentences (entailment
   0.99 against a context passage) counted as 0. Faithfulness now counts a claim supported by
   any passage, as chat's verdict does; citation correctness reports the citation problem.
3. **Copied prompt placeholders.** 3 of 10 answers contained the prompt's citation example —
   "<passage 2> [2].", "<statement from passage 1> [1]." — or wrapped content in "<…>". These
   are now removed (with the marker-only sentence they leave) or unwrapped for every answer;
   a reply that was nothing but a placeholder shows "The model's reply had no usable
   statements" in chat.

What is still low, honestly: citation correctness 0.44 (the 3B model often writes correct
sentences without markers), context precision 0.15 (8 passages per answer, typically 1–2
expected — by design the context is broad), and one question ("What datasets were used …")
whose answer was a list of passage headers. Context recall 0.85 means the expected passage
reached the model for most questions, so remaining failures are mostly generation, not
retrieval.
