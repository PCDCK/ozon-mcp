# Anonymized Ozon API response fixtures

Synthetic JSON payloads matching the response shapes documented in
`seller_swagger.json`. Used by integration tests to verify how
ozon-mcp parses real-world Ozon responses without ever hitting the
network.

## Anonymization rules

- All `product_id` / `sku` use the prefix `9900xxxx` (no real merchant data).
- All `offer_id` use the prefix `TEST-SKU-`.
- All `warehouse_id` use the prefix `99100xxx`.
- Image URLs use `https://example.test/`.
- Company / cabinet names are clearly marked "Test".

## Provenance

The DB `ozon_sync_log.response_body` only contains error payloads
(403 ACCOUNT_BLOCKED, 429 rate-limit) for the test cabinets in
production at 2026-04-17. Successful responses were synthesized to
match the corresponding Ozon swagger schemas verbatim, then
anonymized.

## Files

| File                              | Endpoint                                |
|---                                |---                                      |
| product_list_response.json        | `/v3/product/list`                      |
| product_info_response.json        | `/v3/product/info/list`                 |
| prices_response.json              | `/v5/product/info/prices`               |
| turnover_response.json            | `/v1/analytics/turnover/stocks`         |
| seller_info_response.json         | `/v1/seller/info`                       |
| rating_summary_response.json      | `/v1/rating/summary`                    |
| warehouse_list_response.json      | `/v1/warehouse/list`                    |
