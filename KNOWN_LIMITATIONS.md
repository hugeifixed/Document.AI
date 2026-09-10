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
* **Session auth via /admin/ login.** No SSO/OIDC integration is included; DRF session + basic auth only.
* **Per-project object permissions** are a hook, not enforced membership.
* **Frontend**: the correction dialog uses `window.prompt` (replace with a native `<dialog>` form);
  no offline/PWA behavior; no automated axe/Lighthouse run was performed here.
* **Raw model responses** are stored as artifacts with a retention value but no purge job.
* **Rasterization / deskew / blank-page removal** for PDFs is intentionally not implemented locally (pypdf cannot);
  DI handles orientation for its own inputs.
