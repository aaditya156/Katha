# Katha Studio (कथा स्टूडियो)

> **Agentic Multilingual Audio-Story Generation Platform**  
> *Transforming premise into episodic, multi-character, immersive audio dramas across Hindi, Hinglish, and English.*

---

## Overview

Katha Studio is a production-grade platform that coordinates a multi-agent writing room (LangGraph) with multi-character text-to-speech synthesis (TTS) and audio assembly (FFmpeg) to generate complete audio episodes from a simple premise.

This repository implements the architecture and reliability standards defined in [`PROJECT_CONTEXT.md`](PROJECT_CONTEXT.md) and [`AGENTS.md`](AGENTS.md).

---

## Phase 1 Status & Core Deliverables

- [x] **FastAPI Application & Configuration**: Settings management (`pydantic-settings`), CORS, logging, RFC 7807 structured Problem Details error handling.
- [x] **Async Database Layer**: PostgreSQL 16 + `pgvector` with async SQLAlchemy 2.0 (`asyncpg` for production, `aiosqlite` for fast zero-dependency testing).
- [x] **Alembic Database Migrations**: Versioned async migrations for `users`, `series`, and `episodes`.
- [x] **Data Models**: User, Series, and Episode with UUID primary keys and timestamp tracking.
- [x] **JWT Authentication & Security**: Password hashing with `bcrypt`, access & refresh tokens, route protection dependencies (`get_current_active_user`).
- [x] **Multi-Tenant Ownership Enforcement**: Strict user isolation preventing unauthorized access, updates, or deletes across creators.
- [x] **LLM Provider Abstraction**:
  - `BaseLLMProvider` interface with schema-validated structured generation.
  - `GeminiProvider` (Google Gemini with structured outputs).
  - `GroqProvider` (Groq JSON mode with structured outputs).
  - `MockLLMProvider` (Deterministic provider for testing edge cases: timeouts, service overload, malformed JSON, schema repair).
- [x] **Structured Outline Generation**: Beat-by-beat dramatic episode outline generator validating character archetypes, acoustic soundscapes, and conflict beats.
- [x] **React + Vite + TypeScript Frontend**:
  - Sign In (`/login`) & Sign Up (`/register`).
  - Audio Drama Series Dashboard (`/`).
  - Series Creator (`/series/new`).
  - Series Workspace & Outline Generator (`/series/:id`).
  - Styled with Tailwind CSS, custom fonts, dark mode ambiance, and responsive layout.
- [x] **Docker Compose Scaffolding**: PostgreSQL with `pgvector`, Redis 7, Backend, and Frontend.
- [x] **Automated Test Suite**: 19 unit & integration tests passing in isolated test environments.

---

## Project Structure

```
.
├── backend/
│   ├── alembic/              # Database migration scripts
│   ├── app/
│   │   ├── api/              # API routes (auth, series, episodes)
│   │   ├── core/             # Config, security, DB engine, RFC 7807 exceptions
│   │   ├── models/           # SQLAlchemy async models
│   │   ├── providers/        # LLM Provider abstraction (Gemini, Groq, Mock)
│   │   ├── schemas/          # Strict Pydantic v2 domain schemas
│   │   └── main.py           # FastAPI entrypoint
│   ├── tests/                # Pytest async test suite
│   ├── Dockerfile            # Container definition with FFmpeg
│   ├── pyproject.toml        # Backend configuration
│   └── requirements.txt      # Python dependencies
├── frontend/
│   ├── src/
│   │   ├── context/          # Auth context & session state
│   │   ├── pages/            # Login, Register, SeriesList, CreateSeries, SeriesDetail
│   │   ├── services/         # Typed API client with auto-logout & problem details
│   │   ├── types/            # TypeScript schemas aligned with Pydantic
│   │   ├── App.tsx           # Router & protected route setup
│   │   └── main.tsx          # React DOM root
│   ├── Dockerfile            # Multi-stage production container with Nginx
│   └── package.json          # Frontend dependencies
├── docker-compose.yml        # PostgreSQL (pgvector) + Redis + Backend + Frontend
├── .env.example              # Environment variables template
├── AGENTS.md                 # Engineering guidelines & No-Silent-Failure principle
└── PROJECT_CONTEXT.md        # Comprehensive architecture & phased roadmap
```

---

## Quickstart Guide

### 1. Backend Setup

```bash
# Create & activate virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt

# Copy environment variables
cp .env.example .env

# Run database migrations
cd backend
alembic upgrade head

# Start FastAPI development server
uvicorn app.main:app --reload --port 8000
```

API Documentation will be available at: `http://localhost:8000/docs`

### 2. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

Studio UI will be available at: `http://localhost:5173`

### 3. Running via Docker Compose

```bash
docker compose up -d
```

### 4. Running the Automated Test Suite

```bash
source .venv/bin/activate
PYTHONPATH=backend pytest backend/tests -v
```

---

## Next Steps: Phase 2 (LangGraph Agentic Pipeline)
- Build the LangGraph cyclical state graph: `Planner` → `Writer` → `Critic` → `Conditional Revision Edge (max 2)` → `Localizer` (Hindi / Hinglish / English) → `Voice Caster`.
- Wire live progress streaming via Redis Pub/Sub to FastAPI Server-Sent Events (SSE).
