# Metrics

Open **Measure & share → Metrics** to compare processing trends within the current project and dataset.
The Dashboard still answers “what needs attention now?” Metrics answers “how has processing behaved?”

Dates are UTC, inclusive, and limited to 90 days. The default is the last 30 days including today.
Date and section filters live in the URL, so Back, Forward, and refresh retain them. Project and dataset
use Working context. Shared links use the recipient's current Working context, not the sender's.
**As of** identifies the snapshot; visible pages refresh every minute. The server caches aggregates for
60 seconds, so Refresh may return the same snapshot until its cache expires.

## What the numbers mean

| Section | Definition | Important boundary |
| --- | --- | --- |
| Completed jobs | Run items currently succeeded or failed, dated by their status change | Running, queued, skipped, and cancelled items are excluded. Running the same document again counts as another job; internal retries do not. |
| Median / P95 duration | Recorded final-attempt processing time, in milliseconds | Excludes queue delay and earlier attempts. Median averages the middle pair for even samples; P95 is the nearest rank. Missing measurements are excluded, not zero. |
| Document types | Effective classification for the same document and run, including reviewer corrections | One job counts once per type. A mixed document can count under several types; bars must not be added to get total jobs. No classification means “Not classified.” |
| Failure phase | Broad phase recorded on the failed run item | Workflow includes classification/extraction failures; finer distinctions are unavailable. Upload rejection is not a processing failure. |
| Run success rate | Succeeded ÷ (succeeded + partial + failed), dated by run completion | Cancelled runs appear separately and are excluded from the denominator. Unfinished runs are excluded. |
| Review backlog | Fields and classifications currently needing review, plus distinct documents | Current workspace totals across **all dates**, regardless of period. |
| Review decisions | Field accept/correct/reject/absent and classification accept/reclassify actions in the period | Repeated actions count again. Notes and promotions to ground truth are not decisions. |
| Field correction rate | Correct actions ÷ field decision actions | Measures review activity, not extraction accuracy. Use Evaluations for accuracy against ground truth. |
| LLM usage | Recorded responses and known total-token measurements in the period | Operator access only. Includes retry responses; unmeasured responses remain unknown. Does not measure every attempted provider call or provider failure rate. |

Document type and job status affect **Processing only**. Provider, deployment, and stage affect **LLM
usage only**. Dates and workspace affect all period charts; the current review backlog ignores dates.
Cached and reasoning tokens are subsets of total usage and must not be added again. No cost estimates or
page-throughput claims are included. A chart's expandable data table provides its underlying values without
requiring a mouse or distinguishing series by color alone.

## Implementation and deployment

`GET /api/v1/metrics/` uses the existing DocAI read permission. `GET /api/v1/metrics/usage/` requires the
operator role (or superuser). Both use the normal response envelope and documented OpenAPI query contract.
No document contents, filenames, prompts, or reviewer identities are returned.

Aggregations use existing database records, with no scheduled job or new telemetry table. Django's default
cache stores responses under caller-, role-, workspace-, and filter-specific keys for
`DOCAI_CACHE_TTLS["metrics"]` seconds (default 60). Authorization runs before cache lookup. HTTP responses
are private and not browser-cacheable. Existing Redis cache configuration can replace LocMem without
application changes; separate LocMem processes can see different snapshots for up to the TTL.

Metrics are not a historical accounting ledger: retries can overwrite final attempt timings, and deleted
or reprocessed results can change previous totals. The database performs duration ranking and returns only
the percentile boundaries, rather than shipping every duration into Python. Automated database tests run
on SQLite; a live Oracle validation remains an institutional deployment gate. No live Azure calls are
needed to load this screen.
