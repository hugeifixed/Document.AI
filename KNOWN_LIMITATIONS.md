# Known limitations

* **Azure adapters are untested against live services.** `adapters/layout/azure_di.py` and
  `adapters/llm/azure_openai.py` follow the current SDK signatures (azure-ai-documentintelligence 1.0.2,
  langchain-openai 0.3.x) but were written without credentials. Expect small fixes on first contact
  (e.g. polygon unit handling for TIFF, `features` per model).
* **Local layout adapter is not OCR.** `pypdf` reads text layers with coarse word boxes; scanned PDFs, images and
  DOCX require `azure_di`.
* **The mock LLM is a test double.** It answers from regex heuristics over the preserved text and field
  descriptions. It demonstrates the machinery and drives tests; it is not a proxy for model quality.
* **Semantic chunking has no embeddings** — it breaks at structural boundaries only.
* **SQLite is single-writer**: the thread runner degrades to one worker; use Postgres/Oracle for parallelism.
* **The filesystem Celery broker is a one-host transition mode.** It has no broker HA, heartbeats, message TTL,
  or priority, and an abrupt worker or host loss can strand an in-flight message. Run
  `manage.py recover_stalled_runs` after an ungraceful failure. Use Redis or RabbitMQ before adding worker hosts
  or requiring automatic broker recovery. Native Windows Celery is also best-effort; use `threads`/`solo`, WSL2,
  or the built-in thread runner for development.
* **Session authentication.** No SSO/OIDC integration is included. The frontend uses Django sessions;
  production disables DRF Basic authentication unless `DOCAI_ENABLE_BASIC_AUTH=true` is explicitly set.
* **Per-project object permissions** are a hook, not enforced membership. The current role model assumes one
  trusted organizational boundary: any user in a DocAI role can list every project. Add project membership and
  queryset scoping before using this as a multi-tenant or need-to-know system.
* **Frontend**: no offline/PWA behavior; no automated axe/Lighthouse run was performed here.
* **Raw model responses** are stored as artifacts with a retention value but no purge job.
* **Rasterization / deskew / blank-page removal** for PDFs is intentionally not implemented locally (pypdf cannot);
  DI handles orientation for its own inputs.
