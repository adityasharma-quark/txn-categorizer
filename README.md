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

**Agentic pipeline flow (Anthropic provider):**
```
POST /api/v1/categorize/
        │
        ▼
  [View] validate input (Pydantic)
        │
        ▼
  [context_builder] build agentic system + user prompt
        │
        ▼
  [AnthropicClient.complete_agentic()] ──────────────────────────────┐
        │                                                             │
        │  ┌─ stop_reason == "tool_use" ──► execute tool ────────────┘
        │  └─ stop_reason == "end_turn" ──► extract text
        │
        ▼
  [response_formatter] extract JSON → validate category → format response
        │
        ▼
  JSON response (includes tools_used list)
```

**Standard pipeline flow (OpenAI / HuggingFace):**
```
POST /api/v1/categorize/
        │
        ▼
  [View] → [context_builder] → single LLM call → [response_formatter] → JSON
```

---

## Available Tools (Agentic Mode)

When using the Anthropic provider, the model has access to three tools:

| Tool | Purpose | When to use |
|---|---|---|
| `lookup_bank_rules` | Keyword-match against company-defined GL rules | Always call first — a match is ground truth |
| `lookup_similar_transactions` | Search historical categorized transactions | When no bank rule matches |
| `get_chart_of_accounts` | Full GL account list with codes and groups | When more CoA detail is needed |

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
  "company_id": "125",
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

**Agentic tool use** — When using Anthropic, the model drives its own information-gathering before categorizing. It can look up bank rules (explicit bookkeeper preferences), historical transactions (past behavior), and the full Chart of Accounts. This makes the system an actual agent rather than a single-call classifier.

**`stop_reason == "end_turn"` loop termination** — The agentic loop in `AnthropicClient.complete_agentic()` continues executing tool calls as long as `stop_reason == "tool_use"`, and exits when `stop_reason == "end_turn"`. A max-iterations guard (10) prevents runaway loops.

**Tool file caching** — Heuristics files are loaded once per process and cached in memory (`_file_cache`). Avoids re-reading large JSON files on every request.

**Graceful degradation** — Non-Anthropic providers fall back to the standard single-turn pipeline. No code changes required when switching providers.

**`tools_used` in response** — The API response includes a `tools_used` list showing which tools the agent called. Useful for observability, debugging, and understanding confidence.

**Pydantic schemas** — All input/output contracts live in `schemas.py`. Views stay thin; the schema layer handles coercion, validation, and history truncation.

**No hardcoded company logic** — Company ID, industry, CoA, and history are all runtime inputs. Heuristics files are discovered by convention (`c{id}_BankRules.json`).

**Logging** — Logs model, provider, category, confidence, and tools used — never transaction descriptions or payee names (PII-safe).
