# Solution Design & Architecture

## 1. System Overview

The **Customer Support Agent** is an AI-powered copilot that helps human support agents draft responses to customer tickets. When a ticket is created the system automatically:

1. Retrieves relevant past interactions from a per-customer memory store (Mem0 + ChromaDB).
2. Searches a product knowledge base (ChromaDB RAG) for relevant FAQ content.
3. Calls deterministic tools (customer plan lookup, open-ticket load) to gather live context.
4. Runs all of the above through a LangGraph agent backed by a Groq LLM to produce a personalised reply draft.

A human agent reviews the draft in the Streamlit dashboard, edits it if needed, then accepts or rejects it. An accepted draft automatically resolves the ticket and saves the resolution back to the customer's long-term memory so that future tickets benefit from the interaction history.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────────────────────┐
│                          Docker Compose / Host                               │
│                                                                              │
│  ┌─────────────────────────┐          ┌──────────────────────────────────┐  │
│  │   Streamlit Dashboard   │  HTTP    │        FastAPI Backend           │  │
│  │   app.py  :8501         │ ───────► │        main.py  :8000            │  │
│  └─────────────────────────┘          └──────────────┬───────────────────┘  │
│                                                       │                      │
│                         ┌─────────────────────────────┤                     │
│                         │                             │                     │
│                  ┌──────▼──────┐             ┌────────▼────────┐            │
│                  │  SQLite DB  │             │  SupportCopilot │            │
│                  │  support.db │             │  (LangGraph)    │            │
│                  └─────────────┘             └────────┬────────┘            │
│                                                       │                     │
│                              ┌────────────────────────┤                     │
│                              │            │           │                     │
│                       ┌──────▼──┐  ┌──────▼──┐ ┌─────▼──────┐             │
│                       │ Groq API│  │ChromaDB │ │   ChromaDB  │             │
│                       │  LLM    │  │  (RAG)  │ │   (Mem0)    │             │
│                       └─────────┘  └─────────┘ └─────────────┘             │
│                                                                              │
│                                  ┌──────────────────────────┐               │
│                                  │  Google Gemini / OpenAI  │               │
│                                  │  (embedding provider)    │               │
│                                  └──────────────────────────┘               │
└──────────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Layer-by-Layer Breakdown

### 3.1 Presentation — Streamlit Dashboard (`app.py`)

| Responsibility | Detail |
|---|---|
| List tickets | Polls `GET /api/tickets` (cached 10 s via `@st.cache_data`) |
| Create ticket | Posts `POST /api/tickets`; optionally triggers auto-draft |
| View & edit drafts | Fetches draft via `GET /api/drafts/{ticket_id}`, renders context panel |
| Accept / reject | `PATCH /api/drafts/{draft_id}` with `status=accepted\|rejected` |

The dashboard is stateless — it holds no database connection and communicates exclusively over HTTP with the FastAPI backend. `API_BASE_URL` defaults to `http://localhost:8000` and is overridden to `http://api:8000` inside Docker Compose.

### 3.2 API Layer — FastAPI (`customer_support_agent/api/`)

```
app_factory.py       create_app() — registers routers, runs lifespan (DB init)
dependencies.py      FastAPI Depends providers (repositories, services, copilot)
routers/
  health.py          GET /health, GET / → redirect to /docs
  tickets.py         POST /api/tickets, GET /api/tickets, GET /api/tickets/{id}
  drafts.py          GET /api/drafts/{ticket_id}, PATCH /api/drafts/{draft_id}
  knowledge.py       POST /api/knowledge/ingest
  memory.py          GET /api/memory/{customer_id}
```

**Draft generation is asynchronous.** `POST /api/tickets` returns immediately; a `BackgroundTask` calls `DraftService.generate_and_store_background()` so the HTTP response is never blocked by LLM latency.

`SupportCopilot` is a module-level singleton created once via `@lru_cache` in `dependencies.py`. If the Groq API key is absent the factory raises and the dependency returns HTTP 503.

### 3.3 Service Layer (`customer_support_agent/services/`)

| Service | Role |
|---|---|
| `SupportCopilot` | Orchestrates the LangGraph agent; owns `KnowledgeBaseService` and `CustomerMemoryStore` |
| `DraftService` | Serialises drafts; runs background generation; saves accepted resolutions back to memory |
| `KnowledgeService` | Thin wrapper used by the `/api/knowledge/ingest` router |

### 3.4 Repository Layer (`customer_support_agent/repositories/sqlite/`)

All persistence uses a single **SQLite** file (`data/support.db`), accessed through plain `sqlite3` connections (no ORM).

```
base.py        connect(), init_db(), row_to_dict()
customers.py   create_or_get(), get_by_email(), get_by_id()
tickets.py     create(), list(), get_by_id(), set_status(), count_open_for_customer()
drafts.py      create(), get_latest_for_ticket(), get_by_id(), update()
```

`init_db()` is idempotent — called on every app startup via the FastAPI lifespan hook.

### 3.5 Core Settings (`customer_support_agent/core/settings.py`)

`Settings` extends Pydantic `BaseSettings`; all values can be overridden via environment variables or a `.env` file. Key groups:

| Group | Key Variables |
|---|---|
| LLM | `GROQ_API_KEY`, `GROQ_MODEL`, `LLM_TEMPERATURE` |
| Embeddings | `GOOGLE_API_KEY`, `OPENAI_API_KEY`, `ENABLE_LOCAL_EMBEDDINGS` |
| Paths | `DATA_DIR`, `DB_PATH`, `CHROMA_RAG_DIR`, `CHROMA_MEM0_DIR` |
| RAG tuning | `RAG_CHUNK_SIZE`, `RAG_CHUNK_OVERLAP`, `RAG_TOP_K` |
| Memory tuning | `MEM0_TOP_K` |
| Server | `API_HOST`, `API_PORT` |

---

## 4. AI Agent Pipeline

### 4.1 Draft Generation Flow

```
POST /api/tickets
       │
       ▼
   BackgroundTask
       │
       ▼
DraftService.generate_and_store_background()
       │
       ├─► tickets_repo.get_by_id()
       ├─► customers_repo.get_by_id()
       │
       ▼
SupportCopilot.generate_draft(ticket, customer)
       │
       ├─1─► CustomerMemoryStore.search()
       │       └─ Mem0 semantic search in ChromaDB (chroma_mem0)
       │           scopes: [customer_email, company domain]
       │
       ├─2─► KnowledgeBaseService.search()
       │       └─ ChromaDB similarity search (chroma_rag)
       │           top_k = RAG_TOP_K
       │
       ├─3─► Build system prompt (memory + KB context injected)
       │
       ├─4─► LangGraph agent.invoke()
       │       ├─ Tool: lookup_customer_plan(email)
       │       ├─ Tool: lookup_open_ticket_load(email)
       │       └─ Groq LLM generates draft text
       │
       ├─5─► Extract draft text from agent messages
       │       └─ Fallback chain if LLM returns no text:
       │           a) LLM direct call with same context
       │           b) Deterministic template
       │
       └─6─► drafts_repo.create(content, context_used)
```

### 4.2 LangGraph Agent

- **Model**: `ChatGroq` (default `llama-3.1-8b-instant`, configurable)
- **Checkpointer**: `MemorySaver` (in-process; per `thread_id` = `ticket_id + customer_id`)
- **Tools**: `lookup_customer_plan`, `lookup_open_ticket_load` (see §4.3)
- **Recursion limit**: 40 steps

### 4.3 LangChain Tools (`customer_support_agent/integrations/tools/support_tools.py`)

| Tool | Input | Returns |
|---|---|---|
| `lookup_customer_plan` | `customer_email` | Plan tier, SLA hours, priority queue flag. Plan is deterministically bucketed by SHA-256 hash of email (simulates a real CRM lookup) |
| `lookup_open_ticket_load` | `customer_email` | Count of open tickets; load band: `light / moderate / heavy` |

Both tools return structured JSON so the LLM can reason over the data.

### 4.4 Draft Acceptance & Memory Write-back

When a human agent accepts a draft (`PATCH /api/drafts/{id}` with `status=accepted`):

1. The ticket is set to `resolved` in SQLite.
2. A `BackgroundTask` calls `SupportCopilot.save_accepted_resolution()`.
3. The resolution (subject, description, draft, tool-call context) is saved to Mem0 under both the customer's email and company domain user IDs.
4. Future tickets for the same customer or company will retrieve this interaction as memory context.

---

## 5. Knowledge Base (RAG)

**Storage**: ChromaDB persistent collection (`data/chroma_rag/`).  
**Collection name**: `support_kb_gemini` (when `GOOGLE_API_KEY` is set) or `support_kb`.

### Ingestion Pipeline

```
POST /api/knowledge/ingest
       │
       ▼
KnowledgeBaseService.ingest_directory(knowledge_base/)
       │
       ├─► Glob *.md, *.txt
       ├─► RecursiveCharacterTextSplitter
       │       chunk_size=800, overlap=120
       ├─► SHA-1 content hash per chunk → stable doc IDs
       └─► chromadb collection.upsert()
```

### Embedding Provider Selection

| Priority | Condition | Provider |
|---|---|---|
| 1 | `GOOGLE_API_KEY` set | `GoogleGenaiEmbeddingFunction` (`gemini-embedding-001`) |
| 2 | neither | ChromaDB `DefaultEmbeddingFunction` (local `all-MiniLM-L6-v2`) |

---

## 6. Long-Term Memory (Mem0)

**Storage**: ChromaDB persistent collection (`data/chroma_mem0/`).  
**Library**: [Mem0](https://docs.mem0.ai/) configured with Groq as the LLM backend.

### Memory Search

`CustomerMemoryStore.search()` is called with two user IDs per query:

| Scope | user_id |
|---|---|
| Individual | `customer_email` |
| Org-level | company domain extracted from email |

Results are de-duplicated and limited to `MEM0_TOP_K` (default 5).

### Embedding Provider Selection (Mem0)

| Priority | Condition | Provider |
|---|---|---|
| 1 | `GOOGLE_API_KEY` set | Gemini (`gemini-embedding-001`) |
| 2 | `OPENAI_API_KEY` set | OpenAI |
| 3 | `ENABLE_LOCAL_EMBEDDINGS=true` | HuggingFace `all-MiniLM-L6-v2` |
| — | none of the above | Runtime error at startup |

---

## 7. Data Model

```
┌──────────────────────────────────────────────────────────────────┐
│ customers                                                        │
│  id INTEGER PK AUTOINCREMENT                                     │
│  email TEXT UNIQUE NOT NULL                                      │
│  name TEXT                                                       │
│  company TEXT                                                    │
│  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP                  │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 1:N
┌──────────────────────────▼───────────────────────────────────────┐
│ tickets                                                          │
│  id INTEGER PK AUTOINCREMENT                                     │
│  customer_id INTEGER FK → customers(id)                          │
│  subject TEXT NOT NULL                                           │
│  description TEXT NOT NULL                                       │
│  status TEXT DEFAULT 'open'   {open | resolved}                  │
│  priority TEXT DEFAULT 'medium' {low | medium | high | urgent}   │
│  created_at TIMESTAMP                                            │
│  updated_at TIMESTAMP  ← updated by trigger on every UPDATE      │
└──────────────────────────┬───────────────────────────────────────┘
                           │ 1:N
┌──────────────────────────▼───────────────────────────────────────┐
│ drafts                                                           │
│  id INTEGER PK AUTOINCREMENT                                     │
│  ticket_id INTEGER FK → tickets(id)                              │
│  content TEXT NOT NULL                                           │
│  context_used TEXT  (JSON blob — StructuredDraftContext)         │
│  status TEXT DEFAULT 'pending' {pending | accepted | rejected}   │
│  created_at TIMESTAMP                                            │
└──────────────────────────────────────────────────────────────────┘
```

`context_used` serialises a `StructuredDraftContext` (v2) containing:
- `signals` — hit counts for memory, KB, tools
- `highlights` — top memory/knowledge/tool snippets shown in the dashboard
- `memory_hits` / `knowledge_hits` — full retrieved chunks
- `ticket` / `customer` — snapshot at time of generation

---

## 8. API Reference

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Liveness probe |
| `POST` | `/api/tickets` | Create ticket; optionally enqueues background draft |
| `GET` | `/api/tickets` | List tickets (latest 100, joined with customer) |
| `GET` | `/api/tickets/{id}` | Single ticket with customer fields |
| `GET` | `/api/drafts/{ticket_id}` | Latest draft for ticket |
| `PATCH` | `/api/drafts/{draft_id}` | Edit content or update status |
| `POST` | `/api/knowledge/ingest` | Re-ingest `knowledge_base/` into ChromaDB |
| `GET` | `/api/memory/{customer_id}` | List Mem0 memories for a customer |

Interactive Swagger UI: `http://localhost:8000/docs`

---

## 9. Deployment

### Local Development (uv)

```
uv sync
uv run python main.py          # API on :8000
uv run streamlit run app.py    # Dashboard on :8501
```

### Docker Compose

```
docker compose up --build
```

Two services share the same image built from `Dockerfile`:

| Service | Command | Port |
|---|---|---|
| `api` | `.venv/bin/python main.py` | 8000 |
| `dashboard` | `.venv/bin/streamlit run app.py` | 8501 |

Both mount `./data` and `./knowledge_base` as volumes so state persists across container restarts. The `dashboard` service depends on `api` being healthy (curl probe on `/health`, up to 20 retries).

### Dockerfile

- Base: `python:3.11-slim`
- Installs `uv`, syncs dependencies via `uv sync --frozen --no-dev`.
- App code is copied after dependency installation to maximise layer caching.

---

## 10. Key Design Decisions

| Decision | Rationale |
|---|---|
| SQLite over a hosted DB | Zero-ops for a single-node deployment; sufficient for ticket volumes at this scale |
| Async draft generation (BackgroundTask) | Keeps HTTP latency low; LLM calls can take 5–30 s |
| LangGraph over a raw ReAct loop | Built-in checkpointing, structured message history, deterministic tool invocation |
| `@lru_cache` singleton for `SupportCopilot` | LLM client and vector store clients are expensive to construct; one instance per process is safe and efficient |
| Fallback draft chain | Prevents silent failures: agent result → LLM direct call → deterministic template |
| Stable doc IDs in ChromaDB (SHA-1 hash) | Makes ingest idempotent; re-running `POST /api/knowledge/ingest` upserts rather than duplicates |
| Dual memory scope (email + company domain) | Lets the agent benefit from org-level patterns (e.g. all tickets from `acme.com`) without coupling individual user data |
| Embedding provider fallback chain | Runs on any machine — cloud embeddings preferred, local sentence-transformers as last resort |

---

## 11. Directory Reference

```
customer_support_agent/
├── api/
│   ├── app_factory.py      FastAPI app creation and lifespan
│   ├── dependencies.py     Dependency injection providers
│   └── routers/            One file per resource (tickets, drafts, knowledge, memory, health)
├── core/
│   └── settings.py         Pydantic BaseSettings; all config via env vars
├── integrations/
│   ├── memory/
│   │   └── mem0_store.py   Mem0 wrapper: search, list, add memories
│   ├── rag/
│   │   └── chroma_kb.py    ChromaDB RAG: ingest and search knowledge base
│   └── tools/
│       └── support_tools.py LangChain @tool definitions for the agent
├── repositories/sqlite/
│   ├── base.py             Connection factory, init_db(), schema DDL
│   ├── customers.py
│   ├── tickets.py
│   └── drafts.py
├── schemas/
│   └── api.py              Pydantic request/response models
└── services/
    ├── copilot_service.py  LangGraph agent orchestration, prompt building
    ├── draft_service.py    Background generation, serialisation, memory write-back
    └── knowledge_service.py Knowledge base ingestion facade
app.py                      Streamlit dashboard entry point
main.py                     Uvicorn entry point
data/
├── support.db              SQLite database (runtime, gitignored)
├── chroma_rag/             ChromaDB knowledge-base index (runtime, gitignored)
└── chroma_mem0/            ChromaDB memory index (runtime, gitignored)
knowledge_base/             Markdown FAQ documents (source of truth for RAG)
```
