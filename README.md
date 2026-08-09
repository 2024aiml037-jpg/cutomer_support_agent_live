# Customer Support Agent

An AI-powered copilot for support agents that automatically generates reply drafts using LangChain, LangGraph, Mem0, ChromaDB, and Groq LLMs — served via a FastAPI backend and a Streamlit dashboard.

---

## Architecture

```
┌────────────────────────┐      HTTP      ┌──────────────────────────┐
│  Streamlit Dashboard   │ ─────────────► │  FastAPI Backend (8000)  │
│  (app.py  :8501)       │                │  (main.py)               │
└────────────────────────┘                └──────────┬───────────────┘
                                                     │
                  ┌──────────────────────────────────┤
                  │                                  │
           ┌──────▼──────┐                   ┌──────▼──────┐
           │  SQLite DB  │                   │  LangGraph  │
           │  (tickets,  │                   │  Agent      │
           │  customers, │                   │  (SupportCopilot)
           │  drafts)    │                   └──────┬──────┘
           └─────────────┘                         │
                                    ┌──────────────┬┴──────────────┐
                                    │              │               │
                             ┌──────▼──┐    ┌──────▼──┐    ┌──────▼──┐
                             │ Groq LLM│    │ChromaDB │    │  Mem0   │
                             │(llama-3)│    │  (RAG)  │    │(Memory) │
                             └─────────┘    └─────────┘    └─────────┘
```

| Layer | Technology |
|---|---|
| LLM | Groq (llama-3.1-8b-instant) / Google Gemini |
| Agent framework | LangGraph + LangChain |
| Long-term memory | Mem0 + ChromaDB |
| Knowledge base (RAG) | ChromaDB |
| API | FastAPI + Uvicorn |
| UI | Streamlit |
| Database | SQLite |
| Containerisation | Docker / Docker Compose |

---

## Project Structure

```
customer_support_agent/
├── api/            # FastAPI routers, dependencies, app factory
├── core/           # Pydantic settings
├── integrations/
│   ├── memory/     # Mem0 long-term memory store
│   ├── rag/        # ChromaDB knowledge-base service
│   └── tools/      # LangChain tools exposed to the agent
├── repositories/   # SQLite repositories (tickets, customers, drafts)
├── schemas/        # Pydantic API schemas
└── services/       # Business logic (copilot, draft, knowledge)
app.py              # Streamlit dashboard entry point
main.py             # FastAPI / Uvicorn entry point
knowledge_base/     # Markdown FAQ documents ingested into ChromaDB
data/               # Runtime data (SQLite DB, ChromaDB indexes)
```

---

## Prerequisites

| Tool | Version |
|---|---|
| Python | 3.11.x |
| [uv](https://docs.astral.sh/uv/) | latest |
| Docker & Docker Compose | optional, for containerised run |

---

## Quick Start

### 1. Clone and enter the repo

```bash
git clone <repo-url>
cd customer_support_agent_live
```

### 2. Configure environment variables

```bash
cp .env.example .env
# Edit .env and fill in your API keys
```

### 3a. Run with uv (recommended for development)

```bash
# Install dependencies
uv sync

# Start the API server
uv run python main.py

# In a separate terminal, start the dashboard
uv run streamlit run app.py
```

### 3b. Run with Docker Compose

```bash
docker compose up --build
```

Services:
- API: http://localhost:8000  (Swagger UI at http://localhost:8000/docs)
- Dashboard: http://localhost:8501

### 3c. Run with pip / requirements.txt

```bash
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

---

## Environment Variables

Copy `.env.example` to `.env` and fill in the required values.

| Variable | Required | Description |
|---|---|---|
| `GROQ_API_KEY` | Yes | API key for Groq LLM |
| `GOOGLE_API_KEY` | No | Google Gemini API key (for embeddings) |
| `OPENAI_API_KEY` | No | OpenAI API key (optional fallback) |
| `GROQ_MODEL` | No | Groq model name (default: `llama-3.1-8b-instant`) |
| `LLM_TEMPERATURE` | No | LLM temperature (default: `0.2`) |
| `ENABLE_LOCAL_EMBEDDINGS` | No | Use local sentence-transformers instead of Gemini |
| `API_HOST` | No | Host for the FastAPI server (default: `0.0.0.0`) |
| `API_PORT` | No | Port for the FastAPI server (default: `8000`) |

---

## API Reference

Full interactive docs are available at `http://localhost:8000/docs` when the server is running.

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `POST` | `/api/tickets` | Create a support ticket |
| `GET` | `/api/tickets` | List all tickets |
| `GET` | `/api/tickets/{id}` | Get a single ticket |
| `POST` | `/api/drafts/{id}/generate` | Generate an AI reply draft |
| `GET` | `/api/drafts/{id}` | Get the draft for a ticket |
| `POST` | `/api/knowledge/ingest` | Ingest knowledge-base documents |
| `GET` | `/api/memory/{customer_id}` | Retrieve customer memories |

---

## Knowledge Base

Place Markdown FAQ files in the `knowledge_base/` directory and call the `/api/knowledge/ingest` endpoint to index them into ChromaDB.

```bash
curl -X POST http://localhost:8000/api/knowledge/ingest
```

---

## Running Tests

```bash
# Unit / integration tests
uv run pytest tests/

# End-to-end UI tests (requires a running stack)
uv run python tests/e2e/test_dashboard_ui.py --url http://localhost:8501/
```

---

## Development

### Adding new knowledge-base documents

Drop `.md` files into `knowledge_base/` and re-ingest via the API.

### Adding new tools to the agent

Add tool functions in `customer_support_agent/integrations/tools/support_tools.py` and register them via `get_support_tools()`.

---

## License

MIT
