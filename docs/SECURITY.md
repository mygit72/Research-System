# Security

How the platform protects accounts and data, what each control defends against, and where
it is tested. Reviewed in Phase 15 (2026-10-02).

## Threat model

| Asset | Threat | Main controls |
|---|---|---|
| Accounts | credential stuffing, stolen tokens, session theft | Argon2id, auth rate limit, short-lived access tokens in memory, rotating httpOnly refresh cookies with reuse detection, session list + revoke, security activity log |
| Papers, notes, chats, reports (tenant data) | another user reading or changing them | every query scoped by `user_id`; 404 (not 403) for others' resources; **cross-tenant matrix test over every route** |
| The server | malicious uploads (polyglots, zip bombs), resource exhaustion | extension + magic-byte checks, size limit, DOCX unpacked-size/ratio limit, filename sanitization; rate limits; per-user cap on concurrent answers; job retry cap after crashes |
| Users' browsers | XSS via paper text or model output, clickjacking | no raw HTML rendering anywhere; answer Markdown has no links or HTML; CSP; `X-Frame-Options: DENY` / `frame-ancestors 'none'` |
| The language model | prompt injection from paper text | evidence passed as quoted data; chat has no tools; the deep-research agent has one read-only, user-scoped search tool; output checked against the passages (NLI) and rendered without links |
| Privacy | someone else seeing a user's work; data kept after deletion; data leaving the machine | no admin view, no content in logs, nothing public (see Privacy); account deletion removes rows, files, rendered pages and vectors; full export; `LOCAL_ONLY` refuses remote model providers; the shared free model is opt-in |
| Operations | exposed metrics, vulnerable dependencies | optional `METRICS_TOKEN`; `/metrics` not proxied by nginx; `pip-audit` and `npm audit` in CI |

## Controls

### Authentication and sessions (Phase 1)

| Control | Implementation |
|---|---|
| Password storage | Argon2id (`argon2-cffi`), automatic rehash on login when parameters change. Minimum 10 characters, must mix letters with digits/symbols. |
| Access tokens | HS256 JWT, 30 min TTL (configurable), `type=access` claim enforced, kept only in browser memory. |
| Refresh tokens | 48-byte random opaque tokens; only SHA-256 stored. Delivered as `httpOnly`, `SameSite=Strict`, path-scoped (`/api/v1/auth`) cookie; `Secure` in production. Rotated on every use. |
| Token theft detection | Presenting an already-rotated refresh token revokes every session of that user (persisted even though the request fails). |
| Password change | Revokes all sessions; the current device receives fresh tokens. |
| Session management | Users can list and revoke sessions (device, IP, time). |
| Account enumeration | Identical error for unknown email and wrong password; dummy hash verification equalizes timing. |
| Secrets | Only from environment; `JWT_SECRET` default is rejected in production at startup. `/api/v1/config` exposes only non-secret values. Log processor redacts password/token/api_key fields. |

### Authorization

- Every data query is scoped by `user_id`; other users' resources return **404** — no
  existence leak.
- `tests/test_tenant_isolation.py` reads the OpenAPI schema and, for **every** route with an id
  in its path (67 route/method pairs), sends another user's request for the owner's resource:
  reads and deletes must return 404, writes must never succeed; afterwards the owner's data
  is checked to be intact. A new route fails the test until the fixture creates a resource
  for its id, so endpoints can't silently skip the check. (It found one inconsistency —
  `DELETE /documents/{id}/bookmark` answered 204 for someone else's paper, harmless since it
  only touched the caller's own bookmarks — now 404.)
- Binary assets (`<img src>` can't send a token) use short-lived HMAC-signed URLs, issued only
  for resources the requester owns.

### Uploads

- Extension allow-list, then magic bytes must match (a ZIP renamed `.pdf` is rejected), size
  limit (`MAX_UPLOAD_SIZE_MB`), sanitized filenames, files stored under generated keys.
- **Imports** (`/documents/import`, `/documents/import/zip`, Fill from DOI): outbound requests go only to
  fixed hosts (arxiv.org, export.arxiv.org, api.crossref.org) built from validated identifiers, https
  only, redirects re-checked against the same hosts, response size capped, refused in `LOCAL_ONLY`.
  Nothing the user types becomes a URL, and no email is sent to any service. Open-access PDF hosts for
  arbitrary DOIs are deliberately not fetched (that would need a public-IP-only fetcher).
- **Zip imports**: entry names are labels (last path segment), never paths; at most 100 papers; a
  per-entry size limit and a total limit on bytes actually read (declared sizes aren't trusted);
  entries expanding more than 100:1 skipped; password-protected and nested archives skipped; every
  paper then passes the normal upload checks (extension, magic bytes, size).
- **DOCX zip bombs**: a `.docx` is a zip; one that would unpack to more than 200 MB, or with a
  member compressed more than 100:1, is rejected before parsing (a 4 MB XML of spaces
  deflates to a few KB — ratio ~1000:1; real papers are far below).
- Parsing runs in jobs, not request handlers.

### Browser

- **Content-Security-Policy** for the app (nginx, and `vite preview` with the same value):
  `default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'`.
  No inline scripts; `'unsafe-inline'` for styles only (component libraries inject `<style>`
  tags). The end-to-end test runs against the production build with this policy and fails on
  any console error, so a violation breaks CI.
- API responses: `Content-Security-Policy: default-src 'none'; frame-ancestors 'none'` (they
  are data, never pages) — except `/docs` (Swagger UI) and signed files (a PDF opened in a tab
  keeps the browser's viewer).
- `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`,
  `Permissions-Policy` (no camera / microphone / geolocation). nginx sets them in one included
  file, because a `location` with its own `add_header` drops the server-level ones (the
  `/assets/` location did).
- No `dangerouslySetInnerHTML`; answers, notes and reports render through a small Markdown
  parser that supports emphasis, code, math and citations — no links, no HTML.

### Language models

- Retrieved passages are sent as numbered evidence inside the user message; instructions are
  only in the system prompt. A passage saying "ignore your instructions" can at most change
  the text of an answer, which is then checked claim by claim against the passages and shown
  with its support status.
- Chat calls no tools. The deep-research agent has one tool, a read-only search over the
  user's own papers, with step / token / time limits.
- `LOCAL_ONLY=true` refuses remote LLM, embedding and reranking providers: no document text
  leaves the machine.

### Users' own API keys and models (Settings → AI)

- Keys are write-only. They are encrypted at rest with Fernet (AES-128-CBC + HMAC-SHA256) under
  `MODEL_KEY_SECRET`, or under a key derived from `JWT_SECRET` (HKDF-SHA256) when that is unset.
  API responses carry only the last four characters; audit entries record the provider and model,
  never the key; the data export leaves out the key and its ciphertext; account deletion deletes
  it. Tests: `tests/test_user_models.py`.
- The server has to decrypt a key to call the provider for that user. So "private" means private
  from other users and from anyone holding a copy of the database, not from the server process.
- Hosted presets (OpenAI, Gemini, Groq, OpenRouter, Mistral) are called only at their
  fixed addresses, and the connection test never follows redirects. A user-given address
  (Ollama, a custom OpenAI-compatible server) is accepted only when `ALLOW_LOCAL_MODELS` is on.
  It is off by default in production, so a public server can't be made to connect to its own
  network on a user's behalf (SSRF).
- A user's choice is built only from what they saved: the server's own provider keys are never
  sent to an address a user chose (tested).
- The model in effect is resolved per request and per background job (a context variable set in
  `get_current_user` and in the job runner). Each request runs in its own task, so one user's
  choice can't leak into another user's request. Cache keys include the provider and model, so
  results written by different models are never mixed.
- The connection test is rate-limited like sign-in (`AUTH_RATE_LIMIT_PER_MINUTE`).

### The shared free model (`FREE_TIER`)

- It runs at a third party, so it is opt-in per user: with `FREE_TIER=true` no model is in effect
  for an account until its owner picks the free model, their own key or their own copy. The choice
  is a row like any other model choice (preset `free`), audited, undoable.
- Papers are not summarized on upload while it is the model in effect.
- The site's key goes only to `LLM_API_BASE`; requests carry no user id, email or IP.
- One user can't use up the site's quota: a daily allowance per user and for the site, counted
  from `llm_usage`; calls paced site-wide; refused calls are neither sent nor counted.
- Tests: `tests/test_free_tier.py` (each safeguard was removed in turn to see its test fail) and
  the browser test `frontend/e2e/free/free-model.spec.ts`.

### Abuse and resource limits

- Per-IP rate limits (global API and stricter auth), Redis-backed when configured.
- At most `CHAT_MAX_CONCURRENT_PER_USER` (2) answers streaming per user — each keeps the model
  busy for tens of seconds on a CPU; more get 429 with a hint.
- Jobs interrupted by a crash resume on startup, but a job interrupted 3 times is failed, so a
  file that crashes the process can't put it in a restart loop.

### Privacy

**Who can see a user's papers, questions, notes and answers**

| Who | What they can see | How it is held |
|---|---|---|
| Other users | Nothing | every query scoped by `user_id`; nothing is public and there are no share links |
| An administrator account | Nothing more than any other user | `is_admin` grants no route; the cross-tenant matrix runs a second time as an administrator (`tests/test_tenant_isolation.py`) |
| Someone reading the logs | Ids, routes, timings, error types — no content, no email | `tests/test_private_work.py` captures every log line during sign-up, an upload, a note, a library filter, chat, a summary and a failed answer, and looks for each of them; nginx logs paths without query strings |
| Metrics / Grafana | Counts and timings, never per user | `/metrics` is aggregates; a user's usage is shown only to that user |
| The language model's host | The question and the passages sent to answer it, with nothing identifying the user | local model: nobody. Own key: that provider, under the user's account. Free shared model: its host, and only after the user chose it |
| Whoever runs the server | **Technically everything stored on it** | see below |

The last row is the limit of a hosted site. The server keeps papers, chats and the search index
in readable form, because it has to parse, search and quote them. So the people who run it — and
anyone with its disk or backups — can reach them, even though the app gives them no screen to do
it with. Nothing in this codebase changes that, and the app says so (Settings → Privacy, Help).
The setup in which nobody else can see a user's work, the site's owner included, is their own copy
with a local model (`docs/RUN_LOCALLY.md`): nothing leaves their computer.

Encrypting stored content with a key only the user holds would close that gap for data at rest,
at the price of server-side search, background jobs and password recovery. It is not implemented.

- **Export** (`GET /users/me/export`, Settings → Privacy): a .zip with every row the user owns
  as JSON (secrets excluded: password hash, token hashes) and the original uploads, every
  version; recorded in the activity log.
- **Deletion**: deleting the account deletes each paper through the normal path first, so the
  files, rendered pages and search-index vectors go too (after the commit), then every row via
  cascades. Previously only the rows were deleted — files and vectors stayed on disk; found in
  this review, now tested. Content-addressed caches keyed by text hash (embeddings of passage
  text) are shared and not attributable to a user; they expire with the cache.
- **Security activity** (`GET /users/me/activity`, Settings): sign-ins, failed sign-ins,
  sign-outs, password changes, revoked sessions, token-reuse detection, exports, deleted
  papers — from the audit log (which keeps request id and IP).

### Operations

- `/metrics` carries aggregates only and isn't proxied by nginx; set `METRICS_TOKEN` to
  require `Authorization: Bearer …` where the API port is reachable.
- CI runs `pip-audit` and `npm audit --audit-level=high`. At the Phase 15 review both were
  clean (after updating `setuptools` in the dev environment).
- Error responses never include stack traces; job failures keep technical detail server-side.

## Known limitations

- The per-user concurrency cap and the in-memory caches are per process; with several API
  replicas, use Redis-backed equivalents.
- No antivirus scanning of uploads; files are parsed, never executed or served as HTML.
- No multi-factor authentication or email verification yet.
- Stored content is not encrypted against whoever runs the server (see Privacy).
- The free model's pacing is per process without Redis, and a retried call counts once towards
  the daily numbers although it made several requests.
- Rate limits are per IP: users behind one NAT share them.
