# Changelog

All notable changes to ozon-mcp follow [keep-a-changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.6.1] — 2026-04-19

Hotfix for a silent protocol-level crash on every execution-layer tool
call. Plus a round of defensive hardening and logging improvements so
the next regression is visible instead of invisible.

### Fixed

- **structlog writes to stderr, not stdout.** `_configure_logging()`
  was pointing stdlib `logging` at stderr but leaving structlog on its
  default `PrintLogger(file=sys.stdout)`. Every `log.info("ozon_request",
  ...)` in `transport/base.py` emitted a JSON line onto the stdio
  channel that MCP uses for JSON-RPC framing, so the client disconnected
  with `Connection closed` on the first real API call. Static tools
  (no logging) kept working, which masked the bug. Now configured with
  `PrintLoggerFactory(file=sys.stderr)`.
- **UTF-8 stderr on Windows.** `sys.stderr.reconfigure(encoding="utf-8")`
  runs at startup so Cyrillic log fields and tracebacks don't crash the
  cp1252 codec. `JSONRenderer(ensure_ascii=False)` makes those logs
  readable rather than `\uXXXX`-escaped.

### Added

- **`@safe_tool` decorator** (`tools/_safety.py`) wraps every MCP
  tool handler in a `BaseException` guard. Unhandled exceptions become
  a structured `error_type="internal"` envelope plus a full traceback
  on ERROR — the process stays alive and the caller gets a
  typed response. Applied to `ozon_call_method`, `ozon_fetch_all`,
  `ozon_get_subscription_status`, `ozon_list_methods_for_subscription`.
- **Transport catch-all.** `BaseClient.request()` now converts any
  non-`httpx.HTTPError` exception (SSLError, ProxyError, mid-request
  cancel, ...) into an `OzonError` with `unexpected transport error:`
  prefix. `_auth_headers()` and `_rate_limits.for_call()` were moved
  inside the try-block — previously a broken OAuth refresh or rate
  config could raise before the guard kicked in.
- **Request/response DEBUG logs** in `transport/base.py` — request
  body and response body truncated to 1 KB, `duration_ms` on every
  response, structured event names (`ozon_request`, `ozon_request_body`,
  `ozon_response`, `ozon_response_body`).
- **Optional rotating file log.** Setting `OZON_LOG_FILE=/path/to/log`
  adds a `RotatingFileHandler` (5 MB × 3 backups) parallel to stderr.
  Useful because MCP client stderr is often not surfaced to the user.
- **Asyncio task exception handler** — unawaited task crashes are now
  logged via structlog (`asyncio_task_crashed`) instead of printing to
  stderr with no context.
- **`ozon-mcp --diagnose`** CLI flag. Runs a single `/v1/seller/info`
  call against the Ozon API and either prints `OK subscription=...` or
  a full traceback. Skips the MCP stdio loop entirely — the supported
  way to verify credentials without a client.

## [0.6.0] — 2026-04-17

Six-phase release focused on production-grade reliability and on
preparing the project for standalone GitHub publication. **274 tests,
ruff and mypy --strict clean, coverage 83 %.**

### Added

- **Rate-limit management** — `_execute_with_retry()` in
  `tools/execution.py` retries 429/5xx with bounded exponential
  back-off (cap `MAX_BACKOFF_SECONDS = 60`), honours `Retry-After`
  for both delta-seconds and RFC 7231 HTTP-date.
- **Slow-endpoint queue** — per-process `asyncio.Semaphore` plus
  enforced inter-call delay for endpoints with sub-1-RPS limits
  (e.g. `/v1/analytics/turnover/stocks`, confirmed live at 1 req/min).
- **Auto-pagination** — `ozon_fetch_all` MCP tool walks all 4
  pagination patterns Ozon uses (`offset_limit`, `cursor`,
  `last_id`, `page_number`) for the 38 paginated endpoints listed
  in the new `pagination_patterns.yaml`.
- **Subscription gate** — `tools/execution.py` pre-rejects calls
  for cabinets below the required tier; saves API quota on calls
  that would 403 anyway.
- **5 new analytical workflows**: `oos_risk_analysis`,
  `cabinet_health_check`, `content_audit`, `pricing_analysis`,
  `warehouse_stock_distribution` — each with `interpret`,
  `when_to_use`, and `common_mistakes` to make the agent's job
  unambiguous.
- **Business context** for 6 hot-path methods in `quirks.yaml`
  (`AnalyticsAPI_StocksTurnover`, `RatingAPI_RatingSummaryV1`,
  `ProductAPI_GetProductRatingBySku`,
  `ProductAPI_GetProductInfoPrices`,
  `AnalyticsAPI_AnalyticsStocks`, `PostingAPI_GetFboPostingList`).
- **Curated examples** for the 7 most-used methods in
  `examples.yaml` — all with `response_excerpt`.
- **Safety warnings** for all 38 destructive + 5 high-impact write
  methods (43 entries auto-generated into `quirks.yaml`).
- **`descriptions_overrides.yaml`** — curated descriptions for 10
  hot-path methods where Ozon shipped empty `description`. Applied
  before the BM25 search index is built.
- **Pydantic response models** — `schema/responses.py` with 26
  models for the seven hot-path endpoints, used for typed test
  assertions (production parsing untouched).
- **Anonymized fixture set** — `tests/fixtures/responses/` with
  realistic JSON for product list / info / prices / turnover /
  seller info / rating summary / warehouse list.
- **Knowledge integrity tests** — `tests/unit/test_knowledge_integrity.py`
  guards against typos in operation_ids, duplicate entries,
  invalid tiers, missing examples, real production IDs in
  fixtures.
- **Coverage reporting** — `pytest-cov` in dev deps, `[tool.coverage.*]`
  config, fail-under threshold 70 %.
- **GitHub Actions CI** — `.github/workflows/ci.yml` with matrix
  Python 3.12 / 3.13, ruff + mypy + pytest with coverage upload,
  swagger-drift checker that warns when bundled specs are older
  than 14 days.
- **Issue + PR templates** — `.github/ISSUE_TEMPLATE/{bug_report,
  method_request}.yml`, `.github/PULL_REQUEST_TEMPLATE.md`.
- **Standalone-publication setup** — expanded `.gitignore`, README
  rewrite covering 6 MCP clients (Claude Desktop, Claude Code,
  Cursor, Windsurf, Cline, Continue).

### Changed

- All MCP error responses now use the unified `OzonError` envelope
  (`schema/errors.py`). Backwards-compat top-level fields (`error`,
  `safety`, `available`, `valid_tiers`, `candidates`) preserved so
  existing callers still work.
- `Workflow` model gained `category`, `interpret`, `when_to_use`,
  `common_mistakes`, `rate_limit_note`, `subscription_note`.
- `Quirk` model gained `business_context`, `when_to_use`,
  `common_mistakes`, `safety_warning`.
- `subscription_overrides.yaml` expanded from 6 to 31 curated
  entries.
- `rate_limits.yaml` — `source` field now distinguishes
  `empirical` (confirmed via `ozon_sync_log`) from `docs`/`guess`.
- `state.cabinet_tier` cache gained a 1-hour TTL plus an
  `cabinet_tier_age_seconds()` helper. Errors are no longer cached.
- `ozon_get_subscription_status` now returns the same envelope as
  `ozon_call_method` (was using the legacy
  `errors.OzonError.to_dict()` shape — agents could mis-classify).

### Fixed

- **Pagination infinite-loop guard** — paginator now detects when
  the upstream returns the same `cursor` / `last_id` /
  `next_page_token` twice in a row and breaks the loop.
- **Pagination cursor extraction from nested responses** — when
  Ozon nests items under `response.result.items`, the cursor
  field also lives under `response.result.cursor`. Previously
  the paginator would fall back to taking an int id from the last
  item and send it back as a string-typed cursor → 400 schema
  validation. Now `_extract_field()` walks the same nesting as
  `_extract_items()`.
- **`Retry-After` HTTP-date parsing** — RFC 7231 §7.1.3 allows
  either delta-seconds or an HTTP-date. The transport now parses
  both via `email.utils.parsedate_to_datetime`, clamps negative
  deltas to 0, returns `None` on garbage.
- **Inconsistent error envelopes** — 7 read-only knowledge tools
  (`ozon_get_examples`, `ozon_get_rate_limits`,
  `ozon_get_swagger_meta`, `ozon_get_workflow`,
  `ozon_get_related_methods`, `ozon_list_methods_for_subscription`,
  `ozon_describe_method` ambiguous-path branch) all now return the
  same envelope as `ozon_call_method`.
- **`max_items` validation in `ozon_fetch_all`** — was unbounded;
  now enforces `1 ≤ max_items ≤ MAX_FETCH_ALL_ITEMS (100 000)`.
- **`quirks.yaml` typo** — `ProductAPI_GetProductInfoListV3` →
  `ProductAPI_GetProductInfoList` (V3 suffix never existed in the
  swagger).
- **`examples.yaml` duplicates** — removed two copy-paste
  duplicates (`AnalyticsAPI_AnalyticsGetData` "Daily dynamics" and
  `ProductAPI_GetProductInfoPrices` "All products with prices").
- **`reference.py` mypy `no-any-return`** — explicit
  `dict[str, Any]` annotation on `json.loads` result.

### Removed

- Monorepo coupling — `pyproject.toml` `[project.urls]` and
  `authors` no longer reference the in-tree umbrella project.

## [0.5.0] — 2026-04-12

### Added — 3-phase quality push (safety, search, knowledge)

Major release focused on agent safety, search quality, and curated knowledge depth. **130 tests, ruff and mypy --strict clean.** Triggered by an audit-script incident on 2026-04-12 where path-token heuristics let through Activate/Deactivate calls on real campaigns; this release fixes the underlying architectural weakness (safety as script-level concern → safety as catalog fact).

#### Phase 1 — Architectural safety + search overhaul (offline)

- **Method safety classifier** in [extractor.py](src/ozon_mcp/schema/extractor.py). Every method gets a `safety: "read" | "write" | "destructive"` field. Classifier examines last path segment, then operation_id CamelCase tokens, then HTTP method, with **default-to-write** policy. Distribution on Ozon's current spec: **219 read / 211 write / 38 destructive**. All known incident-causing methods now correctly classified (`ActivateCampaign`, `DeactivateCampaign`, `DeleteProducts`, `SubmitRequest`, all `all_sku_promo/*` toggles, `Carrots4` enable/disable).
- **Hard guardrail in `ozon_call_method`**:
  - `safety="read"` — no flag needed
  - `safety="write"` — requires `confirm_write=True`
  - `safety="destructive"` — requires BOTH `confirm_write=True` AND `i_understand_this_modifies_data=True`
  - Enforced server-side before any side-effecting work, returns structured refusal with safety_reason
- **Search quality overhaul** in [search.py](src/ozon_mcp/schema/search.py):
  - BM25 field boosting via document repetition (summary x4, path/op_id x3, section/tag x2, description x1)
  - CamelCase tokenizer for op_ids and paths so `FinanceTransactionListV3` → `[finance, transaction, list, v3]`
  - BM25 `b=0.3` reduces length normalization so canonical-but-longer methods don't lose to shorter siblings
  - Multiplicative ranking adjustments: deprecated x0.3, exact summary match x8, summary substring match x(1+4×ratio), summary token superset x2, op_id token superset x(1+6×precision), op_id literal substring x2.5, path query x4, read-method x1.05
  - Query tokenizer combines plain stemming (for natural language) with CamelCase splitting (for op_id queries)
  - **Golden test set: precision@1 (strict) 14/14 = 100%, precision@1 (any) 9/9 = 100%, recall@N 12/12 = 100%**
- **Enum enrichment from descriptions** ([extractor.py](src/ozon_mcp/schema/extractor.py)):
  - Walker scans string-typed and array-of-string properties
  - When property has empty/missing `enum` and description contains 3+ backtick-wrapped values, extracts them into a proper `enum` field
  - **124 fields auto-enriched** on Ozon's current spec, including the AnalyticsGetData `dimension`/`metrics`/`filters[].op`/`sort[].order` cases that were `enum: null` in source swagger
  - Marked with `x-enum-source: description` for traceability
- **`safety` and `subscription` fields exposed in `ozon_describe_method`**, `safety` filter added to `ozon_search_methods`

#### Phase 2 — Live audit over safety=read methods only (no incidents)

Audit script iterated **219 safety=read methods** and made 71 successful real calls against the PREMIUM_PLUS test account. **Zero safety violations** — the architectural guardrail held perfectly.

Key findings translated to curated content in Phase 3:

- **10 new response data inconsistencies** discovered (Ozon returns null in fields declared non-nullable, or returns lowercase enum values where swagger says uppercase, or returns `[]` where swagger says object/string):
  - `ReportAPI_ReportList.report_type` lowercase vs uppercase enum
  - `GetLimitsList.objectType` `BRAND_SHELF` not in `[SKU, SEARCH_PROMO]` enum
  - `ListCampaigns.placement` returns `[]` instead of string
  - `UtilizationInfo.utilization_settings.utilization_price_defects` null
  - `RFBSReturnsAPI_ReturnsRfbsListV2.returns` is `[]` when empty
  - Plus all previously known cases verified again
- **8 PERMISSION_DENIED errors** on FBP and ReviewAPI methods → quirks added documenting feature-gated access independent of subscription tier
- **27 ValidationError cases** confirming Ozon runtime is stricter than swagger declares (`filter` required even when not marked, etc.)
- **Section latency profile**: most read methods 60-150ms p50 warm, first call 1300+ms (TLS + connection pool warmup)

#### Phase 3 — Curated content sprint

- **8 workflows total** (was 4): added `sync_analytics_daily`, `sync_advertising_campaigns`, `sync_warehouse_stocks`, `sync_returns_rfbs`. All verified live in Phase 2.
- **37 quirks total** (was 22): added 8 new entries from Phase 2 findings including the data inconsistencies, the FBP feature gating, and the cross-cutting "Ozon runtime stricter than swagger" note.
- **14 error catalog entries** (was 8): added `OBSOLETE_METHOD`, `FILTER_REQUIRED`, `PERMISSION_DENIED_FBP`, `PERMISSION_DENIED_REVIEW`, `TOO_LONG_PERIOD`, `LIMIT_OUT_OF_RANGE` with verbatim Ozon error messages.
- **20 examples total** (was 10): added examples for `SellerInfo`, `AnalyticsGetData` (Premium and non-Premium variants), `WarehouseListV2`, `ProductInfoWarehouseStocks`, `ListCampaigns`, `GetLimitsList`, `ListReports`, `RfbsReturnsListV2`, `returnsList`.
- **Rate limits** still `source: guess` because Phase 2 didn't trigger any 429s (low burst). Added measured latency notes per section.

### Test count

| | v0.4.0 | v0.5.0 |
|---|---|---|
| Total tests | 80 | 130 |
| Safety classifier tests | 0 | 19 |
| Execution guardrail tests | 4 | 8 |
| Search quality tests | 5 | 12 |
| Enum enrichment tests | 0 | 10 |
| Deprecation tests | 8 | 8 |

### Verified-live operation_ids (callable through ozon_call_method)

71 read methods successfully called against the live PREMIUM_PLUS account during Phase 2. All 71 returned 200 with valid responses; 10 had data shape inconsistencies vs swagger that are now documented as quirks.

## [0.4.0] — 2026-04-11

### Added — Subscription tier awareness + security audit + comprehensive live audit (8 sections)

### Comprehensive live audit findings (2026-04-11)

A self-audit script ran 8 categories against the real PREMIUM_PLUS test account and surfaced 5 issues, all now fixed:

#### Critical fixes

1. **Extractor schema sanitizer** ([extractor.py](src/ozon_mcp/schema/extractor.py)): Ozon's swagger contains invalid JSON Schema fragments (`enum: null`, `description: null`, `type: 'int'/'bool'/'timestamp'/'array of strings'`, `required: true|false` at property level, regex placeholders like `'+7(XXX)XXX-XX-XX'` in `pattern` field). These caused `jsonschema.SchemaError` before any data validation, breaking `ozon_call_method` for endpoints like `AnalyticsAPI_AnalyticsGetData`. The new `sanitize_schema()` walker fixes all known patterns:
   - Drops null metadata keys (description, title, format, enum, items, properties, etc.)
   - Coerces `int → integer`, `bool → boolean`, `timestamp → string`
   - Drops informal types like `'array of strings'` (no recovery possible)
   - Removes `required: true|false` swagger 2.0 carry-overs
   - Drops non-standard `format` values
   - Drops un-compilable `pattern` regexes
   - **All 468 method schemas now pass `Draft202012Validator.check_schema()`** (regression test in `test_extractor_sanitize.py::test_extracted_schemas_pass_metaschema_check`)

2. **httpx exception wrapping** ([transport/base.py](src/ozon_mcp/transport/base.py)): `httpx.ConnectError`, `httpx.TimeoutException`, and other transport-level exceptions previously bubbled up unwrapped, crashing the audit script under burst load and leaking raw httpx types to MCP callers. Now wrapped in `OzonServerError` (retryable, so tenacity will back off and retry) and `OzonError` (catch-all). Agents always get a typed exception, never a raw httpx one.

3. **Explicit httpx connection pool limits**: `max_connections=50, max_keepalive_connections=20, keepalive_expiry=30s`. Together with the exception wrapping above, the audit's 20-parallel test now succeeds with 70 effective RPS, p99 = 278 ms, no failures (previous run crashed).

4. **Graceful degradation in `ozon_call_method`** ([tools/execution.py](src/ozon_mcp/tools/execution.py)): if the extracted schema is somehow still broken after sanitization, `_validate` catches `jsonschema.SchemaError`, skips client-side validation, and lets Ozon validate server-side. Better to send the request than block the agent on a tooling defect.

#### Curated quirks added from real responses

- `ProductAPI_GetProductInfoListV3`: non-existent `product_id` returns 200 with empty `items`, not 404 (Ozon convention — confirmed live)
- `SellerAPI_SellerInfo`: `ratings[N].past_value` can be `null` despite swagger declaring it `object` (Ozon data inconsistency, confirmed live)
- `AnalyticsAPI_AnalyticsGetData`: dimension/metrics fields are `array<string>` without enum constraint in swagger — agent must use values from description (now noted in quirk)
- `FinanceAPI_FinanceTransactionListV3`: 1-month period limit confirmed live with exact error message
- `PostingAPI_GetFboPostingList`: limit > 1000 returns precise error message — added to quirks for agent reference

#### Audit metrics (verified live)

| Section | Result |
|---|---|
| **A. Cold start** | catalog 33ms, search index 198ms, knowledge 12ms, total ~250ms |
| **A. Warm meta-tools** | catalog lookup 100x = 0ms, search 100x = 11ms (~0.1ms/query), list_sections 100x = 1ms |
| **B. Schema correctness** | 5/5 methods extracted-schemas now valid; 2/5 responses have Ozon data inconsistencies (documented as quirks) |
| **C. Pagination** | products via cursor (3 pages, 70-85ms each), FBO via offset (3 pages, 90-100ms each), both walk correctly |
| **D. Error paths** | 4/4 deliberate errors return correct typed exceptions with helpful Ozon messages |
| **E. Concurrency (20 parallel)** | 20/20 success, wall clock 284ms, **70 effective RPS**, p50 263ms, p99 278ms, no failures |
| **F. Subscription** | real account = PREMIUM_PLUS, 17 catalog methods mention this tier (matches auto-extraction), 10 methods need strictly higher tier |
| **G. Search quality** | 4/6 expected matches on top-1, 2/6 close-misses (BM25 tuning is a future polish item, not blocking) |
| **H. Performance API** | first call (with OAuth fetch) 551ms, cached-token call 138ms, 363 campaigns in 266 KB response |

#### Known limitations (not bugs in ozon-mcp)

- **Ozon returns null in fields that swagger declares non-null**: `ratings[].past_value`, `result[].financial_data` etc. can be `null` even when schema says they're objects. This is Ozon's data ↔ schema inconsistency; we surface it through quirks but cannot fix at the schema layer. Consumers parsing responses should treat these as nullable.
- **First request can be slow** (~2 seconds observed vs ~80ms steady-state). Cause: TLS handshake + DNS warmup. Subsequent requests on the same `httpx.AsyncClient` are fast due to connection pool keep-alive.

### Prior to live audit — Subscription tier awareness

### Live smoke test (verified 2026-04-11)

8 read-only calls executed against a real PREMIUM_PLUS Ozon account, all 200:

| # | Endpoint | Result |
|---|---|---|
| 1 | `POST /v1/seller/info` | subscription `{is_premium: true, type: PREMIUM_PLUS}` |
| 2 | `POST /v3/product/list` (limit=5) | 5 products returned |
| 3 | `POST /v3/product/info/list` | full details, ~21 KB |
| 4 | `POST /v2/posting/fbo/list` (last 24h) | result block returned |
| 5 | `POST /v3/finance/transaction/list` (last 24h) | result block returned |
| 6 | `POST /v1/analytics/data` (7d, day, revenue+ordered_units) | works on PREMIUM_PLUS |
| 7 | `GET /api/client/campaign` | works, **270+ KB response without pageSize → quirk added** |
| 8 | `GET /api/client/statistics/list` | empty list (account has no API-generated reports yet) |

OAuth2 token flow for Performance API verified end-to-end (token fetched on first call, cached on second).

### Curated content updated based on live results

- **`workflows.yaml`**: `sync_orders_fbs` → **`sync_orders_fbo`**, with verified `PostingAPI_GetFboPostingList` and `PostingAPI_GetFboPosting` operation_ids. `review_status: verified` (was draft).
- **`quirks.yaml`**: 5 new entries — `PostingAPI_GetFboPostingList` (filter requirements + offset cap), `ListCampaigns` (response size warning), `ListReports` (only UI-generated reports), `Premium-методы` (PREMIUM_PLUS confirmed).

#### Subscription tier feature
- Auto-extracted `subscription_tiers_mentioned` and `subscription_min_tier` for every method by scanning op + field descriptions for `Premium`, `Premium Lite`, `Premium Plus`, `Premium Pro` mentions. ~40 methods on the current spec carry tier hints.
- New tool **`ozon_list_methods_for_subscription(tier)`** — offline lookup of methods that mention a specific tier. Lets agents answer "what unlocks with Premium Plus?" without any API call.
- New tool **`ozon_get_subscription_status()`** — calls `/v1/seller/info`, returns the current account's `subscription_type` and `is_premium`, and lists methods that mention this exact tier. Cached per process; pass `refresh=True` to bypass. Available only with seller credentials.
- `ozon_describe_method` now includes a `subscription` block with the tiers mentioned, the min-tier hint, and a disclaimer about hard vs soft requirements.

#### Security & robustness audit (no behaviour changes for callers)
- **SecretStr for credentials**: `Config` wraps `client_id`, `api_key`, `performance_client_id`, `performance_client_secret` in `pydantic.SecretStr` so they cannot leak via `repr()`, `print()`, or accidental log dumps. Access via the new `seller_client_id()`, `seller_api_key()`, `perf_client_id()`, `perf_client_secret()` methods.
- **Error message extraction is no longer crash-prone**: `_raise_for_status` now safely handles error bodies that are lists, strings, or empty (previously would `AttributeError` on a list payload due to operator-precedence in the message extraction expression).
- **OAuth token leaks closed**: `PerformanceTokenManager` no longer includes `response.text` in error messages — only the HTTP status code — so an Ozon error response that echoes the request body cannot accidentally leak the client_secret.
- **Rate limit defaults from YAML**: `RateLimitRegistry` now reads `(api, section=null)` entries from `rate_limits.yaml` as global per-API defaults instead of using a hard-coded 1000/min that ignored config.
- **Lifespan-managed client shutdown**: server uses FastMCP's `lifespan` context manager to `aclose()` Seller and Performance clients on shutdown, eliminating httpx unclosed-client warnings.
- **Cleaner retry path**: `BaseClient.request` no longer has dead `except RetryError` / "unreachable" branches. With `tenacity` `reraise=True` the original `OzonRateLimitError` / `OzonServerError` propagates after exhaustion instead of being wrapped in a generic `OzonError`.
- **Graph max_hops clamp**: `MethodGraph.related()` clamps `max_hops` to `[1, 3]` to prevent an agent from accidentally requesting a graph traversal that walks the entire 468-method index.
- **Defensive response shape**: `BaseClient.request` returns dict responses transparently and wraps non-dict JSON (lists, scalars) in `{"data": ...}` so callers can rely on a stable type.

### Added — Repository hygiene
- `SECURITY.md` — threat model, supported versions, reporting process, operator best practices
- `CONTRIBUTING.md` — dev setup, how to add a workflow / quirk / rate limit, PR checklist

### Changed
- pytest `testpaths` now explicitly excludes `tests/live` from default discovery so live tests never run unless invoked with `pytest tests/live -m live`
- 11 additional tests (8 subscription + 3 e2e) bringing total to **71 tests, all green in ~7s**

### Tools registered
- 11 tools when no credentials are configured (added `ozon_list_methods_for_subscription`)
- 13 tools with full credentials (additionally `ozon_get_subscription_status` + `ozon_call_method`)

## [0.3.0] — 2026-04-11

### Added — M3: Execution layer

- Production-grade async transport (`ozon_mcp.transport`):
  - `SellerClient` — Client-Id + Api-Key header auth
  - `PerformanceClient` — OAuth2 Bearer auth via token manager
  - `PerformanceTokenManager` — concurrent-safe client_credentials flow with cache and refresh-before-expiry
  - `BaseClient` — shared httpx async client with retry (tenacity), per-method/per-section rate limiting (aiolimiter), structured logging
  - `RateLimitRegistry` — driven by `knowledge/rate_limits.yaml`
- Typed exception hierarchy in `ozon_mcp.errors`:
  - `OzonAuthError`, `OzonForbiddenError`, `OzonValidationError`, `OzonNotFoundError`, `OzonConflictError`, `OzonRateLimitError`, `OzonServerError`, `OzonClientValidationError`
- New MCP tool: **`ozon_call_method`**
  - Validates `params` against the method's resolved JSON Schema (jsonschema Draft 2020-12) before sending
  - Routes to Seller or Performance transport based on `method.api`
  - Returns typed errors as structured payloads agents can react to
  - Registered conditionally — only when matching credentials are present in env
- Live test stubs in `tests/live/test_real_api.py` (skipped by default; require real credentials)
- 17 new mocked tests covering transport status mapping, retry on 429/5xx, OAuth caching/refresh, and execution validation

### Changed

- Server reports execution mode at startup (`enabled_for: ["seller", "performance"]` or `none`)
- Server `instructions` mention execution availability
- pytest config now explicitly excludes `tests/live` from default test discovery — they only run via `pytest tests/live -m live`
- Integration test fixture clears `OZON_*` env vars so e2e tests never accidentally instantiate real clients

### Transport behaviour

- Retries: 3 attempts on 429 / 500 / 502 / 503 / 504, exponential backoff with jitter (initial 1s, max 20s)
- 4xx (except 429) raises immediately, no retry
- Rate limiting: per-section limiter from `knowledge/rate_limits.yaml`, falls back to 1000 req/min global
- All requests log structured JSON to stderr (api, method, path, operation_id)

## [0.2.0] — 2026-04-11

### Added — M2: Knowledge layer + method graph

- Method relationship graph (`ozon_mcp.schema.graph`):
  - Auto-extracts cross-references from markdown links in operation/field descriptions
  - Augments edges from curated workflow chains
  - 238 edges across 468 methods on Ozon's current spec
- Curated knowledge base (`ozon_mcp.knowledge`) loaded from YAML at start:
  - **3 workflows** — `sync_orders_fbs`, `sync_products_catalog`, `sync_finance_transactions` (review_status: draft)
  - **8 rate limits** — section-level defaults, all marked `source: guess` until verified
  - **8 error catalog entries** — common HTTP codes with cause/fix
  - **12 quirks** — extracted from method descriptions and curated additions
  - **10 hand-crafted request examples** for the most common methods
- 6 new MCP tools:
  - `ozon_get_related_methods` — auto + workflow-derived neighbours
  - `ozon_list_workflows` — overview of curated workflows
  - `ozon_get_workflow` — full step-by-step plan with DB schema and gotchas
  - `ozon_get_rate_limits` — per-method, per-section, or all
  - `ozon_get_error_catalog` — by code or by operation_id
  - `ozon_get_examples` — hand-crafted request payloads
- `ozon_describe_method` is now rich: includes `rate_limit`, `quirks`, `examples`, `specific_errors`, `related_methods` inline
- Russian + English stemming via `snowballstemmer` for BM25 (handles morphological forms)

### Changed

- Server `instructions` now mentions workflows and quirks counts on startup
- 22 additional tests (4 graph + 7 knowledge + 11 e2e)

### Curated content needs review

The knowledge YAML files are first-pass drafts. Specifically these need verification:
- All `rate_limits.yaml` entries are `source: guess` — measure against real API
- `workflows.yaml` entries are `review_status: draft` — battle-test in production
- `quirks.yaml` covers ~12 methods, swagger has 458 — long tail to discover
- `examples.yaml` covers 10 methods — expand as you encounter new ones

## [0.1.0] — 2026-04-11

### Added — M1: Schema layer + discovery

- New OpenAPI → JSON Schema engine in `ozon_mcp.schema`:
  - Recursive `$ref` resolver with cycle detection at all OpenAPI levels (schemas, requestBodies, parameters, responses)
  - `Method` pydantic model with fully resolved request/response schemas
  - `Catalog` index by `operation_id`, by `(api, method, path)`, and by section
  - BM25 full-text search across summary/description/path/tag (Russian + English)
- 4 MCP meta-tools:
  - `ozon_list_sections` — section overview with method counts
  - `ozon_search_methods` — BM25 search with section/api filters
  - `ozon_describe_method` — full method spec with resolved JSON Schema
  - `ozon_get_section` — list methods inside a section
- 468 methods indexed (Seller API + Performance API), cold start under 50 ms
- Regression tests pinning every bug found in the legacy parser audit:
  - `requestBody` `$ref` resolution (broke 15/25 perf methods)
  - `oneOf`/`anyOf` no longer merged into impossible `required` unions
  - `enum`, `default`, `format` survive into output
  - Nested object expansion no longer truncated at depth 3
  - Array items via `$ref` get correct item type
- CI: ruff + mypy strict + pytest on Python 3.12 / 3.13

### Not yet

- Knowledge layer (workflows, rate limits, error catalog, quirks) — M2 / v0.2
- Execution layer (`ozon_call_method`) — M3 / v0.3
- Method relationship graph from markdown links — M2 / v0.2
- Daily swagger refresh automation — post-MVP
