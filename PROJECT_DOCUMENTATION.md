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
│   │   ├── categorization_service.py # Orchestrator — agentic or standard pipeline
│   │   ├── context_builder.py        # Prompt construction (standard + agentic variants)
│   │   ├── llm_client.py             # LLM abstraction + agentic loop (AnthropicClient)
│   │   ├── response_formatter.py     # JSON parsing & validation
│   │   └── tools.py                  # Tool definitions + implementations (NEW)
│   │
│   └── utils/                        # Utility functions
│       ├── __init__.py
│       └── exception_handler.py      # Global DRF exception handler
│
├── heuristics/                       # Company-specific reference data (not in repo)
│   ├── c125_BankRules.json           # Keyword → GL account rules (company 125)
│   ├── c125_COA.json                 # Chart of Accounts (company 125, 280 accounts)
│   ├── c125_Categorized_Transactions_07-01-24_06-30-25.json  # 1,243 historical txns
│   ├── c125_Plaid_Transactions_07-01-25_12-18-25.json        # Raw Plaid bank feed
│   ├── c417_BankRules.json           # Same set for company 417
│   ├── c417_COA.json
│   ├── c417_Categorized_Transactions_07-01-24_06-30-25.json
│   ├── c417_Plaid_Transactions(01)_07-01-25_12-18-25.json
│   └── c417_Plaid_Transactions(02)_07-01-25_12-18-25.json
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

### Layer 1 — HTTP / Routing
- **Files**: `core/urls.py`, `categorizer/urls.py`
- Root URL (`core/urls.py`) forwards all `/api/v1/` traffic to `categorizer/urls.py`.

### Layer 2 — Views (Thin Controllers)
- **File**: `categorizer/views.py`
- **Classes**: `CategorizeTransactionView`, `HealthCheckView`, `SampleDataView`
- Validate incoming request via Pydantic, delegate to service layer, return HTTP response. No business logic.

### Layer 3 — Validation (Pydantic Schemas)
- **File**: `categorizer/schemas.py`

| Class | Purpose |
|---|---|
| `Transaction` | A single transaction descriptor |
| `HistoricalTransaction` | A labeled past transaction for few-shot prompting |
| `CategorizationRequest` | Inbound API request body — auto-caps history at 20 records |
| `CategorySuggestion` | An alternative category with confidence score and reasoning |
| `CategorizationResponse` | Complete outbound response including `tools_used` list |
| `ErrorResponse` | Consistent error envelope |

**Confidence thresholds**: HIGH ≥ 0.80, MEDIUM ≥ 0.50, LOW < 0.50

### Layer 4 — Services (Business Logic)

#### `categorization_service.py` (Orchestrator)
- Function: `categorize_transaction(request) → CategorizationResponse`
- Checks `client.supports_tools()` to select the agentic or standard pipeline.
- **Agentic path**: builds agentic prompt → calls `complete_agentic()` → tools loop runs → parse output
- **Standard path**: builds standard prompt → calls `complete()` → parse output

#### `context_builder.py` (Prompt Construction)
- Function: `build_prompts(request, agentic=False) → (system_prompt, user_prompt)`
- `agentic=True` returns `_AGENTIC_SYSTEM_TEMPLATE` which instructs the model to use tools before deciding.
- `agentic=False` returns the original `_SYSTEM_TEMPLATE` for single-turn classification.

#### `llm_client.py` (LLM Abstraction)
- `BaseLLMClient` — abstract base with `complete()`, `supports_tools()`, and `complete_agentic()`
- **Implementations**:
  - `OpenAIClient` — single-turn; `supports_tools()` returns False
  - `HuggingFaceClient` — extends `OpenAIClient` for HF-compatible endpoints
  - `AnthropicClient` — implements the full agentic loop; `supports_tools()` returns True
- `LLMClientFactory` — resolves and instantiates the correct client from `LLM_PROVIDER`

**`AnthropicClient.complete_agentic()` loop logic:**
```
messages = [user_prompt]
for iteration in range(10):          # max 10 iterations
    response = messages.create(...)
    if stop_reason == "end_turn":    # ← model is done
        return text content
    if stop_reason == "tool_use":    # ← model wants tool results
        execute tools → append results → continue
    else:
        return text content          # unexpected stop, exit gracefully
```

#### `tools.py` (Tool Definitions + Implementations) — NEW
- **Tool definitions** (Anthropic API format) in `TOOL_DEFINITIONS`
- **Tool implementations**:

| Function | File(s) read | Purpose |
|---|---|---|
| `lookup_bank_rules(company_id, description)` | `c{id}_BankRules.json` | Keyword-match active rules; resolves account IDs to names via COA |
| `lookup_similar_transactions(company_id, description, payee)` | `c{id}_Categorized_Transactions*.json` | Word-overlap search; returns up to 5 past transactions with their categories |
| `get_chart_of_accounts(company_id)` | `c{id}_COA.json` | Full GL account list grouped by ASSETS / LIABILITIES / EQUITY / INCOME / EXPENSES / COGS |
| `execute_tool(name, inputs)` | — | Dispatcher; called by the agentic loop |

- **File caching**: `_file_cache` dict at module level — each heuristics file is loaded once per process.
- **Company ID normalization**: `_normalize_cid()` handles `"125"`, `"c125"`, `"C125"` → `"125"`.

#### `response_formatter.py` (Parse & Validate)
- Function: `parse_and_format(raw_response, request, client, tools_used=None) → CategorizationResponse`
- Extracts JSON, validates category (exact + fuzzy), clamps confidence, deduplicates alternatives.
- Passes `tools_used` into the response object.

### Layer 5 — Utilities
- `categorizer/utils/exception_handler.py` — global DRF exception handler
- Returns `{"error": ..., "detail": ..., "code": ...}` for all errors

### Layer 6 — Configuration
- `core/settings.py` — all LLM settings loaded from `.env` via `python-dotenv`

---

## 3. API Endpoints

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/categorize/` | Categorize a transaction (agentic or standard) |
| `GET` | `/api/v1/health/` | Liveness probe |
| `GET` | `/api/v1/samples/` | Return 5 mock sample requests |

### POST `/api/v1/categorize/`

**Request Body:**
```json
{
  "transaction": {
    "description": "string (required, 1–500 chars)",
    "payee": "string (optional)",
    "amount": "float (optional)",
    "currency": "string (optional, max 3 chars)",
    "date": "ISO-8601 string (optional)"
  },
  "company_id": "string (required)",
  "industry": "string (required)",
  "chart_of_accounts": ["string", "..."],
  "historical_transactions": [{"description": "...", "category": "..."}]
}
```

**Response — HTTP 200:**
```json
{
  "transaction_description": "string",
  "payee": "string or null",
  "suggested_category": "string (exact match from CoA)",
  "confidence_score": 0.92,
  "confidence_label": "HIGH",
  "alternative_categories": [...],
  "reasoning": "string",
  "model_used": "claude-haiku-4-5-20251001",
  "provider": "anthropic",
  "tools_used": ["lookup_bank_rules", "lookup_similar_transactions"]
}
```

**Error Responses:**

| HTTP Status | Trigger |
|---|---|
| `422` | Pydantic validation failure |
| `400` | Malformed JSON body |
| `502` | LLM API call failure |
| `500` | Unhandled server error |

---

## 4. Configuration & Environment Variables

| Variable | Default | Purpose |
|---|---|---|
| `LLM_PROVIDER` | `openai` | `openai` \| `huggingface` \| `anthropic` |
| `LLM_API_KEY` | — (required) | API authentication token |
| `LLM_MODEL` | `gpt-4o-mini` | Model identifier |
| `LLM_BASE_URL` | — (optional) | Custom OpenAI-compatible endpoint |
| `LLM_TEMPERATURE` | `0.1` | Determinism |
| `LLM_MAX_TOKENS` | `512` | Max tokens per LLM response |
| `DEBUG` | `True` | Django debug mode |
| `DJANGO_SECRET_KEY` | dev key | Django CSRF/session secret |
| `ALLOWED_HOSTS` | `*` | Allowed request hosts |

---

## 5. Tech Stack & Dependencies

| Package | Purpose |
|---|---|
| `django >=4.2,<5.0` | Web framework |
| `djangorestframework >=3.14` | REST API framework |
| `openai >=1.30` | OpenAI API client |
| `pydantic >=2.0` | Schema validation & type coercion |
| `python-dotenv >=1.0` | Load `.env` into environment |
| `anthropic >=0.25` (optional) | Anthropic API client — required for agentic tool use |
| `pytest >=8.0` (optional) | Test framework |
| `pytest-django >=4.8` (optional) | Django-pytest integration |

---

## 6. Entry Points

| Entry Point | Command |
|---|---|
| Development server | `python manage.py runserver` |
| Database migrations | `python manage.py migrate` |
| Test runner | `python manage.py test tests` |
| Production (sync) | `gunicorn core.wsgi:application --bind 0.0.0.0:8000` |
| Production (async) | `uvicorn core.asgi:application --host 0.0.0.0 --port 8000` |
| Evaluation script | `python evaluate.py` |

---

## 7. Tests, Middleware & Utilities

### Test Suite (`tests/test_categorization.py`)

| Test Class | Coverage |
|---|---|
| `TestSchemaValidation` | Pydantic validation, history capping, confidence labels |
| `TestContextBuilder` | Prompt building, CoA embedding, few-shot formatting |
| `TestExtractJsonBlock` | JSON extraction from fenced / prose-wrapped LLM output |
| `TestResponseFormatter` | JSON parsing, category validation, confidence clamping |
| `TestCategorizationServiceIntegration` | End-to-end pipeline (LLM mocked), failure handling |

### Middleware (`core/settings.py`)
- `SecurityMiddleware` — HTTPS/security headers
- `CommonMiddleware` — CORS, ETag

### Utility Functions

| File | Function | Purpose |
|---|---|---|
| `llm_client.py` | `extract_json_block(raw)` | Parse JSON from LLM text (fences, prose) |
| `response_formatter.py` | `_validate_category()` | Case-insensitive CoA matching + fuzzy fallback |
| `response_formatter.py` | `_fuzzy_match()` | Word-overlap matching |
| `response_formatter.py` | `_clamp()` | Clamp confidence to `[0.0, 1.0]` |
| `tools.py` | `_build_account_map()` | Build account-id → name dict from COA file |
| `tools.py` | `_normalize_cid()` | Normalize company ID format |

---

## 8. Design Patterns & Key Decisions

### 1. True Agentic Loop (NEW)
`AnthropicClient` implements a real agentic loop. The model decides which tools to call, in what order, based on the transaction and company context. The loop exits only when `stop_reason == "end_turn"`. This is not a pre-scripted flow — the model's tool-calling behavior is emergent.

### 2. Graceful Degradation
`BaseLLMClient.supports_tools()` defaults to `False`. Non-Anthropic providers get the original single-turn pipeline transparently. The categorization service branches on this flag — no other code changes needed when switching providers.

### 3. Heuristics as Ground Truth
The `lookup_bank_rules` tool encodes an explicit signal: if a rule matches, it represents a human bookkeeper's deliberate choice and should be treated as high-confidence ground truth. The agentic system prompt instructs the model to respect this.

### 4. Tool File Caching
`_file_cache` in `tools.py` is a module-level dict. Each heuristics file is read from disk once per process. Avoids re-reading large files (e.g. 1,243-transaction history) on every request.

### 5. `tools_used` Observability
Every API response includes `tools_used`, a deduplicated list of tools the agent called. This enables debugging, latency attribution, and confidence analysis (e.g. HIGH confidence with `lookup_bank_rules` means a rule matched).

### 6. Prompt Separation
- `_SYSTEM_TEMPLATE` — original single-turn instructions
- `_AGENTIC_SYSTEM_TEMPLATE` — tool-aware instructions with explicit decision strategy
Both share the same JSON output schema. The `build_prompts(agentic=True/False)` flag selects the right template.

### 7. Category Validation with Fuzzy Fallback
1. Exact match (case-insensitive)
2. Word-overlap fuzzy match
3. Raises ValueError if neither matches

Prevents silent category mismatches where the LLM or a tool returns a slightly different account name.

### 8. Multi-Tenant by Design
Company ID, industry, CoA, and history are all runtime inputs. Heuristics files are discovered by convention (`c{id}_BankRules.json`). No hardcoded company logic anywhere.

### 9. PII-Safe Logging
Logs model, provider, category, confidence, and tool names — never transaction descriptions or payee names.

---

## 9. Sample Data & Evaluation

### Mock Samples (`sample_data/mock_data.py`)

| # | Transaction | Expected Category | Min Confidence |
|---|---|---|---|
| 1 | Notion Pro subscription | Software & Subscriptions | 0.85 |
| 2 | Team dinner client meeting | Meals & Entertainment | 0.80 |
| 3 | Marriott hotel NYC | Travel & Lodging | 0.85 |
| 4 | Legal retainer invoice | Professional Services | 0.80 |
| 5 | Staples printer ink | Office Supplies | 0.75 |

### Default Chart of Accounts (10 categories)
Software & Subscriptions, Office Supplies, Travel & Lodging, Meals & Entertainment,
Advertising & Marketing, Professional Services, Utilities, Payroll & Benefits,
Equipment & Hardware, Miscellaneous

### Heuristics Data (2 companies)

| Company | Bank Rules | COA Accounts | Historical Transactions |
|---|---|---|---|
| c125 | ~10 rules | 280 accounts | 1,243 categorized |
| c417 | ~35 rules | — | — |

### Evaluation Script (`evaluate.py`)
- Runs all 5 samples through the live LLM (requires `.env` configured)
- Reports: top-1 accuracy, confidence distribution, per-sample results
- Saves results to `evaluation_results.json`
- Exit code: `0` if accuracy ≥ 60%

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
  ├─ client = LLMClientFactory.get()
  │
  ├─ IF client.supports_tools() == True (AnthropicClient):
  │   ├─ build_prompts(request, agentic=True)
  │   └─ client.complete_agentic(system, user, TOOL_DEFINITIONS, execute_tool)
  │       │
  │       ├─ [iteration 1] stop_reason="tool_use"
  │       │   ├─ execute lookup_bank_rules(company_id, description)
  │       │   └─ append tool result → continue
  │       │
  │       ├─ [iteration 2] stop_reason="tool_use"
  │       │   ├─ execute lookup_similar_transactions(company_id, description)
  │       │   └─ append tool result → continue
  │       │
  │       └─ [iteration 3] stop_reason="end_turn"  ← exit loop, return text
  │
  └─ IF client.supports_tools() == False (OpenAI / HuggingFace):
      ├─ build_prompts(request, agentic=False)
      └─ client.complete(system, user) → raw_text
         │
         ▼
[parse_and_format(raw_text, request, client, tools_used)]
  ├─ extract_json_block(raw_text)
  ├─ _validate_category(cat, chart_of_accounts)
  │   └─ Fuzzy fallback if not exact match
  ├─ _clamp(confidence) → [0.0, 1.0]
  ├─ _parse_alternatives(...)
  └─ Return CategorizationResponse(tools_used=[...])
         │
         ▼
HTTP 200 JSON
{
  "suggested_category": "...",
  "confidence_score": 0.95,
  "confidence_label": "HIGH",
  "tools_used": ["lookup_bank_rules"],
  ...
}
```
