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
│   │   ├── categorization_service.py # Orchestrator — 3-tier pipeline
│   │   ├── context_builder.py        # Prompt construction (standard + enriched + agentic)
│   │   ├── llm_client.py             # LLM abstraction + Tier 3 agentic loop
│   │   ├── response_formatter.py     # JSON parsing & validation
│   │   └── tools.py                  # LLM tool definitions + rule engine helpers
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
- Root URL forwards all `/api/v1/` traffic to `categorizer/urls.py`.

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
| `CategorizationResponse` | Outbound response — includes `tools_used` and `categorization_tier` |
| `ErrorResponse` | Consistent error envelope |

**Confidence thresholds**: HIGH ≥ 0.80, MEDIUM ≥ 0.50, LOW < 0.50

### Layer 4 — Services (Business Logic)

#### `categorization_service.py` (Orchestrator)
Entry point: `categorize_transaction(request) → CategorizationResponse`

Implements a **3-tier pipeline** tried in order:

| Tier | Trigger | LLM calls | `model_used` |
|---|---|---|---|
| **1 — Rule Engine** | Bank rule keyword hit + CoA word-overlap mapping succeeds | 0 | `"rule-engine"` |
| **2 — Enriched LLM** | No Tier 1 hit, or rule can't map to CoA | 1 | provider model |
| **3 — Agentic** | Tier 2 confidence < 0.5 AND `client.supports_tools()` | 2–4 | provider model |

Internal helpers:
- `_try_tier1(request, client)` — calls `get_matching_rules()` then `map_rule_to_coa()`; returns a fully-formed `CategorizationResponse` or `None`

#### `context_builder.py` (Prompt Construction)
Function: `build_prompts(request, agentic=False, enrichment_context="") → (system_prompt, user_prompt)`

Three prompt variants, selected by parameters:

| Condition | System template | User template |
|---|---|---|
| `agentic=False`, no enrichment | `_SYSTEM_TEMPLATE` | `_USER_TEMPLATE` |
| `agentic=False`, enrichment provided | `_SYSTEM_TEMPLATE` | `_USER_TEMPLATE_ENRICHED` (adds `## Heuristic Context` section) |
| `agentic=True` | `_AGENTIC_SYSTEM_TEMPLATE` | `_USER_TEMPLATE_ENRICHED` |

#### `llm_client.py` (LLM Abstraction)
- `BaseLLMClient` — abstract base with `complete()`, `supports_tools()`, and `complete_agentic()`
- **Implementations**:
  - `OpenAIClient` — single-turn; `supports_tools()` → `False`
  - `HuggingFaceClient` — extends `OpenAIClient` for HF-compatible endpoints
  - `AnthropicClient` — `supports_tools()` → `True`; implements Tier 3 agentic loop
- `LLMClientFactory` — resolves and instantiates the correct client from `LLM_PROVIDER`

**`AnthropicClient.complete_agentic()` loop (Tier 3 only):**
```
messages = [user_prompt]
for iteration in range(10):           # safety cap
    response = client.messages.create(...)
    if stop_reason == "end_turn":     # model finished → extract text, return
        return text
    if stop_reason == "tool_use":     # model wants data → execute tools, continue
        execute each tool_use block → append results as user turn
    else:
        return text                   # unexpected stop (e.g. max_tokens)
```

#### `tools.py` (Tool Definitions + Heuristics Helpers)

**LLM-callable tools** — used by Tier 3 agentic loop:

| Function | Reads | Purpose |
|---|---|---|
| `lookup_bank_rules(company_id, description)` | `c{id}_BankRules.json` | Keyword-match active rules; returns formatted text for the LLM |
| `lookup_similar_transactions(company_id, description, payee)` | `c{id}_Categorized_Transactions*.json` | Word-overlap search; up to 5 past transactions with categories |
| `get_chart_of_accounts(company_id)` | `c{id}_COA.json` | Full GL account list grouped by account group |
| `execute_tool(name, inputs)` | — | Dispatcher called by the agentic loop |

**Service-layer helpers** — used directly by `categorization_service.py` (not by the LLM):

| Function | Purpose |
|---|---|
| `get_matching_rules(company_id, description)` | Returns structured rule matches as `List[Dict]` for Tier 1 rule engine |
| `map_rule_to_coa(rule, chart_of_accounts)` | Word-overlap maps a rule title to the closest CoA item; returns `(category, confidence)` or `None` |
| `build_enrichment_context(company_id, description, payee, chart_of_accounts)` | Pre-fetches rules + history; returns formatted string injected into the Tier 2 prompt |

**Confidence from word-overlap mapping:**
- ≥ 2 matching words between rule title and CoA item → confidence **0.97**
- 1 matching word → confidence **0.92**
- 0 matching words → `None` (Tier 1 miss, fall through to Tier 2)

**Shared internals:**
- `_file_cache: Dict` — module-level cache; each heuristics file loaded once per process
- `_normalize_cid()` — normalises `"c125"`, `"C125"`, `"125"` → `"125"`
- `_build_account_map(cid)` — builds `{account_id (int): display_name}` from COA file

#### `response_formatter.py` (Parse & Validate)
Function: `parse_and_format(raw_response, request, client, tools_used=None, tier=2) → CategorizationResponse`
- Extracts JSON from raw LLM text (handles markdown fences, prose wrapping)
- Validates suggested category against CoA (exact match, then fuzzy word-overlap fallback)
- Clamps confidence scores to `[0.0, 1.0]`
- Deduplicates alternatives; passes `tools_used` and `tier` into the response

### Layer 5 — Utilities
- `categorizer/utils/exception_handler.py` — global DRF exception handler
- Returns `{"error": ..., "detail": ..., "code": ...}` for all errors

### Layer 6 — Configuration
- `core/settings.py` — all LLM settings loaded from `.env` via `python-dotenv`

---

## 3. API Endpoints

| Method | Route | Purpose |
|---|---|---|
| `POST` | `/api/v1/categorize/` | Categorize a transaction via the 3-tier pipeline |
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
  "model_used": "rule-engine | gpt-4o-mini | claude-haiku-4-5-20251001 | ...",
  "provider": "heuristics | openai | anthropic | huggingface",
  "tools_used": [],
  "categorization_tier": 1
}
```

`categorization_tier` values:
- `1` — answered by the rule engine (no LLM call)
- `2` — answered by a single enriched LLM call
- `3` — answered after agentic escalation (Anthropic only)

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
| `anthropic >=0.25` (optional) | Anthropic API client — required for Tier 3 agentic escalation |
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
| `TestCategorizationServiceIntegration` | End-to-end pipeline (LLM mocked with `supports_tools=False`), failure handling |

### Middleware (`core/settings.py`)
- `SecurityMiddleware` — HTTPS/security headers
- `CommonMiddleware` — CORS, ETag

### Utility Functions

| File | Function | Purpose |
|---|---|---|
| `llm_client.py` | `extract_json_block(raw)` | Parse JSON from LLM text (fences, prose) |
| `response_formatter.py` | `_validate_category()` | Case-insensitive CoA match + fuzzy word-overlap fallback |
| `response_formatter.py` | `_fuzzy_match()` | Word-overlap matching for category names |
| `response_formatter.py` | `_clamp()` | Clamp float to `[0.0, 1.0]` |
| `tools.py` | `get_matching_rules()` | Structured rule lookup for Tier 1 rule engine |
| `tools.py` | `map_rule_to_coa()` | Word-overlap rule title → CoA item mapping |
| `tools.py` | `build_enrichment_context()` | Pre-fetch heuristics for Tier 2 prompt injection |
| `tools.py` | `_build_account_map()` | Build `{account_id → name}` dict from COA file |
| `tools.py` | `_normalize_cid()` | Normalise company ID format |

---

## 8. Design Patterns & Key Decisions

### 1. 3-Tier Hybrid Pipeline
The pipeline is optimised for cost and latency: cheap tiers are tried first and the expensive agentic tier is only reached when cheaper tiers cannot produce a confident answer.

- **Tier 1** (rule engine, 0 LLM calls) handles known vendors fast and deterministically.
- **Tier 2** (1 LLM call) handles the majority of remaining transactions with enriched context.
- **Tier 3** (2–4 LLM calls) is reserved for genuinely ambiguous transactions where the model needs to explore, and is only available with Anthropic.

### 2. Rule Engine Word-Overlap Mapping
`map_rule_to_coa()` maps a bank rule's title to the request's Chart of Accounts by computing word overlap after stop-word removal. Confidence is set to 0.97 for ≥ 2 overlapping words and 0.92 for 1. Zero overlap falls through to Tier 2 (the rule matched the description, but the category is unclear from the title alone — let the LLM decide with the rule text as context).

### 3. Tier 2 Prompt Enrichment
Rather than calling tools at LLM cost during Tier 2, the service pre-fetches bank rule matches and historical transactions in Python and injects them into `_USER_TEMPLATE_ENRICHED`. The LLM gets the same signal it would get from tools but in a single round-trip.

### 4. Agentic Escalation (Tier 3)
Only fires when Tier 2 confidence < 0.5. The model can then call tools in any order it chooses and iterate until `stop_reason == "end_turn"`. A 10-iteration cap prevents runaway loops. Non-Anthropic providers skip Tier 3 and return the Tier 2 result.

### 5. Heuristics as Ground Truth
Bank rules represent explicit decisions by a company's bookkeepers. When a rule matches, the system treats it as ground truth regardless of what the LLM might think. The Tier 3 agentic system prompt instructs the model to assign HIGH confidence (≥ 0.90) to rule matches. Tier 1 encodes this even more strictly — it returns a deterministic answer without consulting the LLM at all.

### 6. Tool File Caching
`_file_cache` in `tools.py` is a module-level dict. Each heuristics file is loaded from disk once per process. This matters for the large categorized transactions file (1,243 transactions).

### 7. `categorization_tier` + `tools_used` Observability
Every response includes `categorization_tier` (1/2/3) and `tools_used` (deduplicated list). Together they make the decision path fully observable:
- Tier 1, no tools → rule engine answered
- Tier 2, no tools → enriched LLM answered
- Tier 3, tools listed → agentic escalation answered; tools show what the model explored

### 8. Prompt Separation
Three distinct prompt templates in `context_builder.py`:
- `_SYSTEM_TEMPLATE` — vanilla single-turn instructions
- `_AGENTIC_SYSTEM_TEMPLATE` — tool-aware instructions with explicit decision strategy for Tier 3
- `_USER_TEMPLATE_ENRICHED` — extends the user prompt with a `## Heuristic Context` section for Tiers 2 and 3

All share the same JSON output schema, so `response_formatter.py` is unchanged.

### 9. Graceful Degradation
`BaseLLMClient.supports_tools()` defaults to `False`. If an OpenAI or HuggingFace provider is configured, the pipeline runs Tier 1 + Tier 2 and returns the Tier 2 result even when confidence is low — Tier 3 is silently skipped.

### 10. Category Validation with Fuzzy Fallback
1. Exact match (case-insensitive)
2. Word-overlap fuzzy match
3. Raises `ValueError` if neither matches

Prevents silent mismatches where the LLM returns a slightly different account name.

### 11. Multi-Tenant by Design
Company ID, industry, CoA, and history are all runtime inputs. Heuristics files are discovered by naming convention (`c{id}_BankRules.json`). No hardcoded company logic anywhere.

### 12. PII-Safe Logging
Logs tier, model, provider, category, confidence, and tool names — never transaction descriptions or payee names.

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
| c125 | ~10 rules | 20 loaded (280 total, paginated) | 1,243 categorized |
| c417 | ~35 rules | 20 loaded (paginated) | available |

> **Note:** The COA JSON files contain only page 0 (20 accounts). Bank rule account IDs that fall outside this page resolve to `Account#N` in tool output, but rule titles still provide sufficient category signal to the model.

### Evaluation Script (`evaluate.py`)
- Runs all 5 samples through the live pipeline (requires `.env` configured)
- Reports: top-1 accuracy, confidence distribution, per-sample tier and reasoning
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
  ├─━━ TIER 1: Rule Engine ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  │    get_matching_rules(company_id, description)   ← tools.py
  │      └─ load c{id}_BankRules.json, keyword-match active rules
  │    map_rule_to_coa(rule, chart_of_accounts)      ← tools.py
  │      └─ word-overlap between rule title and CoA items
  │    HIT  → return CategorizationResponse(tier=1, model_used="rule-engine")
  │    MISS ↓
  │
  ├─━━ TIER 2: Enriched Single LLM Call ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  │    build_enrichment_context(company_id, description, payee, CoA)
  │      ├─ lookup_bank_rules(...)       → formatted rule matches (or "no rules")
  │      └─ lookup_similar_transactions(...) → formatted history (or "no history")
  │    build_prompts(request, agentic=False, enrichment_context=...)
  │      └─ _USER_TEMPLATE_ENRICHED: injects "## Heuristic Context" section
  │    client.complete(system_prompt, user_prompt)   ← one LLM call
  │    parse_and_format(raw, request, client, tier=2)
  │    confidence >= 0.5 → return CategorizationResponse(tier=2)
  │    confidence <  0.5 ↓
  │
  └─━━ TIER 3: Agentic Escalation (Anthropic only) ━━━━━━━━━━━━━━━━━━━━━━━━━━━
       client.supports_tools() == False → return Tier 2 result as-is
       client.supports_tools() == True  ↓
       build_prompts(request, agentic=True, enrichment_context=...)
       client.complete_agentic(system, user, TOOL_DEFINITIONS, execute_tool)
         │
         ├─ [iter 1] stop_reason="tool_use"
         │   model calls lookup_bank_rules(company_id, description)
         │   → execute → append tool_result → continue
         │
         ├─ [iter 2] stop_reason="tool_use"
         │   model calls lookup_similar_transactions(company_id, description)
         │   → execute → append tool_result → continue
         │
         └─ [iter 3] stop_reason="end_turn"   ← exit loop
       parse_and_format(raw, request, client, tools_used=[...], tier=3)
       return CategorizationResponse(tier=3, tools_used=[...])
         │
         ▼
HTTP 200 JSON
{
  "suggested_category": "Meals & Entertainment",
  "confidence_score": 0.92,
  "confidence_label": "HIGH",
  "reasoning": "Bank rule 'Uber Eats - Meals' matched keyword 'Uber Eats'.",
  "model_used": "rule-engine",
  "provider": "heuristics",
  "tools_used": [],
  "categorization_tier": 1
}
```
