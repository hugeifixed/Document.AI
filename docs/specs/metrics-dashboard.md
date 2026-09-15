# Metrics dashboard v1

Approved scope: operational trends using existing durable data, document executions rather than unique
files, token usage without money, scoped filters, and no page-throughput metric or new telemetry.
This spec supersedes the original draft's global filters and unsupported detailed stages.

## Experience

Add Metrics under Measure & share at /metrics, with shared browser title Metrics. Keep the existing
Dashboard for immediate work. Use the current working project/dataset and UTC dates (visible timezone).
Default range 30d including today; offer today, 7d, 30d, 90d and custom inclusive dates up to 90 days.
Use URL query parameters for metrics filters; working context remains the existing project/dataset state.
Show As of and manual Refresh; poll every60 seconds only while visible. Do not show old-filter data as current.

Four sections:
- Processing: completed jobs (currently succeeded or failed RunItems), median/P95 recorded final-attempt
  duration, daily job volume and duration, executions containing each recorded document type, failed jobs
  by broad recorded phase. Processing-only filters: document_type and status (succeeded/failed/all).
- Run reliability: success rate succeeded/(succeeded+partial+failed), failed run count, daily outcome
  breakdown including partial and cancelled separately. Date by finished_at; exclude unfinished runs.
- Review: current backlog fields/classifications and distinct documents, across all dates in workspace;
  period review decisions and field correction rate. Decisions = field accept/correct/reject/mark_absent
  and classification accept/reclassify, dated by ReviewAction.created. Field correction rate = correct /
  those four field decision actions. Repeated actions count, not unique targets or model accuracy.
- LLM usage: operator/superuser only, recorded responses, measured tokens, measurement coverage and daily
  token trend. Section filters: provider, deployment, stage. Include retry responses. Missing tokens are
  unknown, not fabricated zero; cached/reasoning counts are subsets. No money or provider-error-rate claim.

Processing date = RunItem.status_changed for currently succeeded/failed items. Count reruns separately;
internal retries update one item. Duration excludes queue delay and earlier attempts. Median = mean of
middle two for even samples; P95 = nearest rank ceil(.95*n). No data => null duration/rate.
Document type comes from ClassificationResult for same run+document, preferring nonempty reviewed_category.
One execution counts once per effective category; mixed types are non-additive. No classification =>
__unclassified__ / Not classified. Do not infer types from filenames or workflow configuration.
Phase buckets: preparation(normalization), layout(layout), workflow(workflow), persistence(persist),
worker_dispatch(known delivery/dispatch/interruption stages), unknown(anything else); no log parsing.
Use count0 for empty buckets. Existing overwritten/deleted execution/results data is not a historical ledger.

## API contract (all values inside the existing response data envelope)

GET /api/v1/metrics/ — existing DocAIPermission read access.
GET /api/v1/metrics/usage/ — requires OPERATOR, same as run usage API.
Shared query: project?, dataset?, range=today|7d|30d|90d|custom, start?, end?. Custom dates must be valid,
ordered, at most90 inclusive days, and not future. Both supplied scopes must agree; respect available
project/dataset and permission hooks. Invalid filter => existing400 validation envelope. Unknown scope404.
Main endpoint additionally accepts document_type? and status=succeeded|failed; usage endpoint additionally
accepts provider?, deployment?, stage?. Reject unrelated/unknown query filters rather than silently ignore.
Empty or absent optional filters mean all. Taxonomy/provider filters bound to actual scoped option values;
unknown valid-length values may yield empty data (never broaden silently).

meta = {start_date:YYYY-MM-DD,end_date:YYYY-MM-DD,timezone:"UTC",as_of:ISO8601,
        cache_ttl_seconds:60,applied_filters:object}
Main response:
{
  meta,
  processing:{completed_jobs:number,duration_sample_count:number,median_duration_ms:number|null,
    p95_duration_ms:number|null,
    daily:[{date,completed_jobs,succeeded,failed,duration_sample_count,median_duration_ms,p95_duration_ms}],
    by_document_type:[{key,label,executions}], failures_by_phase:[{key,label,count}],
    document_type_options:[{key,label}]},
  runs:{succeeded:number,failed:number,partial:number,cancelled:number,success_rate:number|null,
    daily:[{date,succeeded,failed,partial,cancelled}]},
  review:{backlog_fields:number,backlog_classifications:number,backlog_documents:number,
    decision_count:number,field_decision_count:number,field_correction_count:number,
    field_correction_rate:number|null,daily:[{date,field_decisions,classification_decisions}]}
}
Rates are percentages0..100. All daily arrays include every selected UTC date ascending. Bar arrays sort
count descending then stable key. Options ignore their section-specific filters but respect date/workspace.
Processing filters do not affect runs/review. Backlog ignores date, all other sections honor shared dates.
Usage response:
{meta,calls:number,measured_calls:number,total_tokens:number|null,
 daily:[{date,calls,measured_calls,total_tokens}],
 filter_options:{providers:string[],deployments:string[],stages:string[]}}
Zero calls => total_tokens0. Calls but no measured totals => null. Partial measurement sums known totals and
reports measured_calls; clearly label measured usage. No PII, document IDs/names, prompts or reviewer identities.

## Architecture and UI

Backend aggregation in one metrics service with bounded independent queries; no multiplying joins, N+1,
loading all duration rows into Python, JSON/NCLOB grouping, DB-specific percentile SQL or new task/model.
Use database Window ranks to return percentile boundary rows, aggregate overall independently from daily.
Use django.core.cache default backend; DOCAI_CACHE_TTLS metrics=60. Key version+canonical filters+workspace+
caller+roles. Authorize before cache hits. Redis is config-only; LocMem consistency is TTL bounded.
Use DRF serializer request/response contracts and OpenAPI docs; private/no-store HTTP responses.

Frontend feature under features/metrics, named request functions + query-key factories, tests colocated.
Only move existing shared client and necessary UI primitives into common when target boundary needs it;
no second client, wrappers/framework, unrelated component decomposition or disabling boundary lint.
Workspace/session can be composed into feature through app wiring. Read frontend ARCHITECTURE and DESIGN.
Use modular @visx/shape,scale,axis,responsive,tooltip4.0.0 (React19 compatible) and eligible lock dependencies
released more than7 days ago. Chart frame + line + bar(with stack support), local to metrics; no donut.
Use daisyUI stats, theme tokens and existing typography. Keyboard/touch data access, SVG labels, visible focus,
legends/pattern differences, expandable data tables, reduced motion, stable skeletons, empty/error states.
Avoid huge overviews: two-column desktop charts, single-column small screens, clear scoped filter captions.

## Tests and delivery

Backend: date boundaries, null/zero values, exact percentiles, retries/reruns, mixed and reviewed types,
partial/cancelled runs, review definitions, role and cache isolation/expiry, invalid filters, constant query
count as rows grow. SQLite executed; Oracle-compatible query construction, live Oracle limitation documented.
Frontend: URL/history restoration, scope/filter isolation, stale-response prevention, all states and roles.
Browser: both themes and supported phone/tablet/desktop layouts, keyboard/focus, tooltips/tables/overflow.
Run scripts/verify.py --browser, independent Standards + Spec reviews, fix findings, ready one PR.
No pages/cost/accuracy/historical backlog metrics, new auth/membership, telemetry or historic repair.
Preserve the configured Git identity; exclude uv.lock. Do not change the dirty workflow-example checkout.

## Task graph

M0 (root): spec/contract, isolated PR branch and draft PR.
M1 (backend implementer; depends M0): aggregations, API/RBAC/cache, tests; owns backend only.
M2 (frontend implementer; depends M0): shared prerequisite moves, feature/charts, dependencies, unit tests;
owns frontend excluding e2e and documentation.
M3 (root; depends M0 for authoring, M1+M2 for verification): browser scenarios, documentation, full validation.
Merger integrates each implementer commit into PR worktree; no editing root's dirty checkout.
M4 (two independent review agents; depends M1+M2+M3): Standards and Spec review against fixed base.
M5 (single fix implementer, own worktree; depends M4): all review fixes; merger integrates; verify changed scope.
M6 (root; depends M5): push, ready PR, clean implementer worktrees.

Fixed base: ab68237cbfa30e9e74267fd3a5699dc79f27b1cb, branch feat/shared-link-page-titles (PR29).
Metrics PR is stacked on that branch; workflow examples remain entirely separate and uncommitted.
