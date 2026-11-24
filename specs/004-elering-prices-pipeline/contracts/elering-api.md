# Contract: Elering NPS Price API Integration

External HTTP interface consumed by `ingestion/elering_prices/client.py` and validated by
`ingestion/elering_prices/records.py`.

## Endpoint

```http
GET https://dashboard.elering.ee/api/nps/price?start=<ISO_UTC>&end=<ISO_UTC>
```

- Public endpoint, no authentication required.
- Base URL is configurable via `ELERING_PRICES_URL` (default
  `https://dashboard.elering.ee/api/nps/price`).

## Request Parameters

| Parameter | Format | Semantics |
|---|---|---|
| `start` | `YYYY-MM-DDTHH:MM:SSZ` (URL-encoded) | Inclusive UTC start of the requested chunk |
| `end` | `YYYY-MM-DDTHH:MM:SSZ` (URL-encoded) | Inclusive UTC end of the requested chunk |

**Half-open window mapping**:
To fetch every interval starting in half-open UTC window `[chunk_start, chunk_end)` without
overlapping the next chunk or next day:
- `start = chunk_start.strftime("%Y-%m-%dT%H:%M:%SZ")`
- `end = (chunk_end - timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")`

**Span limit & chunking**:
- Elering rejects requests spanning more than 1 year with HTTP `400`:
  `{"status":"BAD_REQUEST","messages":["Maximum period is 1 year"]}`.
- The job splits any window longer than `ELERING_CHUNK_DAYS` (default `31`, allowed `1..365`) into
  contiguous half-open chunks `[t, min(t + chunk_days, end_utc))`.

## Response Shape

```json
{
  "success": true,
  "data": {
    "ee": [
      {"timestamp": 1759266000, "price": 41.57},
      {"timestamp": 1759269600, "price": 98.95},
      {"timestamp": 1759270500, "price": 89.44}
    ],
    "fi": [...],
    "lv": [...],
    "lt": [...]
  }
}
```

- `timestamp`: integer Unix epoch seconds (UTC) marking interval start.
- `price`: JSON number (float or int) in EUR/MWh; negative and zero values are valid.
- Market resolution: 3600 s (60-min) before `2025-09-30T22:00:00Z` (`1759269600`); 900 s (15-min)
  from `2025-09-30T22:00:00Z` onward.

## Validation Rules (FR-008)

Every chunk response MUST satisfy all checks before any records are stored; any failure raises
`InvalidResponseError` (no internal retry):

1. Body is valid JSON and top-level value is a `dict`.
2. `response.get("success") is True` and `response.get("data")` is a non-empty `dict`.
3. For every configured zone (`zone.code.lower()`), `data[zone_key]` is a non-empty `list`.
4. Every element is a `dict` with:
   - `timestamp`: `int` (not `bool`), whose UTC datetime satisfies
     `chunk_start <= interval_start_utc < chunk_end`.
   - `price`: `int | float` (not `bool`), `math.isfinite(price)` is `True`.
5. No duplicate `(zone_key, timestamp)` appears within a chunk or across chunks in the run.
6. For each configured zone, `len(data[zone_key])` equals the exact expected interval count for
   `[chunk_start, chunk_end)` given that zone's `mtu_switch_utc`, `historical_mtu_minutes`, and
   `current_mtu_minutes`.

## Error & Retry Semantics (FR-009)

| Failure type | Handling |
|---|---|
| Connection error, timeout, `URLError`, `HTTPException` | Retry with exponential backoff (`retry_base * 2^(attempt-1)`) up to `max_attempts`; then raise `FetchError` |
| HTTP `429` or `5xx` | Retry with exponential backoff up to `max_attempts`; then raise `FetchError` |
| HTTP `4xx` (other than `429`) | Fail immediately with `InvalidResponseError` (include `messages` / `reason` if JSON) |
| Non-JSON response body | Fail immediately with `InvalidResponseError` |
| Incomplete / structurally invalid response | Fail immediately with `InvalidResponseError` naming the offending zone/reason |
