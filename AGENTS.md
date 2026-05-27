# AGENTS.md

This file provides guidance to Codex (Codex.ai/code) when working with code in this repository.

## Project overview

**CampusFoodAgent** (成电吃什么 Agent) is an intelligent campus food recommendation system for UESTC (电子科技大学). It combines a rule-based scoring engine with AI (讯飞 Spark LLM) hybrid recommendations, served via FastAPI with a Next.js web frontend and WeChat Mini Program.

The project is currently in early planning/prototyping stage. The `复现计划/` directory contains a 10-chapter implementation guide that walks through building the system from scratch. Each chapter targets a runnable milestone.

## Tech stack

| Layer | Technology |
|-------|-----------|
| Backend framework | FastAPI (Python 3.11) |
| Database | SQLite (single-file, WAL mode, no ORM) |
| AI provider | 讯飞星辰 Workflow API + Spark X LLM |
| Web frontend | Next.js 15 (App Router, `"use client"`) |
| Mini Program | 原生 WeChat Mini Program |
| Deployment | Render (backend) + Vercel (frontend) |

## Project structure (planned)

```
CampusFoodAgent/
├── backend/
│   ├── .env / .env.example          # Secrets & config
│   ├── requirements.txt
│   ├── pytest.ini
│   ├── app/
│   │   ├── main.py                  # FastAPI app entry, CORS + UTF-8 middleware
│   │   ├── api/
│   │   │   ├── routes.py            # /api/v1 MVP endpoints (rule-based)
│   │   │   ├── proxy_routes.py      # /api endpoints (AI-powered)
│   │   │   └── auth.py              # JWT dependency for protected routes
│   │   ├── models/
│   │   │   └── schemas.py           # Pydantic request/response models
│   │   ├── core/
│   │   │   └── scoring_config.py    # Scoring weight loader from YAML
│   │   └── services/
│   │       ├── shop_repository.py   # SQLite DB layer (DDL, seed, queries)
│   │       ├── parser.py            # Natural language → structured slots
│   │       ├── recommender.py       # Rule-based weighted scoring engine
│   │       ├── xfyun_workflow_service.py    # 讯飞 workflow API client
│   │       ├── spark_local_recommend_service.py  # Hybrid: rules + LLM rerank
│   │       ├── auth_token_service.py   # Hand-rolled JWT (HS256)
│   │       ├── wechat_auth_service.py  # WeChat jscode2session → JWT
│   │       ├── user_profile.py         # Behavioral user profile builder
│   │       ├── query_intent_service.py # Category keyword extraction
│   │       ├── usage_events.py      # Event tracking / analytics
│   │       ├── feedback_repository.py
│   │       ├── favorites_repository.py
│   │       ├── ad_repository.py
│   │       └── hot_ranking.py
│   ├── data/
│   │   ├── schema.sql               # DDL for all 9 tables
│   │   ├── shops_mock.csv           # Seed data (5-10 campus restaurants)
│   │   └── scoring_config.yaml      # Weights + time slots + scene aliases
│   └── tests/
├── frontend/
│   └── src/
│       ├── app/ (layout.tsx, page.tsx, globals.css)
│       ├── lib/ (api.ts, identity.ts)
│       └── components/ (FeedbackPanel.tsx)
├── miniprogram/
│   ├── pages/ (index, ads, profile, profile-detail, store-detail)
│   └── utils/ (api.js, config.js, identity.js, analytics.js)
├── 复现计划/                        # 10-chapter build guide
└── AGENTS.md
```

## Architecture: recommendation pipeline

There are three recommendation modes, selectable via `RECOMMEND_PROVIDER` env var:

1. **Rule-based** (default/fallback): User input → `parser.py` extracts structured slots (budget, location, taste, scene, time) → `recommender.py` scores all shops against slots using configurable weights from `scoring_config.yaml` → returns top K ranked results.

2. **Workflow** (`RECOMMEND_PROVIDER=workflow`): Sends query to 讯飞星辰 Workflow API, injecting user profile summary and category intent keywords via `AGENT_*` parameters. The workflow runs a pre-built LLM pipeline on 讯飞's platform.

3. **Spark Local** (`RECOMMEND_PROVIDER=spark_local`): Rule engine retrieves top 30 candidates → constructs a prompt with candidate list → Spark X LLM reranks → **whitelist sanitization** filters out hallucinated store names → returns top results. Falls back to rule-based if LLM output is unusable.

## Key design decisions

- **No ORM**: 9 small tables, SQLite single file. Hand-written SQL with `row_factory = sqlite3.Row` for dict-like access.
- **WAL mode**: `PRAGMA journal_mode=WAL` enables concurrent reads without blocking.
- **Per-request DB connections**: SQLite connections are not shared across threads. Every function opens and closes its own.
- **Double-checked locking in `_ensure_database()`**: Thread-safe schema init and seed import on first access.
- **Hand-rolled JWT (HS256):** Intentionally written from scratch for learning; production should use PyJWT.
- **UTF-8 middleware**: Custom `Utf8ResponseMiddleware` ensures `charset=utf-8` on all JSON responses (the app is fully Chinese-language).
- **Anonymous-first identity**: Both web and mini program generate a persistent anonymous ID (`anon_<timestamp36><random>`) on first visit, stored in localStorage / wx.StorageSync. WeChat login upgrades the identity later.
- **openid hashing**: WeChat openids are hashed via `sha256(salt:openid)[:24]` before storage to protect raw openids.
- **Event tracking is fire-and-forget**: `usage_events.py` catches all exceptions so tracking failures never block the main request.

## Commands

```bash
# Backend
cd backend
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Swagger docs at http://localhost:8000/docs

# Web frontend
cd frontend
npm install
npm run dev                     # http://localhost:3000

# Tests
cd backend
python -m pytest tests/ -v
python -m pytest tests/test_recommend.py -v   # Single test file

# WeChat Mini Program
# Open repo root in WeChat DevTools (project.config.json sets miniprogramRoot)
```

## Critical anti-hallucination mechanism

The Spark Local mode's `_sanitize_or_fallback()` function is a security boundary. LLMs can hallucinate store names that don't exist in the database. This function:
1. Builds a whitelist of valid store names from the rule engine's top 30 candidates
2. Filters LLM output to only include whitelisted names
3. Falls back to rule-based results if all LLM-recommended stores fail validation

This is mandatory — do not remove or weaken this filter.
