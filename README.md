# Argus

**A research assistant that answers with citations you can check.**

Argus reads your documents and the open web, then writes research reports where every
claim is traceable back to the source it came from — and says so when it cannot find
the evidence.

[![Python](https://img.shields.io/badge/python-3.12%2B-blue)](<>)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141-teal)](<>)
[![Next.js](https://img.shields.io/badge/Next.js-16-black)](<>)
[![React](https://img.shields.io/badge/React-19-61dafb)](<>)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.6-3178c6)](<>)
[![Tailwind](https://img.shields.io/badge/Tailwind-3.4-38bdf8)](<>)
[![Tests](https://img.shields.io/badge/tests-760%20passed-4c1)](<>)
[![License](https://img.shields.io/badge/license-Proprietary-gray)](<>)

---

## What it does

- **Reads what you give it.** Drop in PDFs, Word documents, saved web pages, Markdown,
  or plain text. Argus extracts the text, splits it into chunks, and indexes it for
  retrieval.
- **Searches two ways at once.** Every query runs against both a vector index
  (semantic matches) and a BM25 index (exact term matches), then the two result lists
  are fused with Reciprocal Rank Fusion. Vector search catches paraphrase; BM25 catches
  the exact product name.
- **Answers with the evidence attached.** Each retrieved passage is numbered. The report
  cites those numbers inline, and a separate verification pass checks that each cited
  sentence actually supports the claim it is attached to.
- **Tells you when it does not know.** If the evidence is missing, thin, or
  contradictory, the report says so instead of padding with plausible-sounding text.
  Search results are deduplicated by URL so the same article shared through three
  different trackers does not read as three independent sources.
- **Streams as it works.** The API streams progress events over SSE, so the UI shows
  the pipeline advancing — decomposing the question, retrieving, cross-checking,
  writing, verifying — rather than a spinner.

## How it works

```
                        ┌──────────────┐
                        │  Supervisor  │  decomposes the question
                        └──────┬───────┘
                    ┌──────────┴──────────┐
                    ▼                     ▼
             ┌─────────────┐       ┌─────────────┐
             │  Researcher │       │   Analyst   │
             │  gathers     │       │  cross-     │
             │  evidence    │       │  checks it  │
             └──────┬──────┘       └──────┬──────┘
                    │                     │
              ┌─────┴─────────────────────┴─────┐
              │          Evidence store           │
              │  vector KNN  +  BM25  →  RRF      │
              │      sqlite-vec        FTS5       │
              └─────────────────┬─────────────────┘
                                ▼
                    ┌───────────────────────┐
                    │  Writer  →  Critic     │
                    │  report      verifies  │
                    └───────────────────────┘
```

Three tools are exposed to the model during a run: `tavily_search` (web),
`local_search` (your uploaded documents), and `dedup` (URL normalization). Tools whose
credentials are not configured are removed from the tool list rather than being
offered and then failing — the agent loop still completes, it just retrieves less.

### Retrieval, specifically

The two retrieval paths produce scores on incompatible scales: vector search yields an
L2 distance, BM25 yields a negative score that drifts with corpus size. Weighting them
requires normalization constants that are unstable across candidate sets. RRF avoids
the problem entirely by fusing on **rank** rather than score:

```
score(d) = Σ  1 / (k + rank_i(d))     k = 60
```

Documents found by both paths score twice — which is the actual benefit of hybrid
retrieval. Vector search understands that "能效" and "能源效率" mean the same thing;
BM25 understands that "H100" is a specific product name.

Relevance filtering uses **cosine** distance, not L2, because L2 is sensitive to
vector magnitude: two vectors pointing the same direction but differing 20× in length
land far apart under L2 and would cross any threshold. The threshold is 0.45,
calibrated over top-20 rather than top-1 — calibrating on top-1 alone rejects
legitimate second-entity evidence.

Note the split, because it is deliberate: `knn_search` still **returns** L2
distance (the existing contract, locked by a named test), while cosine is used only
for **filtering**. Both distances come out of the same KNN query, so ordering is
still driven by L2 and the return-value semantics are unchanged.

## Stack

| Layer      | Choice                                                                             |
| ---------- | ---------------------------------------------------------------------------------- |
| Backend    | Python 3.12+, FastAPI, SQLAlchemy (async), Pydantic v2, Alembic                    |
| Retrieval  | sqlite-vec (vector KNN) + SQLite FTS5 (BM25), fused with RRF                       |
| Embeddings | Alibaba Cloud Bailian `text-embedding-v4`, OpenAI-compatible endpoint, 1536-dim    |
| Agent loop | Hand-written supervisor/agent orchestration — no LangGraph, no LangChain agent     |
| Models     | Anthropic Claude (Sonnet for synthesis, Haiku for analysis), Tavily for web search |
| Frontend   | Next.js 16 (App Router), React 19, TypeScript 5.6, Tailwind v3, shadcn/ui          |
| Shared     | A `@argus/shared` workspace package holding the API contract types                 |
| Tooling    | uv, pnpm workspaces, ruff, mypy (strict), pytest + xdist, ESLint, tsc              |

### Why sqlite-vec and not pgvector

`vectorstore.py` isolates the vector engine behind one interface, with the reason
written down in the module docstring: the development environment has no Postgres. The
contract that a switch to pgvector would have to preserve — that `knn_search` returns
**L2** distance while filtering uses cosine — is captured in a named test
(`test_distance_is_l2_not_cosine`), so the swap is a deliberate change rather than an
accident.

## Numbers

|                 |                                                    |
| --------------- | -------------------------------------------------- |
| Commits         | 159                                                |
| Backend source  | ~12,400 lines across 58 files                      |
| Frontend source | ~140 TypeScript / TSX files                        |
| Tests           | 760 passing, 719 test functions, ~16,600 lines     |
| Test runtime    | 14s wall clock (parallel, `-n 4 --dist=worksteal`) |

## Running it

Backend:

```bash
cd apps/api
uv sync --extra dev
cp .env.example .env        # fill in the API keys you want to use
uv run alembic upgrade head
uv run uvicorn app.main:app --port 8000
```

Frontend:

```bash
pnpm install
pnpm --filter @argus/web dev
```

The web app runs at `http://localhost:3000`, the API at `http://localhost:8000`
(`/docs` for the OpenAPI UI).

### Configuration

Everything is environment-driven through `apps/api/app/config.py`, which is the only
module allowed to read `os.environ` directly. Keys you may want:

| Variable            | Purpose                                        |
| ------------------- | ---------------------------------------------- |
| `ANTHROPIC_API_KEY` | Claude access                                  |
| `TAVILY_API_KEY`    | Web search                                     |
| `EMBEDDING_API_KEY` | Embeddings (Alibaba Bailian)                   |
| `DATABASE_URL`      | SQLAlchemy async URL; defaults to local SQLite |
| `JWT_SECRET_KEY`    | Session signing key                            |

Missing keys degrade gracefully by design: the corresponding tool is dropped from the
tool list, ingestion continues without embeddings, and the run still completes.

## Quality gates

Every push to `master` runs the same gates in CI that run locally:

- **Backend** — `ruff check`, `mypy` in strict mode, and the full `pytest` suite.
- **Frontend** — `eslint`, then `tsc --noEmit`.
- **Preflight** — `pre-commit` hooks run the fast checks (lint + types) before a commit
  is even created, so the expensive gate cannot be skipped by forgetting to run it.

The test suite runs in parallel with `--dist=worksteal`. `loadscope` was tried and
rejected: it groups by module, and with function-level tests that degenerates into
grouping by file, producing badly unbalanced workers and intermittent failures.

Tests never touch the development database. Every test that needs a database gets its
own in-memory SQLite instance and throws it away afterwards, which is what makes the
suite safe to run repeatedly and in parallel.

## Error handling

Errors are classified rather than lumped together, so a user sees what actually
happened rather than a generic 500: upstream rate limits, quota exhaustion, content
filtering, authentication failures, and timeouts each map to a distinct error code.
The distinction matters — a 403 can mean "quota exhausted" or "no access to this
model", and reading only the status code sends the reader to the wrong place.

Failed runs are also written to a ledger so a failure can be diagnosed after the fact
instead of being lost when the process exits.

## License

Proprietary. All rights reserved.
