# Transaction Categorizer — Project Documentation

## Table of Contents
1. [Folder Structure](#1-folder-structure)
2. [Architectural Layers](#2-architectural-layers)
3. [API Endpoints](#3-api-endpoints)
4. [Configuration & Environment Variables](#4-configuration--environment-variables)
5. [Tech Stack & Dependencies](#5-tech-stack--dependencies)
6. [Entry Points](#6-entry-points)
7. [Tests, Middleware & Utilities](#7-tests-middleware--utilities)
8. [Design Patterns & Key Decisions](#8-design-patterns--key-decisions)
9. [Sample Data & Evaluation](#9-sample-data--evaluation)
10. [End-to-End Pipeline Flow](#10-end-to-end-pipeline-flow)

---

## 1. Folder Structure

```
txn_categorizer/
│
├── .env                              # Runtime environment configuration (not in repo)
├── .env.example                      # Template for environment variables
├── .gitignore                        # Git ignore rules
├── requirements.txt                  # Python dependencies
├── README.md                         # Project documentation
├── manage.py                         # Django CLI entry point
├── db.sqlite3                        # SQLite database (minimal — no models)
├── evaluate.py                       # Evaluation script for model testing
│
├── .claude/
│   └── settings.local.json           # Claude Code local settings
│
├── .vscode/
│   └── settings.json                 # VS Code editor configuration
│
├── core/                             # Django project configuration
│   ├── __init__.py
│   ├── settings.py                   # Django settings & LLM config
│   ├── urls.py                       # Root URL dispatcher
│   ├── wsgi.py                       # WSGI application entry point
│   └── asgi.py                       # ASGI application entry point
│
├── categorizer/                      # Main application (business logic)
│   ├── __init__.py
│   ├── schemas.py                    # Pydantic models (input/output contracts)
│   ├── views.py                      # DRF views (thin controllers)
│   ├── urls.py                       # App-level URL routes
│   │
│   ├── services/                     # Business logic layer
│   │   ├── __init__.py
│   │   ├── categorization_service.py # Orchestrator — pipeline entry point
│   │   ├── context_builder.py        # Prompt construction
│   │   ├── llm_client.py             # Model-agnostic LLM abstraction + factory
│   │   └── response_formatter.py     # JSON parsing & validation
│   │
│   └── utils/                        # Utility functions
│       ├── __init__.py
│       └── exception_handler.py      # Global DRF exception handler
│
├── sample_data/                      # Test fixtures & mock data
│   ├── __init__.py
│   └── mock_data.py                  # 5 sample requests + expected outputs
│
└── tests/                            # Unit & integration tests
    ├── __init__.py
    └── test_categorization.py        # Comprehensive test suite
```

---

## 2. Architectural Layers

The project follows a clean, layered Django REST Framework architecture with strict separation of concerns.

### Layer 1 — HTTP / Routing
- **Files**: `core/urls.py`, `categorizer/urls.py`
- **Purpose**: Maps incoming HTTP requests to the appropriate view class.
- Root URL (`core/urls.py`) forwards all `/api/v1/` traffic to `categorizer/urls.py`.

### Layer 2 — Views (Thin Controllers)
- **File**: `categorizer/views.py`
- **Classes**:
  - `CategorizeTransactionView` — handles `POST /api/v1/categorize/`
  - `HealthCheckView` — handles `GET /api/v1/health/`
  - `SampleDataView` — handles `GET /api/v1/samples/`
- **Purpose**: Validate the incoming request (via Pydantic), delegate to the service layer, and return the HTTP response. Contains **no business logic**.

### Layer 3 — Validation (Pydantic Schemas)
- **File**: `categorizer/schemas.py`
- **Classes**:

| Class | Purpose |
|---|---|
| `Transaction` | A single transaction descriptor (description, payee, amount, currency, date) |
| `HistoricalTransaction` | A labeled past transaction used for few-shot prompting |
| `CategorizationRequest` | Inbound API request body — auto-caps history at 20 records |
| `CategorySuggestion` | An alternative category with confidence score and reasoning |
| `CategorizationResponse` | Complete outbound response with confidence label |
| `ErrorResponse` | Consistent error envelope |

**Confidence thresholds** (defined here):
- `HIGH` — score ≥ 0.80
- `MEDIUM` — score ≥ 0.50
- `LOW` — score < 0.50

### Layer 4 — Services (Business Logic)

The service layer implements a 3-step pipeline:

#### `categorization_service.py` (Orchestrator)
- Function: `categorize_transaction(request) → CategorizationResponse`
- Calls the three steps below in sequence.

#### `context_builder.py` (Step 1 — Prompt Construction)
- Function: `build_prompts(request) → (system_prompt, user_prompt)`
- Embeds the Chart of Accounts as a constrained label set.
- Formats historical transactions as few-shot examples.
- The system prompt is static; the user prompt is variable.

#### `llm_client.py` (Step 2 — LLM Abstraction)
- `BaseLLMClient` — abstract base with interface: `complete(system, user) → str`
- **Implementations**:
  - `OpenAIClient` — Native OpenAI SDK; supports custom `base_url` for self-hosted endpoints (HuggingFace TGI, vLLM, etc.)
  - `HuggingFaceClient` — Extends `OpenAIClient` using HF's OpenAI-compatible API
  - `AnthropicClient` — Native Anthropic SDK
- `LLMClientFactory` — resolves and instantiates the correct client based on `LLM_PROVIDER` setting
- `extract_json_block()` — helper to parse JSON from raw LLM text (handles markdown fences, prose wrapping)

#### `response_formatter.py` (Step 3 — Parse & Validate)
- Function: `parse_and_format(raw_response, request, client) → CategorizationResponse`
- Extracts JSON from raw LLM text.
- Validates the suggested category exists in the Chart of Accounts (case-insensitive).
- Fuzzy fallback matching by word-overlap for minor wording differences.
- Clamps confidence scores to `[0.0, 1.0]`.
- Parses and deduplicates alternative categories.

### Layer 5 — Utilities
- **File**: `categorizer/utils/exception_handler.py`
- Global DRF exception handler (`custom_exception_handler`)
- Returns a consistent error envelope: `{"error": ..., "detail": ..., "code": ...}`

### Layer 6 — Configuration
- **File**: `core/settings.py`
- All LLM settings and Django settings loaded from `.env` via `python-dotenv`.
- No hardcoded provider or model logic.

---

## 3. API Endpoints

All endpoints are prefixed with `/api/v1/`.

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/categorize/` | Categorize a single transaction using an LLM |
| `GET` | `/api/v1/health/` | Liveness probe |
| `GET` | `/api/v1/samples/` | Return 5 mock sample requests for testing |

---

### POST `/api/v1/categorize/`

Categorizes a single financial transaction into a company-specific Chart of Accounts using an LLM.

**Request Body** (`application/json`):
```json
{
  "transaction": {
    "description": "string (required, 1–500 chars)",
    "payee": "string (optional, max 200 chars)",
    "amount": "float (optional)",
    "currency": "string (optional, max 3 chars, e.g. 'USD')",
    "date": "ISO-8601 string (optional, for context only)"
  },
  "company_id": "string (required, 1–100 chars)",
  "industry": "string (required, 1–100 chars)",
  "chart_of_accounts": ["string", "..."] (required, min 1 item),
  "historical_transactions": [
    {
      "description": "string (required)",
      "payee": "string (optional)",
      "amount": "float (optional)",
      "category": "string (required, must be from CoA)"
    }
  ] (optional, capped at 20 records)
}
```

**Response — HTTP 200**:
```json
{
  "transaction_description": "string",
  "payee": "string or null",
  "suggested_category": "string (exact match from CoA)",
  "confidence_score": "float [0.0–1.0]",
  "confidence_label": "HIGH | MEDIUM | LOW",
  "alternative_categories": [
    {
      "category": "string (from CoA)",
      "confidence": "float [0.0–1.0]",
      "reasoning": "string"
    }
  ],
  "reasoning": "string (1–2 sentences)",
  "model_used": "string (e.g. 'gpt-4o-mini')",
  "provider": "string (e.g. 'openai')"
}
```

**Error Responses**:

| HTTP Status | Trigger | Error Body |
|---|---|---|
| `422` | Pydantic validation failure | `{error, detail (list), code: null}` |
| `400` | Malformed JSON body | `{error, detail (string), code: null}` |
| `502` | LLM API call failure | `{error, detail, code: null}` |
| `500` | Unhandled server error | `{error, detail, code: "internal_error"}` |

---

### GET `/api/v1/health/`

Returns `{"status": "ok"}` with HTTP 200. Used as a liveness/readiness probe.

---

### GET `/api/v1/samples/`

Returns 5 pre-built sample `CategorizationRequest` objects (from `sample_data/mock_data.py`) as `{"samples": [...]}`. Useful for manual testing and integration demos.

---

## 4. Configuration & Environment Variables

**Files**: `.env` (runtime, not in repo), `.env.example` (template), `core/settings.py` (loads from `.env`)

| Variable | Default | Example Values | Purpose |
|---|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` \| `huggingface` \| `anthropic` | Which LLM backend to use |
| `LLM_API_KEY` | — (required) | `sk-...` / `hf_...` / `sk-ant-...` | API authentication token |
| `LLM_MODEL` | `gpt-4o-mini` | `gpt-4`, `claude-3-5-sonnet-latest`, etc. | Model identifier |
| `LLM_BASE_URL` | — (optional) | HF TGI endpoint, vLLM endpoint | Custom OpenAI-compatible endpoint |
| `LLM_TEMPERATURE` | `0.1` | `0.0`–`2.0` | Determinism (lower = more deterministic) |
| `LLM_MAX_TOKENS` | `512` | `1024`, etc. | Max tokens in LLM response |
| `DEBUG` | `True` | `True` \| `False` | Django debug mode |
| `DJANGO_SECRET_KEY` | `dev-secret-key-change-in-prod` | Long random string | Django CSRF/session secret |
| `ALLOWED_HOSTS` | `*` | Comma-separated hostnames | Allowed request hosts |

---

## 5. Tech Stack & Dependencies

**File**: `requirements.txt`

| Package | Version | Purpose |
|---|---|---|
| `django` | `>=4.2,<5.0` | Web framework |
| `djangorestframework` | `>=3.14` | REST API framework |
| `openai` | `>=1.30` | OpenAI API client (required by default) |
| `pydantic` | `>=2.0` | Schema validation & type coercion |
| `python-dotenv` | `>=1.0` | Load `.env` into environment |
| `anthropic` | `>=0.25` (optional) | Anthropic API client |
| `pytest` | `>=8.0` (optional) | Test framework |
| `pytest-django` | `>=4.8` (optional) | Django-pytest integration |

**Summary**:
- **Language**: Python 3.10+
- **Web Framework**: Django REST Framework
- **LLM Backends**: OpenAI (default), Anthropic, HuggingFace (OpenAI-compatible)
- **Validation**: Pydantic v2+
- **Database**: SQLite (no ORM models — database barely used)
- **Config**: Environment variables via `python-dotenv`

---

## 6. Entry Points

| Entry Point | Type | Command |
|---|---|---|
| `manage.py` | Development server | `python manage.py runserver` |
| `manage.py` | Database migrations | `python manage.py migrate` |
| `manage.py` | Test runner | `python manage.py test tests` |
| `core/wsgi.py` | Production (sync) | `gunicorn core.wsgi:application --bind 0.0.0.0:8000` |
| `core/asgi.py` | Production (async) | `uvicorn core.asgi:application --host 0.0.0.0 --port 8000` |
| `evaluate.py` | Evaluation script | `python evaluate.py` |

---

## 7. Tests, Middleware & Utilities

### Test Suite (`tests/test_categorization.py`)

| Test Class | # Tests | Coverage |
|---|---|---|
| `TestSchemaValidation` | 4 | Pydantic validation, history capping (max 20), confidence label thresholds |
| `TestContextBuilder` | 6 | Prompt building, CoA embedding, few-shot history formatting, no-history handling |
| `TestExtractJsonBlock` | 4 | JSON extraction from plain / fenced / prose-wrapped LLM output |
| `TestResponseFormatter` | 7 | JSON parsing, category validation, confidence clamping, case-insensitive matching |
| `TestCategorizationServiceIntegration` | 2 | End-to-end pipeline (mocked LLM), LLM failure handling |

```bash
# Run with Django test runner
python manage.py test tests

# Run with pytest
pytest tests/ -v
```

### Middleware (configured in `core/settings.py`)

- `SecurityMiddleware` — HTTPS/security headers
- `CommonMiddleware` — CORS, ETag, etc.

### Global Exception Handler (`categorizer/utils/exception_handler.py`)

Wraps all DRF exceptions in a consistent envelope:
```json
{
  "error": "Human-readable message",
  "detail": "Specific detail or list of validation errors",
  "code": "machine-readable code or null"
}
```

### Utility Functions

| File | Function | Purpose |
|---|---|---|
| `llm_client.py` | `extract_json_block(raw)` | Parse JSON from LLM response (handles fences, prose) |
| `response_formatter.py` | `_validate_category()` | Case-insensitive CoA matching + fuzzy fallback |
| `response_formatter.py` | `_fuzzy_match()` | Word-overlap matching for minor wording differences |
| `response_formatter.py` | `_clamp()` | Clamp confidence scores to `[0.0, 1.0]` |
| `response_formatter.py` | `_parse_alternatives()` | Parse & deduplicate alternative categories |

---

## 8. Design Patterns & Key Decisions

### 1. LLM Abstraction Layer (`BaseLLMClient`)
The interface is minimal: `complete(system, user) → str`. Adding a new LLM provider only requires subclassing `BaseLLMClient` and registering it in `LLMClientFactory`. No changes to the service or view layer.

### 2. Pydantic for All I/O
All validation lives in `schemas.py`. Views stay thin. Pydantic handles type coercion, field limits, and history capping (max 20 records) automatically.

### 3. Prompt Separation
- **System prompt** — static instructions + required JSON output schema
- **User prompt** — variable per-request (company context, CoA, history, transaction)

This makes prompt iteration easy without touching business logic.

### 4. Category Validation with Fuzzy Fallback
The formatter enforces that the LLM's suggested category exists in the Chart of Accounts:
1. Exact match (case-insensitive)
2. Word-overlap fuzzy match
3. Raises an error if neither matches

This prevents silent category mismatches where the LLM hallucinates a category name.

### 5. Multi-Tenant by Design
Company ID, industry, Chart of Accounts, and historical transactions are all runtime inputs. There is no hardcoded company logic anywhere in the codebase.

### 6. PII-Safe Logging
The application logs model, provider, category, and confidence scores — but **never** logs transaction descriptions or payee names.

### 7. Consistent Error Envelopes
All errors follow `{error, detail, code}`. HTTP status codes follow REST conventions (422 = validation, 502 = upstream service, 500 = server error).

---

## 9. Sample Data & Evaluation

### Mock Samples (`sample_data/mock_data.py`)

5 pre-built test cases with expected results:

| # | Transaction | Expected Category | Min Confidence |
|---|---|---|---|
| 1 | Notion Pro subscription | Software & Subscriptions | 0.85 |
| 2 | Team dinner client meeting | Meals & Entertainment | 0.80 |
| 3 | Marriott hotel NYC | Travel & Lodging | 0.85 |
| 4 | Legal retainer invoice | Professional Services | 0.80 |
| 5 | Staples printer ink | Office Supplies | 0.75 |

### Default Chart of Accounts (10 categories)
- Software & Subscriptions
- Office Supplies
- Travel & Lodging
- Meals & Entertainment
- Advertising & Marketing
- Professional Services
- Utilities
- Payroll & Benefits
- Equipment & Hardware
- Miscellaneous

### Evaluation Script (`evaluate.py`)
- Runs all 5 samples through the **live** LLM (requires `.env` configured)
- Reports: top-1 accuracy, confidence distribution (avg/min/max), per-sample results
- Saves full results to `evaluation_results.json`
- Exit code: `0` if accuracy ≥ 60%, `1` otherwise

```bash
python evaluate.py
```

---

## 10. End-to-End Pipeline Flow

```
POST /api/v1/categorize/  (JSON body)
         │
         ▼
[CategorizeTransactionView.post()]
  ├─ Parse body as CategorizationRequest (Pydantic)
  └─ On ValidationError → HTTP 422
         │
         ▼
[categorize_transaction(request)]  ← categorization_service.py
  │
  ├─ Step 1: build_prompts(request)  ← context_builder.py
  │           ├─ Static system_prompt (instructions + JSON schema)
  │           └─ Variable user_prompt (company, CoA, history, transaction)
  │
  ├─ Step 2: LLMClientFactory.get()  ← llm_client.py
  │           ├─ Resolve provider from settings (openai / anthropic / huggingface)
  │           └─ client.complete(system_prompt, user_prompt) → raw_text
  │
  └─ Step 3: parse_and_format(raw_text, request, client)  ← response_formatter.py
             ├─ extract_json_block(raw_text)
             ├─ _validate_category(cat, chart_of_accounts)
             │   └─ Fuzzy fallback if not exact match
             ├─ _clamp(confidence) → [0.0, 1.0]
             ├─ _parse_alternatives(...)
             └─ Return CategorizationResponse
         │
         ▼
HTTP 200 (JSON)
{
  "transaction_description": "...",
  "payee": "...",
  "suggested_category": "...",
  "confidence_score": 0.92,
  "confidence_label": "HIGH",
  "alternative_categories": [...],
  "reasoning": "...",
  "model_used": "gpt-4o-mini",
  "provider": "openai"
}
```
