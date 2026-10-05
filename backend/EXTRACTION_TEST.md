# Local extraction visual test

`test_extraction` is a management command for testing a saved extraction workflow against
a local PDF, JPG/JPEG, PNG, or TIF/TIFF file, or a folder containing those formats.
It uses the normal layout preparation, extraction, grounding,
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

Replace `--input` with a folder to process its supported files. Extensions are case-insensitive;
other file types are ignored. Add `--recursive` to include subfolders.
The default limit is 10 files, in sorted path order; set `--limit N` to choose another limit.
The manifest records omitted files. An output folder nested inside the input folder is excluded
from discovery. Use a separate output folder for each test to keep comparisons distinct.

`--live` uses the application's configured layout and model adapters and the saved workflow's
settings. Without it, the command uses the existing `pypdf` text-layer reader and deterministic
mock model. Offline mode checks the harness on text PDFs; scanned PDFs and raster images
need `--live` with an OCR adapter such as Azure Document Intelligence. Unsupported image/adapter
combinations produce `LAYOUT_ADAPTER_UNSUPPORTED` without making model calls.
Saved scan-enhancement/high-resolution policies retain their normal adapter requirements.
Workflow types supported: `extract_structured`, `extract_unstructured`, and `extract_template`.
Classification and unbundling workflows are excluded.
Runs and this command share governed version resolution, including prompt overrides and pinned
template schema, guidance, and chunking. Local overrides affect only the test's configuration snapshot.

Citation repair is **off by default**. Add `--citation-repair` to permit one bounded, citation-only
model request per extraction invocation. Use `--no-citation-repair` to disable it for this test even
when the workflow enables it. Without either flag, the command follows the saved workflow's
`citation_repair` setting. These overrides do not edit the saved workflow; `manifest.json` and
`result.json` record the effective setting. Grounding and validation always run. Unverified values
remain orange for human bounding and confirmation.
Repair can use only complete source elements visible in the submitted chunk. A source ID on the
same page, or a partially submitted table/paragraph, cannot authorize evidence outside that chunk.
Mixed valid/invented IDs can qualify when the surviving submitted references uniquely locate the
unchanged value. Repair must cite that same occurrence and retains the original references in its
history. Fully invalid or ambiguous citations stay orange; successful corrections still need review.

Metadata orientation preparation uses core Pillow even with scan enhancement off. JPG/PDF page
rendering also needs optional PDFium. Install the rendering extra with
`uv sync --extra dev --extra image-normalization`. OpenCV remains optional scan-enhancement code.

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
Ordinary JPEG/PNG images without orientation metadata are rendered directly. Explicit raster
rotation/mirroring metadata is consumed before OCR, independently of scan enhancement. Adjusted
images and TIFF frames produce a lossless PDF; that same PDF supplies OCR and preview images.
Original uploads remain unchanged, PDF rotation metadata is respected by the PDF renderer,
and physical sideways content without useful metadata is not automatically reoriented.
The preview applies no separate EXIF orientation or scan correction. Skipped pages remain visible
under their original page numbers. Signature, upload-size, page-count and image-decoding checks run
before provider calls. Raster frames use the application's configured image pixel/dimension limits.

Labels display raw source values. Boolean fields retain the printed answer (such as `Yes`/`No`)
or a cited checkbox's `selected`/`unselected` state. `result.json` stores that `raw_value` alongside
the recognized `normalized_value` of `"true"` or `"false"`. Existing true/false field guidance
describes the normalized result; extraction still preserves the printed answer for citations.
Absent or unrecognized answers have no normalized boolean value, and nonempty unrecognized
answers fail validation for review.

Default-mode structured extraction keeps repeated labels at separate source locations. For example,
two `Date of Birth` entries remain two results, even if their values are identical; their label names
are not renamed to infer who owns each value. Separate results receive separate visual label IDs.
Only predictions with the same case/whitespace-normalized name, exact unchanged raw value, and an
independently verified, unambiguous source occurrence are deduplicated, including overlap between
chunks or alternative citations of the same value. Missing, invalid, fuzzy, unlocated, or ambiguous
evidence cannot identify duplicates; those values stay in the results for normal review. Custom-schema
extraction is unchanged. Compare repeated entries and their locations with the source: a box verifies
a location, not the association between a value and a person or other record.

Null/empty field values and empty collections produce no labels, including no orange labels.
Inspect the complete field results in `result.json` for omissions and compare them with the source
document. Citation repair corrects references for detected values; it cannot fill missing values.
A report with no orange labels can still have missed fields. Label and box counts describe retained
populated values, not the number of expected fields or a complete accuracy score.

`manifest.json` indexes the batch results. A failed file does not stop the remaining selected files;
the command returns a nonzero exit status after finishing the batch and writes a sanitized
`error.json` for failures. Extraction JSON and labels are saved before rendering so a graphics
failure preserves completed extraction work. Document content is stored in the requested artifacts;
command progress reports counts and error codes.
