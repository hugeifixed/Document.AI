# Known limitations

- **Metrics are operational snapshots, not an accounting ledger.** They use existing mutable execution and
  result records, so retries, reprocessing, and deletion can change historical totals. Timing is final-attempt
  processing time, not end-to-end latency; page throughput and cost are deliberately excluded. LLM response
  records do not cover every attempted provider call. See [metric definitions](docs/metrics.md).

- **Live Azure calls are not part of the automated suite.** Document Intelligence and Azure OpenAI have been
  exercised manually, while repository tests use local or deterministic adapters. Run a credentialed smoke workflow
  in RND after changing an endpoint, API version, deployment, model, identity, or network policy. Current client pins
  are `azure-ai-documentintelligence==1.0.2` and `langchain-openai==1.6.0`.
- **Local layout adapter is not OCR.** `pypdf` reads text layers with coarse word boxes; scanned PDFs, images and
  DOCX require `azure_di`.
- **The mock LLM is a test double.** It answers from regex heuristics over the preserved text and field
  descriptions. It demonstrates the machinery and drives tests; it is not a proxy for model quality.
- **Semantic chunking has no embeddings** — it breaks at structural boundaries only.
- **SQLite is single-writer**: the thread runner degrades to one worker; use Oracle for parallelism.
- **The filesystem Celery broker is a one-host transition mode.** It has no broker HA, heartbeats, message TTL,
  or priority, and an abrupt worker or host loss can strand an in-flight message. Run
  `manage.py recover_stalled_runs` after an ungraceful failure. Use Redis or RabbitMQ before adding worker hosts
  or requiring automatic broker recovery. Native Windows Celery is also best-effort; use `threads`/`solo`, WSL2,
  or the built-in thread runner for development.
- **Trusted-team access boundary.** No SSO/OIDC integration or project membership is included. The frontend uses
  Django sessions, and deployed settings disable DRF Basic authentication unless `DOCAI_ENABLE_BASIC_AUTH=true` is
  explicitly enabled behind HTTPS. DocAI roles are global: any member can discover every project. Add Entra/OIDC,
  project membership, and queryset scoping before use across separate lines of business or need-to-know groups.
- **Frontend**: no offline/PWA behavior and no Lighthouse performance audit. The optional Playwright suite performs
  targeted axe-core scans, but those checks cover only its mocked browser workflows and are not a complete WCAG audit.
- **Raw model responses** are stored as artifacts with a retention value but no purge job.
- **Optional scan enhancement is experimental and off by default.** Synthetic scans and mocked Azure responses
  test transformations and contracts, not OCR gains. Validate `adaptive-v1` on a representative RND/QA corpus
  before rollout; blank skipping is separately opt-in. PDFium work is serialized in thread workers; use Linux
  prefork for parallel rendering. See `backend/IMAGE_NORMALIZATION.md`.
