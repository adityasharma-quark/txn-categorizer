# Transaction Categorization Service

A backend-only AI-powered service that automatically categorizes financial transactions using an LLM. Built with Django REST Framework, a model-agnostic LLM abstraction layer, and a clean service-layer architecture.

---

## Architecture Overview

```
categorizer/
├── schemas.py                  # Pydantic contracts — all I/O validation
├── views.py                    # Thin DRF views — no business logic
├── urls.py                     # Route definitions
├── services/
│   ├── categorization_service.py   # Orchestrator — pipeline entry point
│   ├── context_builder.py          # Builds structured LLM prompt
│   ├── llm_client.py               # Model-agnostic LLM abstraction + factory
│   └── response_formatter.py       # Parses & validates LLM output
└── utils/
    └── exception_handler.py        # Global error envelope
```

**Pipeline flow:**
```
POST /api/v1/categorize/
        │
        ▼
  [View] validate input (Pydantic)
        │
        ▼
  [context_builder] build system + user prompt
        │
        ▼
  [llm_client] invoke LLM (provider resolved from config)
        │
        ▼
  [response_formatter] extract JSON → validate category → format response
        │
        ▼
  Deterministic JSON response
```

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
cp .env
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

**HuggingFace (OpenAI-compatible TGI endpoint):**
```env
LLM_PROVIDER=huggingface
LLM_API_KEY=hf_...
LLM_MODEL=mistralai/Mistral-7B-Instruct-v0.2
LLM_BASE_URL=https://api-inference.huggingface.co/models/mistralai/Mistral-7B-Instruct-v0.2/v1
```

**Anthropic:**
```env
LLM_PROVIDER=anthropic
LLM_API_KEY=sk-ant-...
LLM_MODEL=claude-haiku-4-5-20251001
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
  "historical_transactions": [
    {
      "description": "AWS monthly bill",
      "payee": "Amazon Web Services",
      "amount": 340.50,
      "category": "Software & Subscriptions"
    }
  ]
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
  "reasoning": "Notion is a SaaS tool; monthly charges from software vendors map directly to Software & Subscriptions.",
  "model_used": "gpt-4o-mini",
  "provider": "openai"
}
```

**Confidence labels:**
- `HIGH` — score ≥ 0.80
- `MEDIUM` — score ≥ 0.50
- `LOW` — score < 0.50

**Error `422 Unprocessable Entity`** (validation failure):
```json
{
  "error": "Invalid request payload.",
  "detail": [{"loc": ["chart_of_accounts"], "msg": "field required"}],
  "code": null
}
```

---

### `GET /api/v1/health/`

Liveness probe.

```json
{"status": "ok"}
```

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

Tests cover:
- Schema validation (Pydantic)
- Context builder output correctness
- JSON extraction from raw LLM text
- Response formatter (valid, edge cases, fuzzy category matching)
- Full pipeline integration (LLM mocked)

---

## Evaluation

```bash
python evaluate.py
```

Runs 5 sample transactions through the live LLM and reports:

- **Top-1 accuracy** — whether predicted category matches expected
- **Confidence score** distribution (avg, min, max)
- Per-sample pass/fail with reasoning
- Saves full results to `evaluation_results.json`

Sample expected outputs:

| # | Description | Expected Category | Expected Confidence |
|---|---|---|---|
| 1 | Notion Pro subscription | Software & Subscriptions | ≥ 0.85 |
| 2 | Team dinner client meeting | Meals & Entertainment | ≥ 0.80 |
| 3 | Marriott hotel NYC | Travel & Lodging | ≥ 0.85 |
| 4 | Legal retainer invoice | Professional Services | ≥ 0.80 |
| 5 | Staples printer ink | Office Supplies | ≥ 0.75 |

---

## Design Decisions

**LLM abstraction layer** — `BaseLLMClient` defines a minimal interface (`complete(system, user) → str`). Adding a new provider requires subclassing and registering in `LLMClientFactory._REGISTRY` — no other code changes.

**Pydantic schemas** — All input/output contracts live in `schemas.py`. Views stay thin; the schema layer handles coercion, validation, and history truncation.

**Prompt construction** — System prompt is stable (instructions + JSON schema). User prompt is variable (company context, CoA, history, transaction). This separation makes prompt iteration easy.

**Category validation** — The formatter enforces that the LLM's suggested category exists in the Chart of Accounts. A fuzzy fallback (word overlap) handles minor casing/wording differences before raising an error.

**No hardcoded company logic** — Company ID, industry, CoA, and history are all runtime inputs. The service is fully multi-tenant by design.

**Logging** — Uses Python's `logging` module. Logs model, provider, category, and confidence — never transaction descriptions or payee names that could contain PII.
