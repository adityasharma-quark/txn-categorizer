# Transaction Categorization Service

An AI-powered agent that automatically categorizes financial transactions using an LLM with access to company-specific heuristics. Built with Django REST Framework, an agentic tool-use loop (Anthropic), and a clean service-layer architecture.

---

## Architecture Overview

```
categorizer/
├── schemas.py                  # Pydantic contracts — all I/O validation
├── views.py                    # Thin DRF views — no business logic
├── urls.py                     # Route definitions
├── services/
│   ├── categorization_service.py   # Orchestrator — agentic or standard pipeline
│   ├── context_builder.py          # Builds system + user prompts (standard or agentic)
│   ├── llm_client.py               # Model-agnostic LLM abstraction + agentic loop
│   ├── response_formatter.py       # Parses & validates LLM output
│   └── tools.py                    # Tool definitions + implementations (NEW)
└── utils/
    └── exception_handler.py        # Global error envelope

heuristics/                     # Company-specific reference data
├── c125_BankRules.json             # Keyword → GL account rules for company 125
├── c125_COA.json                   # Chart of Accounts for company 125
├── c125_Categorized_Transactions_*.json  # Historical categorized transactions
├── c125_Plaid_Transactions_*.json        # Raw Plaid bank feed
├── c417_BankRules.json             # Same for company 417
├── c417_COA.json
├── c417_Categorized_Transactions_*.json
└── c417_Plaid_Transactions_*.json
```

**Pipeline flow — three tiers, tried in order:**
```
POST /api/v1/categorize/
        │
        ▼
  [View] validate input (Pydantic)
        │
        ▼
  TIER 1 — Rule Engine (zero LLM cost)
    keyword-match bank rules → word-overlap map to CoA
    HIT  → return immediately  (conf 0.92–0.97, model_used="rule-engine")
    MISS ↓
        │
        ▼
  TIER 2 — Enriched Single LLM Call
    pre-fetch: lookup_bank_rules + lookup_similar_transactions
    inject as context → single client.complete() call
    confidence >= 0.5 → return  (categorization_tier=2)
    confidence <  0.5 ↓
        │
        ▼
  TIER 3 — Agentic Escalation  (Anthropic only)
    [AnthropicClient.complete_agentic()] loop ─────────────────────────┐
      stop_reason == "tool_use"  → execute tool → append result ───────┘
      stop_reason == "end_turn"  → extract text → return
    (categorization_tier=3, tools_used=[...])
```

---

## Tier Routing Summary

| Tier | Trigger | LLM calls | `categorization_tier` |
|---|---|---|---|
| 1 — Rule Engine | Bank rule keyword match + CoA word-overlap | **0** | `1` |
| 2 — Enriched LLM | No rule hit, or rule can't map to CoA | **1** | `2` |
| 3 — Agentic | Tier 2 confidence < 0.5 (Anthropic only) | **2–4** | `3` |

## Available Tools (Tier 3 Agentic Mode)

| Tool | Purpose |
|---|---|
| `lookup_bank_rules` | Keyword-match against company-defined GL rules |
| `lookup_similar_transactions` | Search historical categorized transactions |
| `get_chart_of_accounts` | Full GL account list with codes and groups |

---

## Quickstart

### 1. Clone and install

```bash
git clone <repo-url>
cd txn_categorizer
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env — at minimum set LLM_API_KEY
```

### 3. Run migrations (minimal — no app models)

```bash
python manage.py migrate
```

### 4. Start the server

```bash
python manage.py runserver
```

---

## Configuration

All configuration is environment-driven — no hardcoded company or model logic.

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` \| `huggingface` \| `anthropic` |
| `LLM_API_KEY` | — | Your provider API key |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier for chosen provider |
| `LLM_BASE_URL` | — | Custom endpoint (HuggingFace TGI, vLLM, etc.) |
| `LLM_TEMPERATURE` | `0.1` | Low = more deterministic |
| `LLM_MAX_TOKENS` | `512` | Max tokens in LLM response |
| `DEBUG` | `True` | Django debug mode |
| `DJANGO_SECRET_KEY` | dev key | Override in production |

### Switching providers

**Anthropic (recommended — enables agentic tool use):**
```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-haiku-4-5-20251001
```

**HuggingFace (OpenAI-compatible TGI endpoint):**
```env
LLM_PROVIDER=huggingface
LLM_API_KEY=hf_...
LLM_MODEL=mistralai/Mistral-7B-Instruct-v0.2
LLM_BASE_URL=https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2/v1
```

---

## API Reference

### `POST /api/v1/categorize/`

Categorize a single transaction.

**Request body:**

```json
{
  "transaction": {
    "description": "Monthly Notion Pro subscription",
    "payee": "Notion Labs",
    "amount": 16.00,
    "currency": "USD",
    "date": "2024-05-01"
  },
  "company_id": "acme-corp-001",
  "industry": "Technology / SaaS",
  "chart_of_accounts": [
    "Software & Subscriptions",
    "Office Supplies",
    "Travel & Lodging",
    "Meals & Entertainment",
    "Advertising & Marketing",
    "Professional Services",
    "Utilities",
    "Payroll & Benefits",
    "Equipment & Hardware",
    "Miscellaneous"
  ],
  "historical_transactions": []
}
```

**Response `200 OK`:**

```json
{
  "transaction_description": "Monthly Notion Pro subscription",
  "payee": "Notion Labs",
  "suggested_category": "Software & Subscriptions",
  "confidence_score": 0.93,
  "confidence_label": "HIGH",
  "alternative_categories": [
    {
      "category": "Miscellaneous",
      "confidence": 0.05,
      "reasoning": "Catch-all fallback if category is unclear."
    }
  ],
  "reasoning": "No bank rule matched; historical transactions show similar SaaS tools categorized under Software & Subscriptions.",
  "model_used": "claude-haiku-4-5-20251001",
  "provider": "anthropic",
  "tools_used": ["lookup_bank_rules", "lookup_similar_transactions"]
}
```

**Confidence labels:**
- `HIGH` — score ≥ 0.80
- `MEDIUM` — score ≥ 0.50
- `LOW` — score < 0.50

**Error responses:**

| Status | Trigger |
|---|---|
| `422` | Pydantic validation failure |
| `400` | Malformed JSON |
| `502` | LLM API error |
| `500` | Unhandled server error |

---

### `GET /api/v1/health/`

Liveness probe — returns `{"status": "ok"}`.

---

### `GET /api/v1/samples/`

Returns 5 pre-built sample requests for manual testing.

---

## Running Tests

```bash
# Django test runner
python manage.py test tests

# Or with pytest
pip install pytest pytest-django
pytest tests/ -v
```

---

## Evaluation

```bash
python evaluate.py
```

Runs 5 sample transactions through the live LLM and reports top-1 accuracy, confidence distribution, and per-sample results. Saves full results to `evaluation_results.json`.

---

## Design Decisions

**Tiered pipeline** — Tier 1 (rule engine) covers the majority of known vendors at zero LLM cost. Tier 2 (enriched single call) handles everything else with pre-fetched context in the prompt. Tier 3 (agentic) is reserved exclusively for genuinely ambiguous transactions (confidence < 0.5) where the LLM needs to explore further. This keeps cost and latency low on the hot path.

**`stop_reason == "end_turn"` loop termination** — The Tier 3 agentic loop in `AnthropicClient.complete_agentic()` continues executing tool calls as long as `stop_reason == "tool_use"`, exits on `stop_reason == "end_turn"`. A 10-iteration safety cap prevents runaway loops.

**Rule engine word-overlap mapping** — `map_rule_to_coa()` maps bank rule titles to the request's CoA items via word overlap after stop-word removal. Confidence is 0.97 for ≥ 2 word matches, 0.92 for 1. Zero overlap falls through to Tier 2.

**Tool file caching** — Heuristics files are loaded once per process (`_file_cache`). Avoids re-reading large JSON files on every request.

**`categorization_tier` in response** — Every response includes which tier produced it (1, 2, or 3). Combined with `tools_used`, this makes the decision path fully observable.

**Graceful degradation** — Non-Anthropic providers skip Tier 3 silently; they run Tier 1 + Tier 2 and return the Tier 2 result even if confidence is low.

**Pydantic schemas** — All I/O contracts live in `schemas.py`. Views stay thin.

**No hardcoded company logic** — Company ID, industry, CoA, and history are all runtime inputs. Heuristics files are discovered by convention (`c{id}_BankRules.json`).

**Logging** — Logs tier, model, provider, category, confidence, and tool names — never transaction descriptions or payee names (PII-safe).
