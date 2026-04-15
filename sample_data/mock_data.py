"""
mock_data.py — Sample requests and expected outputs for manual testing & evaluation.
No real company or PII data.
"""

CHART_OF_ACCOUNTS = [
    "Software & Subscriptions",
    "Office Supplies",
    "Travel & Lodging",
    "Meals & Entertainment",
    "Advertising & Marketing",
    "Professional Services",
    "Utilities",
    "Payroll & Benefits",
    "Equipment & Hardware",
    "Miscellaneous",
]

HISTORICAL_TRANSACTIONS = [
    {
        "description": "AWS monthly bill",
        "payee": "Amazon Web Services",
        "amount": 340.50,
        "category": "Software & Subscriptions",
    },
    {
        "description": "Team lunch at Chipotle",
        "payee": "Chipotle Mexican Grill",
        "amount": 87.20,
        "category": "Meals & Entertainment",
    },
    {
        "description": "Flight to SF for conference",
        "payee": "United Airlines",
        "amount": 420.00,
        "category": "Travel & Lodging",
    },
    {
        "description": "Google Workspace subscription",
        "payee": "Google",
        "amount": 72.00,
        "category": "Software & Subscriptions",
    },
    {
        "description": "Facebook Ads campaign",
        "payee": "Meta Platforms",
        "amount": 500.00,
        "category": "Advertising & Marketing",
    },
]

# ── 5 sample categorization requests ──────────────────────────────────────────

SAMPLE_REQUESTS = [
    {
        "_description": "SaaS subscription — should map to Software & Subscriptions",
        "transaction": {
            "description": "Monthly charge - Notion Pro plan",
            "payee": "Notion Labs",
            "amount": 16.00,
            "currency": "USD",
            "date": "2024-05-01",
        },
        "company_id": "acme-corp-001",
        "industry": "Technology / SaaS",
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "historical_transactions": HISTORICAL_TRANSACTIONS,
        "_expected_category": "Software & Subscriptions",
        "_expected_confidence_min": 0.85,
    },
    {
        "_description": "Team meal — should map to Meals & Entertainment",
        "transaction": {
            "description": "Team dinner - client meeting",
            "payee": "The Capital Grille",
            "amount": 215.40,
            "currency": "USD",
            "date": "2024-05-08",
        },
        "company_id": "acme-corp-001",
        "industry": "Technology / SaaS",
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "historical_transactions": HISTORICAL_TRANSACTIONS,
        "_expected_category": "Meals & Entertainment",
        "_expected_confidence_min": 0.80,
    },
    {
        "_description": "Hotel stay — should map to Travel & Lodging",
        "transaction": {
            "description": "Marriott hotel — 2 nights NYC",
            "payee": "Marriott International",
            "amount": 480.00,
            "currency": "USD",
            "date": "2024-05-15",
        },
        "company_id": "acme-corp-001",
        "industry": "Technology / SaaS",
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "historical_transactions": HISTORICAL_TRANSACTIONS,
        "_expected_category": "Travel & Lodging",
        "_expected_confidence_min": 0.85,
    },
    {
        "_description": "Legal invoice — should map to Professional Services",
        "transaction": {
            "description": "Legal retainer Q2 invoice",
            "payee": "Wilson Sonsini LLP",
            "amount": 3200.00,
            "currency": "USD",
            "date": "2024-05-20",
        },
        "company_id": "acme-corp-001",
        "industry": "Technology / SaaS",
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "historical_transactions": HISTORICAL_TRANSACTIONS,
        "_expected_category": "Professional Services",
        "_expected_confidence_min": 0.80,
    },
    {
        "_description": "Ink cartridges — should map to Office Supplies",
        "transaction": {
            "description": "Staples order - printer ink and paper",
            "payee": "Staples Inc.",
            "amount": 67.99,
            "currency": "USD",
            "date": "2024-05-22",
        },
        "company_id": "acme-corp-001",
        "industry": "Technology / SaaS",
        "chart_of_accounts": CHART_OF_ACCOUNTS,
        "historical_transactions": HISTORICAL_TRANSACTIONS,
        "_expected_category": "Office Supplies",
        "_expected_confidence_min": 0.75,
    },
]

# ── Expected JSON outputs (for README documentation) ──────────────────────────

EXPECTED_OUTPUTS = [
    {
        "transaction_description": "Monthly charge - Notion Pro plan",
        "payee": "Notion Labs",
        "suggested_category": "Software & Subscriptions",
        "confidence_score": 0.92,
        "confidence_label": "HIGH",
        "alternative_categories": [
            {
                "category": "Miscellaneous",
                "confidence": 0.05,
                "reasoning": "Catch-all if category not clearly identifiable.",
            }
        ],
        "reasoning": "Notion Pro is a SaaS product; monthly charges from software vendors map directly to Software & Subscriptions.",
        "model_used": "gpt-4o-mini",
        "provider": "openai",
    },
]
