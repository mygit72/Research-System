# Roadmap

Built vertically: every phase ships backend → API → UI (loading, empty, error,
success states) → responsive layout → tests before the next phase starts.

**Phase gate** (must pass before moving on): tests green · lint clean · manual
walkthrough in the browser · docs updated · `PROGRESS.md` updated · commit.

| # | Phase | Delivers | Key interview topics |
|---|---|---|---|
| 1 | **Foundation** | Project structure, config, logging, DB + migrations, auth (JWT + rotating refresh cookies), jobs system, rate limiting, metrics, Docker, CI, design system, app shell, onboarding, settings | Async Python, auth security, API design, observability |
| 2 | **Ingestion & parsing** | Upload (drag & drop, multi-file), validation, dedupe (exact/probable/possible), versioning, parser providers (PDF/DOCX/HTML/MD/TXT), OCR fallback, structure tree, metadata extraction + manual correction, Papers library (grid/list, status, progress), paper page skeleton + reader v1 | Document AI, layout analysis, heuristics vs. ML |
| 3 | **Chunking & embeddings** | 5 chunking strategies, embedding providers (BGE/E5/ST), model manager (CUDA detect, lazy load/unload), content-hash cache, Qdrant (embedded + server), similar papers v1 | Chunking trade-offs, embedding models, vector DBs |
| 4 | **Sparse & hybrid retrieval** | Own BM25, PG FTS, dense retrieval, RRF, filters, Search page (simple/advanced), search-explanation panel | Dense vs. sparse, RRF, filtered ANN |
| 5 | **Reranking** | Cross-encoder + API rerankers, candidate/final-K config, per-stage latency | Precision/latency trade-off |
| 6 | **RAG chat + citations** | LLM providers (OpenAI-compatible, Ollama, local HF), query processor (intent/entities/filters), expansion, context selection (MMR, budget), SSE streaming, citation engine, claim verification, support status, paper chat + global chat, split view (reader + assistant), evidence panel | RAG, hallucination control, verification |
| 7 | **Paper summaries** | Structured summaries (problem → takeaway) with per-section citations, cached by config version | Map-reduce summarization, grounding |
| 8 | **Comparison** | 2–5 paper comparison table ("Not reported"), methodology comparison, export | Structured extraction |
| 9 | **Organization** | Collections, tags, notes (Markdown, anchored to passages), bookmarks, filters by collection/tag | Data modelling |
| 10 | **Knowledge graph & clustering** | Entity extraction (datasets, models, methods, metrics, tasks), NetworkX graph + Neo4j-ready interface, K-Means/HDBSCAN/agglomerative clustering, LLM cluster naming, landscape viz, timeline, author analysis, dataset/model intelligence | Graphs, clustering, entity linking |
| 11 | **Literature review & gaps** | Topic → retrieve → cluster → themes → chronology → disagreements → gaps → cited review; contradiction detection; research-gap detection; editor + export (MD/PDF/DOCX); Deep Research agent (step/token/time budgets) | Agentic RAG, multi-hop, tool calling |
| 12 | **Research Project Builder** | Guided project from an idea: research questions → background (library + literature review) → gap and hypothesis → method plan (datasets, baselines, metrics used by similar papers, with evidence) → experiment and timeline plan → paper outline with citations; one saved, editable project page linked to a collection; export MD / DOCX / LaTeX | Planning with grounded suggestions, structured generation |
| 13 | **Evaluation** | Eval datasets, Recall@K/Precision@K/MRR/nDCG, faithfulness/relevance/citation correctness, A/B of retrievers/embeddings/chunkers/rerankers, experiments, dashboard | IR metrics, LLM-as-judge pitfalls |
| 14 | **Observability & performance** | Redis caching (embeddings, queries, summaries), semantic cache, token/cost tracking with configurable pricing, latency dashboards, Prometheus/Grafana compose profile | Caching, cost control |
| 15 | **Testing & security** | E2E (upload → ask → verify citations), security review, MIME/magic-byte checks, full data export, audit views | Threat modelling |
| 16 | **Polish & deployment** | Accessibility audit, performance (virtualization, code-splitting), demo mode with permissively licensed papers, deployment guide | Production readiness |

> All 16 phases were completed on 2026-10-02 (see PROGRESS.md).
>
> Phase 12 (Research Project Builder) was added on 2026-10-02 at the user's request; the
> later phases moved from 12–15 to 13–16 (session notes before that date use the old numbers).

## Suggested additions (beyond the original spec)

These are proposed extras, slotted into the phase where they fit naturally.

| Addition | Phase | Why it's worth it |
|---|---|---|
| **arXiv / DOI import by URL** (fetch PDF + metadata from arXiv API / Crossref) | 2 | Fastest way to build a library; metadata is authoritative instead of heuristically extracted. |
| **Watch-folder / bulk import (zip)** | 2 | Researchers have folders of PDFs already. |
| **Reference-list parsing → in-library citation links** ("cites" edges between uploaded papers) | 2 / 10 | Turns the reference section into a real citation graph for free. |
| **Retrieval trace persistence ("why this answer?")** saved with every message | 6 | Reproducibility + a great demo of IR engineering. |
| **Answer feedback (👍/👎 + "wrong citation")** stored as labelled data | 6 / 12 | Seeds the evaluation set from real usage; enables active learning later. |
| **Synthetic eval-set generation** (LLM writes questions from chunks, human-verified) | 12 | Evaluation without hand-writing hundreds of questions. |
| **Highlight-to-ask** in the reader (select text → "Explain" / "Find related") | 6 | Signature interaction for the split view. |
| **BibTeX / RIS export** of collections and cited sources | 9 / 11 | Plugs into Zotero, Overleaf, thesis workflows. |
| **Reading status & priority** (to-read / reading / done) | 9 | Makes the library a daily-use tool. |
| **Contextual chunk headers** (prepend "Paper › Section" to each chunk before embedding) | 3 | Cheap, measurable recall improvement — perfect for the A/B dashboard. |
| **HyDE and query decomposition as toggleable strategies** | 6 / 12 | Directly comparable in the evaluation framework. |
| **Weekly digest / "what's new in my library"** | 13 | Uses clustering + recency; good dashboard insight. |
| **Playwright E2E suite in CI** | 14 | Guards the core success criterion (upload → cited answer in minutes). |


## Post-launch additions (2026-10-04)

Found by running the Research Project Builder on two papers that were not in the library
(Contriever, Self-RAG; real models) — see the Session 10 entry in PROGRESS.md.

| Addition | Status | Why |
|---|---|---|
| **Project guidance** — "Next:" card on the project page (first unfinished step, with a link) and warnings: no collection linked, or fewer than 4 papers | ✅ done | With 2 papers the background review and gaps come out thin, and nothing told the user. |
| **arXiv import by id or link** (Papers page → "Import from arXiv"; `POST /documents/import/arxiv`) | ✅ done | Fastest way to fill a project's library, and arXiv's title, authors, abstract and date replace the parser's guesses (authors came back empty on every real PDF). Two fixed hosts only, `LOCAL_ONLY` refuses, size-capped, duplicates skipped. |
| **Step-by-step guide for every project step** (`GET /projects/{id}/guide/{step}`; "How this step works" panel): why, numbered actions with reasons, what you should end up with, how to check it, common mistakes, and what is true of *your* project now | ✅ done | Guidance should explain, not just point. Written once by hand (reviewable, tested); only the "your project" lines vary. |
| **Starter code from the plan** (7th item "Starter code"; `GET /projects/{id}/code`, zip download) — runnable Python project: tested metrics (accuracy, EM, F1, recall/precision/hit@k, MRR, nDCG), toy dataset + SQuAD loader, runner that writes `results.csv`, stubs for *your approach and baselines* annotated with the papers that use them, README walkthrough | ✅ done | Gets the user from plan to results. Not model-written: a 3B model's code is unreliable. Unknown things stay visible TODOs and unimplemented systems/metrics/datasets produce `todo` rows, never numbers. The generated project is run in the tests (smoke run, its own pytest suite). |
| **DOI support** — `POST /documents/import` takes arXiv ids/links *and* DOIs (arXiv DOIs import in full); **"Fill from DOI"** in a paper's details corrects title, authors, abstract, date, venue and DOI from Crossref | ✅ done | A DOI gives metadata, not a PDF, so non-arXiv DOIs are explained ("upload the PDF, then Fill from DOI") rather than guessed. One fixed host (api.crossref.org), `LOCAL_ONLY` refuses, no email sent anywhere. Unpaywall / arbitrary PDF hosts were deliberately left out: they need an outbound-fetch guard (public IPs only, per-redirect checks). |
| **A runnable `YourApproach`** — the starter code's `components.py` has real, tested BM25, DPR, Contriever, a sentence-transformer, reciprocal rank fusion and a cross-encoder reranker (public pretrained checkpoints, nothing trained). Names in the plan map onto them ("DPR", "Contriever", "Contrastive learning", "Hybrid retrieval", "Reranking" …): baselines that map run now, and `YourApproach` becomes a first runnable version assembled from what the user chose to build on, labelled "starter pipeline: …" beside every number, with the unmapped parts listed by name and a marked place to write the actual idea. | ✅ done | A model can't write someone's novel idea, but most of an approach is known parts, and the work of getting an experiment to run end to end is real. Everything unmapped stays an explicit TODO. Verified with the real models (BGE-small, MiniLM cross-encoder, Contriever, DPR) and a full generated project run on real MS MARCO rows. |
| **Starter-code dataset loaders**, verified against the datasets' real schemas (Hugging Face viewer API) and tested on real sample rows: SQuAD, MS MARCO v2.1, HotpotQA (distractor), TriviaQA (rc.nocontext), NQ-Open as "Natural Questions". Names in a plan are matched loosely ("NQ", "ms_marco", "Hotpot QA"). | ✅ done | Pointers said "verify before use", leaving the checking to the user. MS MARCO and HotpotQA are ranking within each question's candidate passages (said so); TriviaQA and NQ-Open have no passages, so retrieval metrics on them become `todo` rows instead of a silent 0. |
| **Zip import** (Papers page → "Import zip"; `POST /documents/import/zip`) — a folder of papers becomes a library in one step, optionally into a new collection ready to start a project from | ✅ done | Researchers already have folders of PDFs. Hostile archives handled: names are labels, never paths; limits on entries (100), per-file size, total bytes *actually read*, expansion ratio; password-protected files and nested archives skipped. Everything left out comes back with the reason. |
| **The outline covers every project paper** — every paper gets introduction evidence (a paper the main search missed gets its own search); related work adds a checked statement + citation for each paper the review text didn't mention (or says none passed the check — never an invented citation); the comparison's "Approach" shows what each paper proposes | ✅ done | The test run's outline, related work and BibTeX cited only one of two papers. |
| Link or change a project's collection from the project page | ✅ done | The guidance told users to add papers, but the collection could only be chosen when the project was created. |
| Sentence splitter no longer breaks after "Mr.", "Dr.", "e.g.", "Fig." … | ✅ done | A suggested question was cut at "datasets such as Mr." (Mr. TyDi). |
| Titles shortened at a word boundary | ✅ done | "…trained without label", "…CRITIQUE THROU". |

### Status of the earlier suggestions (checked against the code)

| Suggestion | Status |
|---|---|
| BibTeX / RIS export; reading status; contextual chunk headers; synthetic eval-set generation; Playwright E2E in CI; retrieval trace saved with every answer; in-library citation links | ✅ built in phases 3, 6, 9, 10, 13 and 15 |
| arXiv import by URL; DOI lookup (Crossref metadata) | ✅ built 2026-10-04 (no PDF download for non-arXiv DOIs) |
| HyDE and query decomposition · weekly digest · answer feedback (👍/👎, "wrong citation") · highlight-to-ask | not built |

### Next, in the order they would help most

0. **Starter code:** more components (ColBERT, query expansion, an answer generator through the project's own LLM providers, a retrieval gate); loaders for BEIR and FEVER (no verified schema yet); a retrieval-from-a-corpus task for the passage-less datasets. An LLM-written first draft of the *novel* part is deliberately not built.
1. **Open-access PDFs for DOIs (Unpaywall)** — only with a guarded outbound fetcher (https, public IPs only, re-checked on every redirect, size cap) and an opt-in `UNPAYWALL_EMAIL`.
2. **Answer feedback** — 👍/👎 and "wrong citation" stored as labelled data for the evaluation sets.
3. **HyDE / query decomposition** as toggles, compared in the evaluation dashboard.
4. **Better introductions from a small model:** the outline now has evidence from every paper, but a 3B model
   writes run-on, subject-less sentences from it. Needs a measured prompt / post-processing change (and a
   larger model via the OpenAI-compatible provider is the real fix).
