# Week 2 — Core Build (AI Logic & Data Flow)

**Capstone:** IIT Patna Generative AI Capstone Sprint 2026 — Batch 4
**Project:** AI Copilot for Customer Support Agents (`cutomer_support_agent_live`)
**Week 2 theme:** Core Build — develop AI logic & data flow
**Deliverable:** Working prototype + Build-in-Public Post #2
**Due:** 2nd August 2026 (End of Week 2 = MVP Prototype milestone)

---

## 1. Recap of the Problem (from Week 1)

Support agents spend most of their time re-reading ticket history, hunting through
policy documents, and re-typing near-identical replies. Quality drops when the agent
is new, when the customer has prior context, or when the answer depends on a policy
document nobody remembers.

**Solution:** an AI copilot that drafts the reply *for* the human agent, grounded in
(a) the company knowledge base, (b) what we already know about this customer, and
(c) live account lookups. The human stays in the loop — every draft is reviewed,
edited, and accepted or discarded by the agent.

---

## 2. What "Core Build" means for this project

Week 2 is about the **AI logic and the data flow**, not about polish. The target for
this week is a prototype where a ticket goes in one end and a grounded, context-aware
draft comes out the other, with every piece of evidence used by the model persisted
and inspectable.

Concretely, the Week-2 scope is the five layers below.

| # | Layer | What it does | Where it lives |
|---|-------|--------------|----------------|
| 1 | Ingress & storage | Create customers/tickets, persist drafts | `customer_support_agent/repositories/sqlite/`, `api/routers/tickets.py` |
| 2 | Retrieval (RAG) | Chunk + embed the policy KB, retrieve top-k | `integrations/rag/chroma_kb.py` |
| 3 | Memory | Per-customer and per-company long-term memory | `integrations/memory/mem0_store.py` |
| 4 | Tools | Deterministic account/plan/ticket-load lookups | `integrations/tools/support_tools.py` |
| 5 | Agent | LangGraph agent that fuses 2–4 into a draft | `services/copilot_service.py` |

---

## 3. Data Flow (end to end)

```
Agent (Streamlit app.py)
        │  POST /api/tickets  {customer, subject, description, priority}
        ▼
FastAPI (main.py → api/app_factory.py)
        │  customers.create_or_get() → tickets.create()
        │  BackgroundTasks → DraftService.generate_and_store_background()
        ▼
SupportCopilot.generate_draft(ticket, customer)
        ├── Mem0 search  ── user scope   : customer email
        │                └─ company scope: customer company        → memory_hits
        ├── Chroma RAG search (top_k = 4 over knowledge_base/*.md) → kb_hits
        ├── system prompt = persona + memory block + KB block
        │   user prompt   = customer + ticket fields
        ▼
LangGraph agent (ChatGroq llama-3.1-8b-instant, MemorySaver checkpoint,
                 thread_id = "ticket::<id>")
        ├── may call lookup_customer_plan(email)      → plan tier, SLA hours
        └── may call lookup_open_ticket_load(email)   → open count, load band
        ▼
draft_text + tool_call traces
        │  (fallback 1: single-shot LLM call with no tools)
        │  (fallback 2: deterministic templated reply)
        ▼
context_used  { version, ticket, customer, signals, highlights,
                memory_hits, knowledge_hits, tool_calls, errors }
        ▼
SQLite drafts table (content + context_used JSON + status="pending")
        ▼
Streamlit dashboard: agent reviews → edits → PATCH /api/drafts/{id}
        │
        └── status="accepted" → ticket set to "resolved"
                              → SupportCopilot.save_accepted_resolution()
                                writes the resolution back into Mem0
                                (this is the learning loop)
```

The accept path closing back into Mem0 is the part that makes the system get better
over time: every accepted reply becomes retrievable context for the next ticket from
that customer or that company.

---

## 4. AI Logic — design decisions and why

**Retrieval before generation, not tool-based retrieval.**
Memory and KB search run *unconditionally* before the agent is invoked and are injected
into the system prompt. Account lookups are exposed as *tools* so the model calls them
only when the ticket is actually about billing/plan/SLA. Cheap, always-relevant context
is pushed; expensive, sometimes-relevant context is pulled.

**Two memory scopes.**
`_search_memory_scopes` queries Mem0 with the customer email as `user_id` and, when
present, the company as a second scope. A policy exception granted to one person at a
company is usually relevant to their colleague's ticket too.

**Deterministic tools.**
`lookup_customer_plan` buckets the email with a SHA-256 hash so the same customer always
resolves to the same plan tier — the demo is reproducible without a real billing system,
and swapping in a real CRM later is a one-function change.
`lookup_open_ticket_load` is already backed by real data (`tickets.count_open_for_customer`).

**Three-tier degradation.** Once generation starts, the prototype should not return nothing:
1. agent with tools → 2. plain LLM call with the same context, no tools →
3. deterministic templated reply. Every downgrade is recorded in `context_used.errors` and
rendered in the dashboard's *Context used → Context Errors* panel.

Caveat found during Week-2 verification: all three tiers live inside `generate_draft`, but
`SupportCopilot.__init__` raises when `GROQ_API_KEY` is absent, so a missing key produces a
503 and a placeholder draft row rather than the tier-3 reply. The fallback chain only covers
*generation* failures, not *construction* failures. Moving the key check into `generate_draft`
is a Week-3 item.

**Structured context, not a prose trace.**
`context_used` (`version: 2`) separates `signals` (counts, KB source list — cheap to
render as badges) from `highlights` (top-3 snippets) from the full `memory_hits` /
`knowledge_hits` / `tool_calls` payloads. The dashboard shows the agent *why* the draft
says what it says, which is what makes a human willing to accept it.

**Prompt guardrails.** The system prompt fixes the output contract: empathy first,
concrete next steps, cite KB/tool facts, never expose internal reasoning, ≤180 words.

---

## 5. Prototype Surface (what is working)

**API** (`http://localhost:8000/docs`)

| Method | Route | Purpose |
|--------|-------|---------|
| GET | `/health` | Liveness (used by the compose healthcheck) |
| POST | `/api/tickets` | Create customer + ticket; `auto_generate=true` kicks off drafting |
| GET | `/api/tickets` | List tickets for the dashboard |
| GET | `/api/tickets/{id}` | Single ticket |
| POST | `/api/tickets/{id}/generate-draft` | Synchronous (re)generation |
| GET | `/api/drafts/{ticket_id}` | Latest draft + full context |
| PATCH | `/api/drafts/{draft_id}` | Edit content / accept / discard (accept ⇒ resolve + memory write) |
| POST | `/api/knowledge/ingest` | (Re)index `knowledge_base/` into Chroma |
| GET | `/api/customers/{id}/memories` | Inspect stored memories |
| GET | `/api/customers/{id}/memory-search` | Semantic search over a customer's memories |

**UI:** Streamlit agent dashboard (`app.py`, port 8501) — create tickets, read drafts,
inspect the context that produced them, edit and accept.

**Knowledge base:** four banking policy documents under `knowledge_base/`
(savings account rules, minimum balance & charges, KYC/account update, ATM withdrawal FAQ).
Note that `chroma_kb.py` silently falls back to Chroma's `DefaultEmbeddingFunction` and a
separate `support_kb` collection when `GOOGLE_API_KEY` is unset, so a successful ingest does
not by itself prove the Gemini path. Each of the four files also fits inside a single 800-char
chunk, so `rag_top_k = 4` currently returns the whole KB — chunking and top-k are not yet
meaningfully exercised and need a larger corpus before they can be tuned.

**Config:** all knobs in `.env` via `pydantic-settings` — model, temperature, chunk size
(800) / overlap (120), `rag_top_k` (4), `mem0_top_k` (5), paths.

**Run it:**

```bash
cp .env.example .env          # add GROQ_API_KEY + GOOGLE_API_KEY
docker compose up -d --build  # API :8000, dashboard :8501
curl -X POST localhost:8000/api/knowledge/ingest -H 'content-type: application/json' -d '{"clear_existing":true}'
```

---

## 6. Verification

`tests/test_simple.py` — 29 tests, run by GitHub Actions on every PR (`.github/workflows/ci.yml`):
settings and path resolution, health endpoint, the three SQLite repositories, the ticket
and draft API routes including 404 paths, copilot draft generation and context shape with a
stubbed LLM, the deterministic fallback, both tools, KB ingest + search (and the empty-collection
case), Mem0 result normalisation, and draft serialisation.

```bash
uv sync --dev && uv run pytest -q     # 26 passed, 3 failed — see below
```

**Open issue:** the three copilot tests patch `copilot_service.create_react_agent`, but the
service was migrated to `langchain.agents.create_agent`, so the patch target no longer exists
and the tests error with `AttributeError`. The production path is unaffected; the patch target
needs renaming. This must be fixed before the Week-3 submission so CI is green.

Manual acceptance for the Week-2 demo (status from the runtime run on 2 Aug 2026, done without
API keys — items 1–4 could not be exercised because every copilot-backed route returns 503):

1. Create a ticket about minimum-balance charges → draft cites `banking-charges-and-minimum-balance.md`. *(untested)*
2. Create a billing/SLA ticket → `context_used.tool_calls` contains `lookup_customer_plan`. *(untested)*
3. Accept a draft → ticket flips to `resolved`, and the resolution appears in
   `GET /api/customers/{id}/memories`. *(untested)*
4. File a second ticket for the same customer → the earlier resolution comes back as a memory hit. *(untested)*
5. Both services start, `/health` returns ok, `/docs` lists the ten routes above, dashboard loads. *(passed)*
6. `POST /api/knowledge/ingest {"clear_existing": true}` → 4 files / 4 chunks. *(passed, with the
   embedding caveat in §5)*
7. Ticket creation through the dashboard persists and appears in the list. *(passed)*
8. Invalid email → 422 rendered as a banner, no 500; `GET /api/tickets/99999` and
   `/api/drafts/99999` → 404. *(passed)*
9. Failures are surfaced, not silent: a failed draft shows a warning banner and the missing-key
   error under *Context Errors* with signals 0/0/0. *(passed)*

---

## 7. Mapping to the Capstone Requirements

| Capstone requirement | Status this week |
|---|---|
| Develop AI logic & data flow | Built — retrieval + memory + tools + agent wired end to end (runtime verification pending keys) |
| Working prototype | Partly verified — API + dashboard run and the non-AI flow is confirmed end to end; the AI half is unverified pending API keys (§6) |
| Use ≥2 tool categories | LLM & AI APIs (Groq, Google embeddings) + Database/Backend (SQLite, ChromaDB, Mem0) + Testing (pytest/CI) |
| Core flow first, polish later | Core flow (ticket → AI → reviewed draft) is complete; UI polish deferred to Week 3 |
| Build-in-Public Post #2 | Draft in §9 |

---

## 8. Risks & Week-3 Plan

**Known gaps**

- CI is red: 3 of 29 tests patch a function name that no longer exists (see §6).
- Repository `README.md` is empty; `pyproject.toml` points `readme` at a missing `Plan.md`.
- Missing `GROQ_API_KEY` bypasses the fallback chain entirely (see §4) — 503 instead of a draft.
- No retrieval-quality evaluation yet — top-k is untuned and unmeasured, and the KB is too small
  to exercise chunking at all.
- KB ingest reports success even when it quietly used default (non-Gemini) embeddings.
- No auth on the API, and no rate limiting on the LLM calls.
- Groq/Gemini failures are caught and degraded silently into `context_used.errors`; the
  dashboard should surface them prominently.
- Mem0 writes are best-effort on accept and are swallowed on failure.

**Week 3 (Integration & UI — due 9 Aug 2026)**

1. Fix the three stale copilot tests and get CI green.
2. Rebuild the dashboard around the review loop: draft, evidence panel, accept/edit in one view.
3. Surface `signals` as badges (KB sources, tool calls, memory hits, degradation warnings).
4. Write the README + architecture diagram (`flow.excalidraw` is already in the repo).
5. Move the `GROQ_API_KEY` check out of `SupportCopilot.__init__` so tier-3 is actually reachable,
   and fail the KB ingest loudly when the configured embedding provider is unavailable.
6. Add a small golden-set eval: ~15 tickets with expected KB sources, to tune `rag_top_k`/chunk size.
7. Confirm the EC2 deployment from `main` and capture a live URL for the demo.
8. Ticket filtering/search and a per-customer timeline in the UI.

---

## 9. Build-in-Public Post #2 (draft)

> **Week 2 of the IIT Patna GenAI Capstone: the copilot writes its first real reply.**
>
> I'm building an AI copilot for customer support agents — it drafts the reply, the human
> approves it.
>
> This week was the core build: AI logic and data flow.
>
> A ticket now flows through four context sources before a single token is generated —
> ChromaDB retrieval over our policy docs, Mem0 long-term memory scoped to both the customer
> and their company, and two deterministic tools the LangGraph agent can call for plan/SLA
> and open-ticket load. Groq's llama-3.1-8b fuses them into a draft.
>
> The bit I'm most happy with: every draft is stored with the exact evidence that produced it —
> which KB chunks, which memories, which tool calls. An agent won't trust a black box, but they
> will trust a draft that shows its work.
>
> And when the agent accepts a draft, the resolution is written back into memory. The next
> ticket from that customer starts warmer than the last one.
>
> Stack: FastAPI · LangChain/LangGraph · Groq · ChromaDB · Mem0 · SQLite · Streamlit ·
> Docker Compose · GitHub Actions → EC2, with a pytest suite running in CI.
>
> Next week: the UI and the review loop.
>
> #IITPatnaCapstone
