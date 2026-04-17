# ozon-mcp

> MCP server for the Ozon Seller & Performance APIs.
> Connect any AI agent to your Ozon cabinet in minutes.

[![CI](https://github.com/PCDCK/ozon-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/PCDCK/ozon-mcp/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.12%2B-blue)
![License](https://img.shields.io/badge/license-MIT-green)
![MCP](https://img.shields.io/badge/MCP-compatible-orange)

ozon-mcp is a knowledge-rich MCP server that turns the entire Ozon
seller toolkit into 15 high-leverage tools. AI agents (Claude, Cursor,
Cline, Continue, Goose, Zed, …) can search the API in Russian or
English, drill into any of 466 methods with a fully-resolved JSON
Schema, and execute calls with built-in safety guards. Subscription-
aware, automatic pagination over all 4 cursor styles, retry/back-off
on 429s, and 13 ready-to-use analytical workflows.

**Key facts:** 466 indexed methods (420 Seller + 46 Performance),
55 sections, 5 subscription tiers modelled, 38 paginated endpoints
auto-walked, 43 destructive methods double-gated, 13 curated
workflows for typical seller scenarios.

---

## Quick start

### Prerequisites

- Python 3.12 or 3.13
- `uv` package manager — install with
  `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Ozon Seller API credentials (Client-Id + Api-Key) — get them at
  <https://seller.ozon.ru/app/settings/api-keys>

### Installation

```bash
git clone https://github.com/PCDCK/ozon-mcp.git
cd ozon-mcp
uv sync
```

### Verify it works

```bash
uv run ozon-mcp --help
```

You should see the FastMCP usage line. The server speaks the MCP stdio
protocol — point any compatible client at it (instructions below).

---

## Connecting to your AI agent

ozon-mcp uses the standard MCP stdio transport. Every example below
exposes the same 15 tools — pick whichever client you already use.

### Claude Desktop

Edit:
`~/Library/Application Support/Claude/claude_desktop_config.json`
(macOS) or `%APPDATA%\Claude\claude_desktop_config.json` (Windows).

```json
{
  "mcpServers": {
    "ozon": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/ozon-mcp",
                "run", "ozon-mcp"],
      "env": {
        "OZON_CLIENT_ID": "your-seller-client-id",
        "OZON_API_KEY": "your-seller-api-key",
        "OZON_PERFORMANCE_CLIENT_ID": "your-perf-client-id",
        "OZON_PERFORMANCE_CLIENT_SECRET": "your-perf-secret"
      }
    }
  }
}
```

### Claude Code (CLI)

```bash
cd /path/to/ozon-mcp
claude mcp add ozon -- uv run ozon-mcp
```

Or add to `~/.claude/mcp.json` with the same shape as the Claude
Desktop config above.

### Cursor

Settings → MCP → Add new MCP Server, or edit `~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "ozon": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/ozon-mcp",
                "run", "ozon-mcp"]
    }
  }
}
```

### Windsurf

Edit `~/.codeium/windsurf/mcp_config.json`:

```json
{
  "mcpServers": {
    "ozon": {
      "command": "uv",
      "args": ["--directory", "/absolute/path/to/ozon-mcp",
                "run", "ozon-mcp"]
    }
  }
}
```

### Cline (VS Code extension)

Cline → Settings → MCP Servers → Add:

```json
{
  "ozon": {
    "command": "uv",
    "args": ["--directory", "/absolute/path/to/ozon-mcp",
              "run", "ozon-mcp"]
  }
}
```

### Continue.dev

Edit `~/.continue/config.json`:

```json
{
  "experimental": {
    "modelContextProtocolServers": [
      {
        "transport": {
          "type": "stdio",
          "command": "uv",
          "args": ["--directory", "/absolute/path/to/ozon-mcp",
                    "run", "ozon-mcp"]
        }
      }
    ]
  }
}
```

### Goose, Zed, or any other MCP client

Any client that speaks MCP stdio will work. Generic config:

```yaml
command: uv
args: ["--directory", "/absolute/path/to/ozon-mcp", "run", "ozon-mcp"]
transport: stdio
env:
  OZON_CLIENT_ID: ...
  OZON_API_KEY: ...
```

Browse the official MCP client list at
<https://modelcontextprotocol.io/clients>.

---

## Usage examples

All examples below show realistic responses copied from
[`tests/fixtures/responses/`](tests/fixtures/responses/) — anonymized
identifiers (`99000001`, `TEST-SKU-001`) but real shape.

### Example 1 — Get all your products

> **You:** Use `ozon_fetch_all` with `operation_id="ProductAPI_GetProductList"`
> to get all my products.

The agent calls:

```json
{
  "operation_id": "ProductAPI_GetProductList",
  "params": {"filter": {"visibility": "ALL"}},
  "max_items": 10000
}
```

Server walks the `last_id` cursor automatically and returns:

```json
{
  "ok": true,
  "items": [
    {"product_id": 99000001, "offer_id": "TEST-SKU-001", "archived": false},
    {"product_id": 99000002, "offer_id": "TEST-SKU-002", "archived": false},
    {"product_id": 99000003, "offer_id": "TEST-SKU-003", "archived": true}
  ],
  "total_fetched": 3,
  "truncated": false,
  "pages_fetched": 1
}
```

### Example 2 — Find products at risk of going out of stock

> **You:** Run the `oos_risk_analysis` workflow for my cabinet.

Agent first inspects the workflow:

```json
ozon_get_workflow({"name": "oos_risk_analysis"})
```

→ tells the agent to call `AnalyticsAPI_StocksTurnover` (rate-limited
to 1 req/min — the server's per-endpoint queue handles that for you)
and how to interpret `turnover_grade`. The call returns:

```json
{
  "items": [
    {"sku": 99000001, "current_stock": 12, "ads": 1.5,
     "idc": 8.0, "turnover_grade": "DEFICIT",
     "turnover_grade_cluster": "DEFICIT_GROWING"},
    {"sku": 99000002, "current_stock": 25, "ads": 0.8,
     "idc": 31.25, "turnover_grade": "OPTIMAL",
     "turnover_grade_cluster": "OPTIMAL_FALLING"},
    {"sku": 99000003, "current_stock": 0, "ads": 0.0,
     "idc": 0.0, "turnover_grade": "NO_SALES",
     "turnover_grade_cluster": "NO_SALES"}
  ]
}
```

The workflow's `interpret` field tells the agent to flag SKUs where
`idc < 14` or `turnover_grade ∈ {DEFICIT, NO_SALES}` and surface them
sorted by `idc asc`.

### Example 3 — Full cabinet health check

> **You:** Check the health of my Ozon cabinet using the
> `cabinet_health_check` workflow.

The workflow tells the agent to read three endpoints in parallel —
`RatingAPI_RatingSummaryV1`, `SellerAPI_SellerInfo`,
`AverageDeliveryTimeSummary`. The first call returns:

```json
{
  "groups": [
    {
      "group_name": "Выполнение заказов",
      "items": [
        {"rating": "rating_on_time", "name": "Процент заказов вовремя",
         "current_value": 97.5, "status": "OK", "value_type": "PERCENT"},
        {"rating": "rating_review_avg_score", "name": "Средняя оценка",
         "current_value": 4.7, "status": "OK", "value_type": "RATING"}
      ]
    },
    {
      "group_name": "Качество сервиса",
      "items": [
        {"rating": "rating_price_index", "name": "Индекс цен",
         "current_value": 1.01, "status": "OK", "value_type": "INDEX"}
      ]
    }
  ],
  "premium_scores": [
    {"rating": "rating_on_time", "value": 97.5,
     "penalty_score_per_day": 0, "scope": "premium_plus"}
  ]
}
```

### Example 4 — Analyze product pricing

> **You:** Which of my products have a red price index?

Agent runs the `pricing_analysis` workflow and inspects the
`price_indexes.color_index` field on every item:

```json
{
  "product_id": 99000001, "offer_id": "TEST-SKU-001",
  "price": {"price": "399.0000", "marketing_seller_price": "399.0000",
             "min_price": "299.0000"},
  "price_indexes": {
    "color_index": "WITHOUT_INDEX",
    "ozon_index_data": {"minimal_price": "395.0000",
                          "price_index_value": 1.01}
  },
  "commissions": {"sales_percent_fbo": 0.13, "sales_percent_fbs": 0.13}
}
```

The workflow's `common_mistakes` list reminds the agent to compare
against `marketing_seller_price` (the actual buyer-facing price), not
just the base `price`.

### Example 5 — Content audit

> **You:** Find products with low content rating and tell me what to
> improve.

Agent runs `content_audit`, gets per-SKU ratings + the list of
attributes that would lift the score:

```json
{
  "products": [
    {
      "sku": 99000001, "rating": 85,
      "groups": [
        {"key": "media", "rating": 100},
        {"key": "characteristics", "rating": 75,
         "improve_attributes": [
           {"id": 4191, "name": "Цвет"},
           {"id": 8292, "name": "Материал"}
         ],
         "improve_at_least": 4}
      ]
    }
  ]
}
```

The workflow tells the agent that a `+10` lift to `rating` measurably
improves search ranking — so filling in those two attributes is worth
~4 points.

---

## Available tools (15)

| Tool | What it does |
|---|---|
| `ozon_call_method` | Execute any Ozon API method with safety + subscription guards |
| `ozon_fetch_all` | Auto-paginate — get every page, not just the first |
| `ozon_describe_method` | Full docs for a method: schema, examples, rate limit, quirks |
| `ozon_search_methods` | BM25 search across 466 methods (Russian or English, with stemming) |
| `ozon_list_sections` | Browse the API by section |
| `ozon_get_section` | All methods inside one section |
| `ozon_list_workflows` | List ready-made analytical workflows (filterable by category) |
| `ozon_get_workflow` | Full step-by-step plan for one workflow |
| `ozon_get_related_methods` | Methods that work well together (auto-extracted graph) |
| `ozon_get_examples` | Curated request/response examples for a method |
| `ozon_get_rate_limits` | Per-method, per-section, or all |
| `ozon_get_subscription_status` | Read your current cabinet's subscription tier |
| `ozon_list_methods_for_subscription` | What you unlock on a given tier |
| `ozon_get_swagger_meta` | Check that bundled API specs are still fresh |
| `ozon_get_error_catalog` | Look up any Ozon error code |

---

## Ready-made workflows (13)

Workflows are curated step-by-step recipes. Use
`ozon_get_workflow("name")` to fetch the full plan, including
`interpret`, `when_to_use`, `common_mistakes`, and the recommended
DB schema for sync-style workflows.

| Workflow | Category | What it solves |
|---|---|---|
| `oos_risk_analysis` | analytics | Find products about to go out of stock |
| `cabinet_health_check` | health | Check all seller-rating metrics in one shot |
| `content_audit` | content | Find low-content-rating cards + actionable attributes |
| `pricing_analysis` | pricing | Find products with non-competitive pricing |
| `warehouse_stock_distribution` | warehouse | Per-warehouse stock breakdown for FBO |
| `sync_products_catalog` | catalog | Full product catalog snapshot |
| `sync_orders_fbo` | orders | Incremental FBO order sync |
| `sync_orders_fbs` | orders | Incremental FBS / rFBS order sync |
| `sync_finance_transactions` | finance | Finance transactions for unit economics |
| `sync_analytics_daily` | analytics | Daily revenue / orders time series |
| `sync_advertising_campaigns` | advertising | Performance API ads catalog |
| `sync_warehouse_stocks` | warehouse | FBS warehouse stocks |
| `sync_returns_rfbs` | returns | rFBS returns sync |

---

## API coverage

| API | Methods | Sections |
|---|---|---|
| Ozon Seller API | 420 | 49 |
| Ozon Performance API | 46 | 6 |
| **Total** | **466** | **55** |

Subscription tiers modelled (low → high):
`LITE → STANDARD → PREMIUM → PREMIUM_PLUS → PREMIUM_PRO`.

---

## Key features

### Subscription-aware

The server knows which methods are gated on Premium tiers and refuses
the call before it leaves your machine — saves your API quota:

```json
{
  "error": "subscription_gate",
  "error_type": "subscription_gate",
  "code": 7,
  "message": "Endpoint requires PREMIUM_PRO, cabinet has PREMIUM_PLUS",
  "operation_id": "ProductPricesDetails",
  "required_tier": "PREMIUM_PRO",
  "cabinet_tier": "PREMIUM_PLUS",
  "retryable": false,
  "http_call_skipped": true
}
```

### Rate-limit management

- Auto-retry with exponential back-off on 429.
- Honours `Retry-After` (both delta-seconds and RFC 7231 HTTP-date).
- Per-endpoint semaphore for slow methods (e.g.
  `/v1/analytics/turnover/stocks` is hard-limited to 1 req/min on the
  Ozon side — the server queues parallel calls automatically).

### Auto-pagination

`ozon_fetch_all` handles all four pagination patterns Ozon uses:
`offset/limit`, `cursor`, `last_id`, `page_number`. It also detects
the rare case where the server returns the same cursor twice in a
row and breaks the loop instead of spinning forever.

```python
ozon_fetch_all(
  operation_id="ProductAPI_GetProductList",
  params={"filter": {"visibility": "ALL"}},
  max_items=10_000,
)
# → {"items": [...all products...], "total_fetched": 847,
#    "truncated": false, "pages_fetched": 1}
```

### Unified error envelope

Every tool that can fail returns the same shape — easy to branch on
in any agent or downstream code:

```json
{
  "error": "rate_limit_exceeded",
  "error_type": "rate_limit | subscription_gate | not_found | invalid_params | server_error | timeout | auth | forbidden | conflict | ...",
  "message": "Human-readable explanation",
  "code": 429,
  "operation_id": "AnalyticsAPI_StocksTurnover",
  "endpoint": "/v1/analytics/turnover/stocks",
  "retryable": true,
  "retry_after_seconds": 60
}
```

### Safety classification baked into the catalog

Every method carries a `safety` field — `read`, `write`, or
`destructive`. Write requires `confirm_write=True`; destructive
requires both `confirm_write=True` AND
`i_understand_this_modifies_data=True`. Heuristics from the schema
extractor are reinforced by 43 curated `safety_warning` entries in
`quirks.yaml` so the agent always sees a clear reminder before
mutating anything.

---

## Keeping the API specs up to date

Ozon refreshes their swagger periodically. To sync:

```bash
cd parser/                               # the parser repo / drop-zone
python parse_swagger.py                  # downloads + sanitises both APIs
cp seller_swagger.json ../src/ozon_mcp/data/
cp perf_swagger.json   ../src/ozon_mcp/data/
cp swagger_meta.json   ../src/ozon_mcp/data/
```

Run `ozon_get_swagger_meta` to confirm the bundled snapshot is fresh
(the CI also fails the build when the snapshot is older than 14
days).

---

## Development

```bash
git clone https://github.com/PCDCK/ozon-mcp.git
cd ozon-mcp
uv sync --extra dev

# Tests (≈25s, 274 currently)
uv run pytest tests/ --ignore=tests/live

# Code quality
uv run ruff check src tests
uv run mypy src/ozon_mcp

# Coverage
uv run pytest tests/ --ignore=tests/live --cov=src/ozon_mcp \
    --cov-report=term-missing
```

See [CONTRIBUTING.md](CONTRIBUTING.md) for how to add knowledge
(workflows, examples, quirks, subscription overrides).

---

## License

[MIT](LICENSE)
