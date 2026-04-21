"""
tools.py — Tool definitions and implementations for the agentic categorization loop.

The LLM agent has access to three tools that let it look up company-specific data
before making a categorization decision:

  1. lookup_bank_rules       — keyword rules defined by the company's accountants
  2. lookup_similar_transactions — historical categorized transactions
  3. get_chart_of_accounts   — full GL account list with codes and groups
"""
from __future__ import annotations

import glob
import json
import logging
import os
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Heuristics directory is at the project root, two levels above this file.
HEURISTICS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "heuristics",
)

# Module-level cache — avoids re-reading large files on every agentic tool call.
_file_cache: Dict[str, Any] = {}


# ─── Tool definitions (Anthropic API format) ─────────────────────────────────

TOOL_DEFINITIONS: List[Dict[str, Any]] = [
    {
        "name": "lookup_bank_rules",
        "description": (
            "Look up company-defined bank rules that match a transaction description. "
            "These are keyword-based rules configured by the company's accountants that "
            "map transaction text patterns to specific GL accounts. Always call this first "
            "— a matching rule represents an explicit bookkeeper preference and should "
            "be treated as ground truth."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Company identifier, e.g. '125' or 'c125'.",
                },
                "description": {
                    "type": "string",
                    "description": "The transaction description to match against bank rules.",
                },
            },
            "required": ["company_id", "description"],
        },
    },
    {
        "name": "lookup_similar_transactions",
        "description": (
            "Search the company's history of categorized transactions for entries "
            "with similar descriptions or payee names. Returns up to 5 matches showing "
            "how this company previously categorized comparable transactions. Use this "
            "when bank rules produce no match, to infer category from past behavior."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Company identifier.",
                },
                "description": {
                    "type": "string",
                    "description": "Transaction description to search for.",
                },
                "payee": {
                    "type": "string",
                    "description": "Optional payee/vendor name to narrow the search.",
                },
            },
            "required": ["company_id", "description"],
        },
    },
    {
        "name": "get_chart_of_accounts",
        "description": (
            "Retrieve the company's full Chart of Accounts — account codes, display "
            "names, and account groups (ASSETS, LIABILITIES, EQUITY, INCOME, EXPENSES, "
            "COGS). Use this to understand the real GL structure and available accounts "
            "when you need more detail than what the request's chart_of_accounts list provides."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "company_id": {
                    "type": "string",
                    "description": "Company identifier.",
                },
            },
            "required": ["company_id"],
        },
    },
]


# ─── Tool implementations ─────────────────────────────────────────────────────

def lookup_bank_rules(company_id: str, description: str) -> str:
    cid = _normalize_cid(company_id)
    path = os.path.join(HEURISTICS_DIR, f"c{cid}_BankRules.json")
    if not os.path.exists(path):
        return f"No bank rules file found for company '{company_id}'."

    data = _load_json(path)
    rules: List[Dict] = data.get("data", {}).get("list", [])
    desc_lower = description.lower()
    account_map = _build_account_map(cid)

    matches = []
    for rule in rules:
        if not rule.get("isActive") or rule.get("isDeleted"):
            continue
        for field in rule.get("statementMatchesFildes", []):
            pattern = field.get("fieldText", "").lower()
            if pattern and pattern in desc_lower:
                account_ids = [
                    item.get("account")
                    for item in rule.get("ratioLineItems", [])
                    if item.get("account")
                ]
                account_names = [
                    account_map.get(aid, f"Account#{aid}") for aid in account_ids
                ]
                matches.append(
                    f'• Rule: "{rule["title"]}" | '
                    f'Matched keyword: "{field["fieldText"]}" | '
                    f'Maps to: {", ".join(account_names)} | '
                    f'Type: {rule.get("ruleCategoryName", "N/A")}'
                )
                break  # one match per rule is sufficient

    if not matches:
        return f'No bank rules matched for description: "{description}"'
    return "Matching bank rules:\n" + "\n".join(matches)


def lookup_similar_transactions(
    company_id: str, description: str, payee: str = ""
) -> str:
    cid = _normalize_cid(company_id)
    pattern = os.path.join(HEURISTICS_DIR, f"c{cid}_Categorized_Transactions*.json")
    files = glob.glob(pattern)
    if not files:
        return f"No categorized transactions file found for company '{company_id}'."

    data = _load_json(files[0])
    # Handle the paginated response format: data["data"]["items"]
    items = (
        data.get("data", {}).get("items")
        or data.get("items")
        or data.get("transactions")
        or data.get("content")
        or (data if isinstance(data, list) else [])
    )

    desc_lower = description.lower()
    payee_lower = payee.lower() if payee else ""
    account_map = _build_account_map(cid)

    matches = []
    for txn in items:
        txn_desc = str(txn.get("description", txn.get("name", ""))).lower()
        txn_payee = str(txn.get("payeeName", txn.get("merchant_name", ""))).lower()

        desc_hit = any(word in txn_desc for word in desc_lower.split() if len(word) > 3)
        payee_hit = payee_lower and (
            payee_lower in txn_payee or txn_payee in payee_lower
        )

        if desc_hit or payee_hit:
            raw_cat = txn.get("category")
            if isinstance(raw_cat, int):
                category = account_map.get(raw_cat, f"Account#{raw_cat}")
            else:
                category = str(raw_cat) if raw_cat else "Unknown"

            matches.append(
                f'• "{txn.get("description", txn.get("name", "N/A"))}" '
                f"| Payee: {txn.get('payeeName', 'N/A')} "
                f"| Category: {category} "
                f"| Amount: {txn.get('amount', 'N/A')}"
            )
            if len(matches) >= 5:
                break

    if not matches:
        return f'No similar historical transactions found for: "{description}"'
    return "Similar historical transactions:\n" + "\n".join(matches)


def get_chart_of_accounts(company_id: str) -> str:
    cid = _normalize_cid(company_id)
    path = os.path.join(HEURISTICS_DIR, f"c{cid}_COA.json")
    if not os.path.exists(path):
        return f"No Chart of Accounts file found for company '{company_id}'."

    data = _load_json(path)
    accounts = data.get("content", [])

    groups: Dict[str, List[str]] = {}
    for acct in accounts:
        if acct.get("isHidden") or acct.get("isDisabled"):
            continue
        group = acct.get("group", "OTHER")
        display = acct.get("displayName") or acct.get("name", "")
        if display:
            groups.setdefault(group, []).append(display)

    lines: List[str] = []
    for group in sorted(groups):
        accts = sorted(groups[group])
        lines.append(f"\n{group}:")
        lines.extend(f"  - {a}" for a in accts[:25])
        if len(accts) > 25:
            lines.append(f"  ... and {len(accts) - 25} more accounts")

    total = sum(len(v) for v in groups.values())
    header = f"Chart of Accounts ({total} accounts):"
    return header + "\n".join(lines)


# ─── Tool dispatcher ──────────────────────────────────────────────────────────

def execute_tool(name: str, inputs: Dict[str, Any]) -> str:
    """Dispatch a tool call by name and return a string result to feed back to the model."""
    logger.info("Tool call | name=%s inputs=%s", name, list(inputs.keys()))
    try:
        if name == "lookup_bank_rules":
            return lookup_bank_rules(**inputs)
        if name == "lookup_similar_transactions":
            return lookup_similar_transactions(**inputs)
        if name == "get_chart_of_accounts":
            return get_chart_of_accounts(**inputs)
        return f"Unknown tool: '{name}'"
    except Exception as exc:
        logger.warning("Tool '%s' raised an exception: %s", name, exc)
        return f"Tool error in '{name}': {exc}"


# ─── Private helpers ──────────────────────────────────────────────────────────

def _normalize_cid(company_id: str) -> str:
    """'c125', 'C125', '125' → '125'"""
    return str(company_id).lstrip("cC")


def _load_json(path: str) -> Any:
    if path not in _file_cache:
        with open(path, "r", encoding="utf-8") as f:
            _file_cache[path] = json.load(f)
    return _file_cache[path]


def _build_account_map(cid: str) -> Dict[int, str]:
    """Returns {account_id (int): display_name} from the company's COA file."""
    path = os.path.join(HEURISTICS_DIR, f"c{cid}_COA.json")
    if not os.path.exists(path):
        return {}
    data = _load_json(path)
    return {
        acct["id"]: acct.get("displayName") or acct.get("name", "")
        for acct in data.get("content", [])
        if "id" in acct
    }
