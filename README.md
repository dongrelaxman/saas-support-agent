# saas-support-agent

> AI-powered customer support agent built with LangGraph — answers questions from your own knowledge base, hedges when uncertain, and escalates to a human with full context when needed.

---

## How it works

```
User message
    │
    ▼
RAG retrieval (Weaviate)
    │
    ├── score ≥ 0.75  →  Answer (streamed via SSE)
    ├── score < 0.75  →  Hedge / ask clarifying question
    │   └── 3 low-conf in a row  →  Escalate
    └── "talk to human"  →  Escalate immediately
                                │
                                ▼
                    Support ticket created
                    Slack alert fired
                    Agent console notified (WebSocket)
```

Conversation memory is persisted in Postgres via LangGraph's `PostgresSaver` checkpointer — users pick up exactly where they left off across sessions.

---

## Tech stack

| Layer | Technology |
|---|---|
| Agent runtime | LangGraph `StateGraph` with `interrupt` / `resume` |
| LLM | GPT-4o-mini (chat + intent) |
| Vector search | Weaviate (cosine similarity, `text-embedding-3-small`) |
| Memory | Postgres (`PostgresSaver` checkpointer) |
| API | FastAPI — SSE streaming + WebSocket console |
| Frontend | React + Tailwind CSS + Vite |
| Infra | GCP Cloud Run + Cloud SQL + Artifact Registry |
| CI | GitHub Actions — eval gate (F1 ≥ 0.80) |
| CD | GitHub Actions — auto-deploy on merge to `main` |

---

## Project structure

```
├── backend/
│   ├── Dockerfile
│   ├── api.py          # FastAPI endpoints (SSE, WebSocket, REST)
│   ├── graph.py        # LangGraph StateGraph definition
│   ├── nodes.py        # retrieve, answer, pause, handoff nodes
│   ├── state.py        # SupportState TypedDict
│   ├── db.py           # Postgres connection + schema
│   ├── memory.py       # Conversation summarisation
│   ├── handoff.py      # Ticket creation + Slack alert
│   └── prompts.py      # LLM prompt templates
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf.template
│   └── src/
│       └── pages/
│           ├── ChatPage.tsx      # User chat interface (SSE streaming)
│           └── ConsolePage.tsx   # Agent console (WebSocket)
├── kb/                 # Knowledge base Markdown files (12 articles)
├── scripts/
│   ├── ingest.py       # Ingest KB into Weaviate
│   └── eval.py         # Eval suite — 50 questions, F1 gate
├── eval/               # Eval dataset (CSV + multi-turn scenarios)
├── deploy/
│   └── gcp.sh          # One-command GCP Cloud Run deploy
├── .github/workflows/
│   ├── eval.yml        # CI — runs eval on every PR
│   └── deploy.yml      # CD — deploys to Cloud Run on merge to main
├── docker-compose.yaml # Local full-stack (postgres + backend + frontend)
├── config.yaml         # Thresholds, model names, Weaviate collection
└── requirements-prod.txt
```

---

## Local setup

### Prerequisites
- Docker + Docker Compose
- An `.env` file with your API keys (see `.env.example`)

### Run

```bash
cp .env.example .env   # fill in your keys
docker compose up --build
```

- Frontend: http://localhost:3000
- Backend API: http://localhost:8001

### Ingest the knowledge base

```bash
pip install -r requirements-prod.txt
python scripts/ingest.py
```

---

## Environment variables

| Variable | Description |
|---|---|
| `OPENAI_API_KEY` | OpenAI API key |
| `WEAVIATE_URL` | Weaviate cluster URL |
| `WEAVIATE_API_KEY` | Weaviate API key |
| `LANGCHAIN_API_KEY` | LangSmith tracing key |
| `SLACK_WEBHOOK_URL` | Slack incoming webhook for escalation alerts |
| `DATABASE_URL` | Postgres connection string |

---

## CI / CD

**CI (`eval.yml`)** — runs on every PR that touches `backend/`, `kb/`, or `config.yaml`:
- Ingests the KB into a test Weaviate instance
- Runs 50-question eval suite
- Blocks merge if F1 < 0.80

**CD (`deploy.yml`)** — runs on every merge to `main`:
- Builds and pushes Docker images to GCP Artifact Registry (with layer caching)
- Deploys backend to Cloud Run (Cloud SQL proxy, Secret Manager refs)
- Deploys frontend to Cloud Run with `BACKEND_URL` injected at runtime

Uses Workload Identity Federation — no long-lived service account keys stored in GitHub.

### Required GitHub secrets

| Secret | Description |
|---|---|
| `WIF_PROVIDER` | Workload Identity Federation provider |
| `WIF_SERVICE_ACCOUNT` | GCP service account email |
| `GCP_PROJECT` | GCP project ID |
| `DB_PASS` | Cloud SQL postgres password |

App secrets (`OPENAI_API_KEY`, `WEAVIATE_*`, etc.) live in **GCP Secret Manager** — not GitHub.

---

## GCP one-time setup

See the comments at the bottom of `.github/workflows/deploy.yml` for the full Workload Identity Federation setup commands.

Estimated running cost: **~$12–30/month** (Cloud SQL dominates at ~$10/month; Cloud Run scales to zero when idle).

---

## Eval

```bash
python scripts/eval.py
```

Runs 50 single-turn questions + 6 multi-turn conversation scenarios. Prints per-question results and a final F1 score. Exits with code `1` if F1 < 0.80.

Cost per run: ~$0.02.
