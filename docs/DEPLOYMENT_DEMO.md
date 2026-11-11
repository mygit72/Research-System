# Research Intelligence — Public Demo Deployment Guide (₹0/Month)

This guide documents the exact steps to deploy a publicly accessible demonstration of **Research Intelligence** with a long-lived **₹0/month budget**.

---

## Architecture Overview

* **Frontend:** Vercel Hobby Tier (React 19 + TypeScript + Vite)
* **Backend:** Render Free Web Service (FastAPI container, `JOB_BACKEND=inline`)
* **Database & Vector Store:** Neon Serverless PostgreSQL with `pgvector`
* **AI Provider:** NVIDIA API (`integrate.api.nvidia.com`) using server-side NVAPI key
* **Research Dataset:** Shared synthetic research library preloaded and indexed under `DEMO_USER_ID`

---

## 1. Neon PostgreSQL Database & pgvector Setup

Neon provides a free serverless PostgreSQL database with 0.5 GB storage that autosuspends when idle and never expires after 30 days.

1. Sign up for a free account at [neon.tech](https://neon.tech) (no credit card required).
2. Create a new project named `research-intelligence-demo`.
3. In the Neon Console SQL Editor, verify that the `pgvector` extension is available:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```
4. Copy your pooled connection string from the Neon dashboard. It looks like:
   `postgresql://neondb_owner:YOUR_PASSWORD@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb?sslmode=require`
5. Format the connection string for SQLAlchemy's asyncpg driver by prefixing `postgresql+asyncpg://`:
   `postgresql+asyncpg://neondb_owner:YOUR_PASSWORD@ep-xyz-pooler.us-east-2.aws.neon.tech/neondb?ssl=require`

---

## 2. Render Backend Deployment

1. Sign up for a free account at [render.com](https://render.com).
2. Click **New +** -> **Web Service**.
3. Connect your GitHub repository: `https://github.com/mygit72/Research-System`.
4. Configure service settings:
   * **Name:** `research-intelligence-backend`
   * **Language / Environment:** `Docker`
   * **Dockerfile Path:** `./infra/docker/backend.Dockerfile`
   * **Docker Context:** `.`
   * **Instance Type:** `Free` (0.1 CPU, 512 MB RAM)
   * **Health Check Path:** `/health`
5. Configure the Environment Variables in the Render dashboard:

| Variable | Value / Description |
| :--- | :--- |
| `ENVIRONMENT` | `production` |
| `DEBUG` | `false` |
| `APP_NAME` | `Research Intelligence` |
| `JOB_BACKEND` | `inline` |
| `INLINE_JOB_CONCURRENCY` | `1` |
| `VECTOR_STORE` | `pgvector` |
| `DEMO_MODE` | `true` |
| `UPLOADS_ENABLED` | `false` |
| `GITHUB_URL` | `https://github.com/mygit72/Research-System` |
| `RERANKER_PROVIDER` | `lexical` |
| `WARM_MODELS_ON_STARTUP` | `false` |
| `MODEL_DEVICE` | `cpu` |
| `FREE_TIER` | `true` |
| `FREE_TIER_LABEL` | `NVIDIA Nemotron` |
| `FREE_TIER_HOST` | `NVIDIA NIM` |
| `LLM_PROVIDER` | `openai` |
| `LLM_API_BASE` | `https://integrate.api.nvidia.com/v1` |
| `LLM_MODEL` | `nvidia/nemotron-3-ultra-550b-a55b` |
| `LLM_EXTRA_BODY` | `{"chat_template_kwargs": {"enable_thinking": false}}` |
| `DATABASE_URL` | Your Neon connection string (`postgresql+asyncpg://...`) |
| `OPENAI_API_KEY` | Your NVIDIA API key (`nvapi-...`) |
| `JWT_SECRET` | 32+ character random secret (Render can generate this) |
| `CORS_ORIGINS` | `["https://your-app.vercel.app"]` (update once Vercel URL is known) |

6. Click **Deploy Web Service**.
   * On startup, Alembic automatically runs all migrations, creates the `vector_points` table, and indexes the three synthetic sample papers into Neon.
   * Render assigns a public URL: `https://research-intelligence-backend.onrender.com`.

---

## 3. Vercel Frontend Deployment

1. Sign up or log in at [vercel.com](https://vercel.com).
2. Click **Add New...** -> **Project** and import `https://github.com/mygit72/Research-System`.
3. In the project settings:
   * **Framework Preset:** Vite
   * **Root Directory:** `frontend`
4. Add the following Environment Variable in Vercel:
   * `VITE_API_DIRECT_URL`: `https://research-intelligence-backend.onrender.com`
5. Deploy.
6. Once deployed, note your Vercel URL (e.g. `https://research-intelligence-demo.vercel.app`) and update `CORS_ORIGINS` in your Render backend settings.

---

## 4. Demo Verification & Features Checklist

Once deployed, visit your Vercel URL. You should see:
1. **Demo Badge:** A visible "Demo Mode • GitHub" badge in the header linking to the GitHub repository.
2. **Preloaded Research Papers:** The three synthetic conference papers:
   * *Hybrid Sparse-Dense Retrieval for Scientific Question Answering*
   * *Low-Rank Adapters for Efficient Domain Adaptation of Language Models*
   * *RAG Adapters for Domain-Specific Scientific Retrieval*
3. **Hybrid Search:** Search queries (e.g., "reciprocal rank fusion") retrieve relevant sections combining BM25 lexical ranking and pgvector dense cosine similarity.
4. **AI Research Chat:** Clicking suggested questions streams answers powered by NVIDIA Nemotron with exact citations.
5. **Upload Protection:** Clicking "Upload" displays an explanation informing visitors that uploads are disabled in the public demo, providing a link to run the complete version locally.

---

## 5. Free-Tier Characteristics & Troubleshooting

### Cold Starts
* **Render Web Service:** Render free instances spin down after 15 minutes of zero traffic.
* **Wake-Up Latency:** The first request takes ~50–70 seconds while the container initializes. Subsequent requests respond in < 100 ms.
* **Frontend Handling:** The frontend displays an informative loading state during initial wake-up.

### Inactivity & Suspension Policies
* **Neon PostgreSQL:** Neon scales compute to 0 when idle and wakes in < 1 second. Neon free databases **do not expire after 30 days** (unlike Render's internal PostgreSQL).
* **Render Free:** Provides 750 free instance hours per month, sufficient to keep 1 service running indefinitely.
* **Vercel Hobby:** Generous free-tier bandwidth (100 GB/month) with zero cold starts for static assets.

