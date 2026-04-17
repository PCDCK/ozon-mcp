# Contributing to ozon-mcp

Thanks for your interest! Most contributions land in one of three
buckets:

1. **Bug fixes** — schema extraction, transport, paginator edge cases.
2. **Curated knowledge** — examples, quirks, business context,
   workflows, subscription requirements.
3. **New features** — additional MCP tools, transport improvements,
   extra pagination types.

---

## Development setup

```bash
git clone https://github.com/PCDCK/ozon-mcp.git
cd ozon-mcp
uv sync --extra dev

# Test suite (≈25s, 274 tests)
uv run pytest tests/ --ignore=tests/live

# Lint and type check
uv run ruff check src tests
uv run mypy src/ozon_mcp

# Coverage report
uv run pytest tests/ --ignore=tests/live --cov=src/ozon_mcp \
    --cov-report=term-missing
```

Required Python: 3.12 or 3.13. Strict mypy and full ruff selection are
enforced in CI.

---

## How to add knowledge

Knowledge YAML files live in `src/ozon_mcp/knowledge/`. They are
loaded once at server start and surfaced through `ozon_describe_method`
and the dedicated lookup tools. Every change is validated by
`tests/unit/test_knowledge_integrity.py`.

### Business context for a method

File: [`src/ozon_mcp/knowledge/quirks.yaml`](src/ozon_mcp/knowledge/quirks.yaml).

```yaml
- operation_id: AnalyticsAPI_StocksTurnover
  api: seller
  title: "Business context: stock-out planning"
  description: |
    Single call returns ads / idc / turnover_grade for every SKU.
  business_context: |
    The single best signal for purchase planning. idc < 14 means the
    item runs out within two weeks at current sell-through. Hard
    rate-limited to 1 req/min on the Ozon side.
  when_to_use:
    - "Daily OOS-risk monitoring"
    - "FBO supply planning"
  common_mistakes:
    - "Calling in a loop without backoff — guaranteed 429"
  severity: info
  extracted_from: curated
```

### Usage example

File: [`src/ozon_mcp/knowledge/examples.yaml`](src/ozon_mcp/knowledge/examples.yaml).

```yaml
- operation_id: ProductAPI_GetProductList
  title: "First 100 active products"
  description: |
    Minimal useful call — for UI / catalog preview. Use the returned
    last_id as the offset for the next page or call ozon_fetch_all
    for full pagination.
  request:
    filter:
      visibility: ALL
    last_id: ""
    limit: 100
  response_excerpt:
    result:
      items:
        - product_id: 99000001
          offer_id: TEST-SKU-001
      last_id: WyI5OTAwMDAwMSJd
      total: 1
```

Anonymize identifiers — use the `99000xxx` range for `product_id` /
`sku` / `id`, `99100xxx` for `warehouse_id`, and the `TEST-SKU-`
prefix for `offer_id`. The integrity test
`test_no_real_credentials_in_fixtures` enforces this for fixtures and
encourages it for examples.

### New workflow

File: [`src/ozon_mcp/knowledge/workflows.yaml`](src/ozon_mcp/knowledge/workflows.yaml).

```yaml
- name: my_new_workflow
  category: analytics    # one of: catalog, orders, analytics, health,
                         #         pricing, content, advertising,
                         #         warehouse, returns, finance
  title: "Brief title"
  description: |
    What problem this workflow solves and when an agent should pick it.
  recommended_schedule: every 30 minutes  # optional
  steps:
    - n: 1
      operation_id: SomeAPI_SomeMethod
      purpose: "What this step accomplishes"
      pagination: "cursor / offset / page_number"
      notes: "Anything the agent has to know"
  rate_limit_note: "Aggregated rate-limit guidance"
  subscription_note: "Which tier is required"
  interpret: |
    How to read the response — which fields matter, what to filter on.
  when_to_use:
    - "Concrete situation 1"
    - "Concrete situation 2"
  common_mistakes:
    - "Pitfall the agent should avoid"
  gotchas:
    - "Schema-level surprises"
  review_status: draft   # promote to "verified" after live validation
```

Single-step workflows do not contribute edges to the related-methods
graph — pair them with a complementary step or accept that
`ozon_get_related_methods` for that endpoint will be empty.

### Subscription requirement

File: [`src/ozon_mcp/knowledge/subscription_overrides.yaml`](src/ozon_mcp/knowledge/subscription_overrides.yaml).

```yaml
- operation_id: ProductPricesDetails
  required_tier: PREMIUM_PRO     # PREMIUM | PREMIUM_PLUS | PREMIUM_PRO | unknown | null
  source: swagger+empirical      # how you confirmed the requirement
  note: "Confirmed 403 on PREMIUM_PLUS, 200 on PREMIUM_PRO (2026-04-15)"
```

`null` means the method has no subscription requirement; `unknown`
means we don't have evidence either way and the gate should defer to
Ozon. Both skip the pre-flight check.

### Description override

File: [`src/ozon_mcp/knowledge/descriptions_overrides.yaml`](src/ozon_mcp/knowledge/descriptions_overrides.yaml).

Use this when Ozon's swagger ships an empty `description` for a hot-
path method. The override is applied at server startup before the BM25
search index is built so the method becomes findable.

---

## Pull request checklist

- [ ] `uv run pytest tests/ --ignore=tests/live` is green
- [ ] `uv run ruff check src tests` is green
- [ ] `uv run mypy src/ozon_mcp` is green
- [ ] `tests/unit/test_knowledge_integrity.py` is green
- [ ] [CHANGELOG.md](CHANGELOG.md) updated under `## [Unreleased]`
- [ ] No real API credentials in code, tests, or fixtures
- [ ] If you added a YAML entry — `review_status` / `source` set
- [ ] If you added a new MCP tool — added an integration test for it

---

## Reporting issues

For bug reports include:

- The MCP **tool name** (e.g. `ozon_call_method`)
- The Ozon **`operation_id`** (e.g. `ProductAPI_GetProductList`)
- The **request params** you sent (sanitised — no real `Client-Id` or
  `Api-Key`)
- The **actual** response (the full envelope, not just the message)
- The **expected** response

Use the issue templates in
[`.github/ISSUE_TEMPLATE/`](.github/ISSUE_TEMPLATE/) — they prompt for
each of those fields.

---

## Live tests

The `tests/live/` suite hits the real Ozon API and is **never** run by
default. To run it locally:

```bash
export OZON_CLIENT_ID=...
export OZON_API_KEY=...
uv run pytest tests/live -m live
```

These tests use only `read` methods but consume real API quota. Keep
them minimal and idempotent.
