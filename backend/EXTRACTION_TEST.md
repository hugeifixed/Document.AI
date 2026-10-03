# Local extraction visual test

`test_extraction` is a management command for testing a saved extraction workflow against
a local PDF or folder of PDFs. It uses the normal layout preparation, extraction, grounding,
validation and optional citation correction pipeline. It reads the configured application database;
it creates no datasets, documents, runs, labels or configuration versions there.

From `backend`, with the normal Django environment and database containing your workflow:

```bash
.venv/bin/python manage.py test_extraction \
  --workflow-id YOUR-WORKFLOW-UUID \
  --input /path/to/document.pdf \
  --output /path/to/test-output \
  --live
```

Replace `--input` with a folder to process its PDFs. Add `--recursive` to include subfolders.
The default limit is 10 PDFs, in sorted path order; set `--limit N` to choose another limit.
The manifest records omitted files. An output folder nested inside the input folder is excluded
from discovery. Use a separate output folder for each test to keep comparisons distinct.

`--live` uses the application's configured layout and model adapters and the saved workflow's
settings. Without it, the command uses the existing `pypdf` text-layer reader and deterministic
mock model. Offline mode checks the harness on text PDFs; scanned PDFs need an OCR adapter.
Saved scan-enhancement/high-resolution policies retain their normal adapter requirements.
Workflow types supported: `extract_structured`, `extract_unstructured`, and `extract_template`.
Classification and unbundling workflows are excluded.

Citation repair is **off by default**. Add `--citation-repair` to permit one bounded, citation-only
model request per extraction invocation. Use `--no-citation-repair` to disable it for this test even
when the workflow enables it. Without either flag, the command follows the saved workflow's
`citation_repair` setting. These overrides do not edit the saved workflow; `manifest.json` and
`result.json` record the effective setting. Grounding and validation always run. Unverified values
remain orange for human bounding and confirmation.

JPG rendering uses the existing optional dependencies. If needed, install them with
`uv sync --extra dev --extra image-normalization`. No new dependencies are introduced.

Each document gets `<filename>.extraction/` under the output folder, preserving input subfolders:

- `page-001.jpg`, `page-002.jpg`, …: source page with boxes and a label/value index.
- Additional `page-001-labels-02.jpg` panels when a page has more than 90 labels.
- `unlocated-labels-001.jpg` for values without a uniquely identified source page.
- `labels.csv` and `labels.json`: complete names, values, list-property paths and evidence statuses.
- `layout.json`: the layout used for extraction.
- `result.json`: extraction results, configuration, actual prompt versions, warnings and timings.

**Blue** identifies scalar boxes; **green** identifies individual list-property boxes;
**orange** identifies detected values without usable individual boxes. Orange values receive no
guessed locations. A star marks a corrected citation. Collections and corrected fields retain
their normal review requirements. Box coverage is distinct from whole-document accuracy or completeness.
Prepared documents are rendered using the exact representation analyzed by the layout service.

`manifest.json` indexes the batch results. A failed PDF does not stop the remaining selected files;
the command returns a nonzero exit status after finishing the batch and writes a sanitized
`error.json` for failures. Extraction JSON and labels are saved before rendering so a graphics
failure preserves completed extraction work. Document content is stored in the requested artifacts;
command progress reports counts and error codes.
