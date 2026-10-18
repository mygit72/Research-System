# Run it on your own computer

Your own copy of Research Intelligence, with a language model running on your machine: your
papers, questions and answers never leave it. Any model you pull into Ollama can be used.

## What you need

| | Why | Get it |
|---|---|---|
| Python 3.12+ | the backend | https://www.python.org/downloads/ (Windows: tick “Add python.exe to PATH”) |
| Node.js 20+ | the web interface | https://nodejs.org/ |
| Ollama | runs the language model | https://ollama.com (optional — see “No Ollama?” below) |

About 4 GB of free disk space (PyTorch and the search models ~1 GB, a 3B model ~2 GB) and
8 GB of RAM. A GPU isn't needed; answers on a laptop CPU take 20–40 s with a 3B model.

## Start it

From the project folder:

```bash
# Windows (PowerShell)
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1

# macOS / Linux
./scripts/run-local.sh
```

Then open **http://localhost:5173**, create an account (it lives only in your copy) and press
**Try sample papers** or upload your own.

The first run checks what's installed, writes `backend/.env`, installs the Python and web
packages (several minutes), starts Ollama if it isn't running and downloads the default model
(`qwen2.5:3b`, ~2 GB). Later runs just start the app. To check without changing anything:
`run-local.ps1 -CheckOnly` / `CHECK_ONLY=1 ./scripts/run-local.sh`.

## Use another model

Start with a different one:

```bash
powershell -ExecutionPolicy Bypass -File scripts\run-local.ps1 -Model llama3.2:3b   # Windows
./scripts/run-local.sh llama3.2:3b                                                  # macOS / Linux
```

or pull any model later (`ollama pull mistral`, `ollama pull qwen2.5:7b`, …) and pick it in
**Settings → AI → A model on my computer → Test connection**: the list shows every model you
have. Bigger models answer better and need more memory; 3B–8B models suit most laptops.

For code requests only, you can configure a separate local coder without changing the model used
for ordinary chat. Pull a coder model, then add its exact Ollama name to `backend/.env`:

```dotenv
CODE_LLM_MODEL=qwen2.5-coder:14b
```

The local start script downloads that model if needed. This override is used only when the chat is
already using local Ollama; it never replaces a hosted or shared free model choice. Python code
drafts are checked for syntax, and GPT-from-scratch drafts also get structural checks and up to two
repair attempts. Code requests use `CODE_LLM_CONTEXT_WINDOW` (default 8192); lower it in
`backend/.env` if a large context exceeds your GPU or system memory. The app does not execute
generated code automatically.

After the configured embedding, reranking and verifier checkpoints are cached, set
`HF_HUB_OFFLINE=true` in `backend/.env` to use them without contacting Hugging Face. Set it back
to `false` when you want the app to download a newly selected model.

LM Studio, vLLM or a llama.cpp server work too: choose **Other OpenAI-compatible server** and
give its address (for example `http://localhost:1234/v1`).

## No Ollama? Use an API key

Every copy, yours or a hosted one, can use your own key instead: **Settings → AI → My own API
key**, choose the provider (OpenAI, Gemini, Groq, OpenRouter, Mistral — Gemini, Groq,
OpenRouter's “:free” models and Mistral have free tiers with rate limits), paste the key, press
**Test connection**, pick a model. The key is stored encrypted and never shown again. Free
tiers may use what you send to improve their models: check their terms before sending
unpublished work.

## What is where

- `backend/.env` — your settings (written once; edit it to change the default model). It holds
  a random `JWT_SECRET` that also protects saved API keys: keep it, or saved keys must be
  entered again.
- `backend/data/` — your database, uploaded papers and search index. Back this folder up.
- Stop the app with Ctrl+C in its terminal.

## Running it for other people

A copy reachable by others is a server: see [DEPLOYMENT.md](DEPLOYMENT.md). There, leave
`ALLOW_LOCAL_MODELS` unset (off in production), so the server never connects to addresses on
its own network on a user's behalf; users can still bring their own API keys.
