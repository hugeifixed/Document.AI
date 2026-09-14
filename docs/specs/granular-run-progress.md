# Granular run progress

Make active processing understandable through measured milestones, elapsed time, and cautious batch estimates.
The application retains its current polling, role-based access, worker pools, and optional broker configuration.

## Task graph

| Ticket | Work | Blocked by |
| --- | --- | --- |
| P1 | Backend snapshots, instrumentation, API and tests | — |
| P2 | Frontend progress, filtering and lifecycle tests | Agreed API contract below |
| P3 | Browser verification, documentation and integration | P1, P2 |
| P4 | Independent standards/spec review, fixes and final verification | P3 |

## Experience

Replace active run's four large stats + completion-only bar with one calm progress card directly below header. Counts: completed/total, succeeded, processing, queued, failed, skipped (overall bar counts terminal documents, never a guessed percentage of provider work). Counts are buttons filtering the items table, reset to page one, with an All control to clear the filter. Show up to five activity items, preferring running, then retry_wait, then queued, stable created/id order within each priority. View all links filter the table. Each preview has filename, accurate operation label, operation elapsed time, optional measured counters/group context and Processing details disclosure. Keep expansions keyed by item id; never steal focus or reorder due merely to progress timestamps.

Run items table immediately follows card, before versions/metrics/usage. Reuse shared DataTable, server pagination (50 rows default), search and status filtering, stable created/id default ordering. Preserve existing columns, scan details, document links, errors, operator-only token usage and lifecycle actions. Action/count logic must use unfiltered totals, not current page. Completion yields a compact summary and existing journey cue. Explicit cancellation and partial failure semantics remain.

Details show applicable phases Prepare scans (only if enabled), Read document, Analyze, Save results; current subactivity supplies granular meaning. No growing event timeline. Pages examined use normalization callbacks only. Never imply Azure OCR reports page completion. Unknown request progress gets elapsed time and waiting copy, not an invented percentage. Unbundle combines grouping/classification in its actual segmentation call; no invented independent classification call. Chunk counters scope to the actual group/segment and reset clearly when changing group.

Use tokens, Heroicons/daisyUI, native accessible disclosures, reduced motion, visible keyboard focus. Announce meaningful state changes only, not every elapsed-second tick. Verify both themes at 390x844,768x1024,1024x768,1440x900. Do not add animation loops or decorative dashboards.

## Shared public contract (backend + frontend)

RunItem adds `processing_progress: ProcessingProgress | null` and `progress_updated_at: ISO UTC string | null`. Model JSON default dict, serialized absent/empty as null. Existing lifecycle status/stage stays unchanged.

ProcessingProgress schema:
- `phase`: queued | preparing_scans | reading_document | analyzing | saving_results | complete
- `operation`: queued | preparing_scans | reading_document | waiting_for_ocr | reusing_layout | identifying_groups | classifying | extracting | checking_evidence | saving_results | retry_wait | complete | failed | cancelled
- `phase_started_at`: ISO UTC string
- `operation_started_at`: ISO UTC string
- `completed_phases`: bounded unique array of phase codes (no history)
- `counter`: null or {completed: integer>=0, total: integer>=0, unit: pages | chunks}; completed<=total
- `segment`: null or {current: integer>=1, total: integer>=1}; current<=total, display one-based
- `retry_at`: ISO UTC string|null (actual scheduled retry only)

Existing progress endpoint retains old fields and adds:
- `as_of`: server UTC now
- `last_milestone_at`: max progress_updated_at or null
- `activity_items`: up to five RunItemSerializer objects, prioritization above; do not include terminal items
- `estimated_finish_at`: UTC or null

RunItemViewSet supports stable `created` ordering with id tie-break and existing status/status__in/search filters. No new endpoints. OpenAPI + TypeScript updated. Counts/ETA are SQL aggregates on scalar fields; do not group/order/filter JSON or LOB columns. Activity-item bounded query is separate from aggregates. No prompts, text, new credential exposure; preserve RBAC/content boundaries. API reads never write milestones.

## Instrumentation and persistence

One small progress recorder outside adapters, validated by a Pydantic snapshot model. Inject lightweight optional callbacks through workflow context / adapter construction where needed, no ORM in adapters. Instrument claim, preparation page callbacks, layout reuse, OCR/text read start/completion, grouping/classification, chunk start and completion, evidence checking, persistence, actual provider/Celery retry schedule and terminal states. Keep local mock, pypdf/Excel/text, Azure and thread/sync/Celery routes working.

Stage/operation transitions immediate, repeated same-operation page/chunk counts throttled to at most once/3seconds, always flush phase/terminal completion. UI telemetry failures must never abort task or poison a business transaction. Guard updates by item id + claim attempt + worker task id where applicable and expected lifecycle state; stale deliveries cannot overwrite new/terminal progress. New claims reset snapshot. Counts after invalid-output handling mean chunks processed, not accepted fields. Capture failures/cancellation/scheduling failure without pretending completion.

No heartbeat thread, log parser, extra task/queue, websocket/event stream, or Redis dependency. Does not change worker pool/concurrency, provider timeout or cancellation mechanics. Progress snapshots only, no history repair.

## Timing/freshness

Poll relevant run/progress/items every 3 sec while queued/running/cancelling, focus-refetch on return; final refresh then stop. Keep prior snapshots through refresh errors. Server as_of + client receipt monotonic elapsed gives timers without clock-skew confusion. Browser polling is not proof worker is alive.

Always show elapsed; estimate only when >=3 succeeded, at least one document remaining, no failures/skips, no item attempts>1 or retry_wait, no cancellation, active run. `latest_success_at` from Max(modified) over succeeded scalar rows, `elapsed_to_success = latest_success_at - run.started_at`, `predicted_finish = latest_success_at + (elapsed_to_success / succeeded) * remaining`. Freeze predicted timestamp between real completions. Retain estimated_seconds_remaining derived from it (null when no estimate; clamp expired to 0 for legacy clients). Frontend displays an approximate human duration; past timestamp => Taking longer than the estimate. No ETA for single/small runs incapable of accumulating 3 finished samples with work remaining. Larger runs before samples: Estimating after more documents finish. Suppress ETA during cancellation, retry/failure or stale client updates.

After 15 sec without successful active progress refresh, show Updates interrupted + manual Retry refresh, retain last-known data. After 120 sec without an item milestone, show quiet No new milestone for [duration] and operation. These are not stuck/dead/alive diagnoses. Queued with no claimed task says Waiting for a worker (busy or unavailable), not No workers or an invented queue position.

## Verification / rollout

Backend: five docs dispatch concurrently/sequentially; known vs unknown counters; segmentation chunk reset; cached layout; retry schedule and reset; failure/cancel; stale attempt writes; throttling and best effort; empty/legacy snapshots; bounded queries and authorization; ETA eligibility/formula; SQLite functional + Oracle SQL shape no JSON aggregates. No live network tests. Frontend: timer/refresh fake-clock cases, aggregate-vs-paged counts, filter/pagination, final refresh, disclosure preservation. Browser: progressing synthetic responses, errors/recovery, stage transitions/counters, terminal state, keyboard/disclosures, both themes/viewports/axe. All required lint/unit/build/backend tests; preserve coverage>=80.

Add migration (default empty progress, nullable timestamp); older runs show old coarse status safely. Document contract/design/operations; backend+workers need restart after deployment. Do not backfill historical data.
