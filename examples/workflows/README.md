# Copy-and-paste workflow configurations

Start here to create a workflow version in **New workflow version → Type-specific configuration JSON**.
Every `.json` file in this folder is a complete editor body: copy the whole file, including its outer braces.
The folder name is the exact `workflow_type` key. Files contain no comments, placeholders that require substitution,
or API request wrappers. Template extraction has a saved-template prerequisite described below.

These are editable starting points, not extraction-accuracy guarantees. All processing examples deliberately send
results to human review for the first iteration. They contain field definitions, not example customer data or secrets.

The builder's **Generate with assistant** panel produces another valid starting point for three
extraction workflow types. Its JSON may be much shorter than these comprehensive examples: it
proposes fields from the stated goal and samples, with every field optional until reviewed. For
ambiguous amounts, row associations, masked identifiers and variable lists, add or check field
`guidance`. Use `enum` only with explicit choices; an empty enum list is syntactically valid but
does not constrain extraction. Mixed-bundle categories should explain how to identify each
document and how continuation pages stay with it. The examples remain useful as review checklists,
not mandatory templates to copy wholesale into every generated proposal.

## Pick an example

| Your input and goal | Select this workflow type in the UI | Copy this JSON |
| --- | --- | --- |
| One file containing W-2, 1099 and promissory-note documents | Unbundling + classification + extraction | [Mixed tax and loan package](unbundle_classify_extract/w2-1099-promissory-note.json) |
| One W-2 per file; predictable named fields | Extraction only: structured (layout-preserved, generic extractor) | [W-2 custom schema](extract_structured/w2.json) |
| One 1099 per file; payer address, recipient and reported amounts | Extraction only: structured (layout-preserved, generic extractor) | [1099 common schema](extract_structured/1099-common.json) |
| Explore the explicit key/value pairs in an unfamiliar form | Extraction only: structured (layout-preserved, generic extractor) | [All visible fields](extract_structured/all-visible-fields.json) |
| One promissory note per file, including its continuation pages | Extraction only: unstructured (LLM strategies) | [Promissory note](extract_unstructured/promissory-note.json) |
| Categorize separate tax/loan documents using printed titles, without LLM fallback | Classification only: structured (rules + optional LLM) | [Rule classification](classify_structured/tax-and-loan-documents.json) |
| Categorize separate tax/loan documents with an LLM; do not extract fields | Classification only: unstructured (LLM) | [LLM classification](classify_unstructured/tax-and-loan-documents.json) |
| Reuse an existing governed extraction template | Extraction only: versioned template | [W-2 template reference — prerequisite required](extract_template/w2-template-reference.json) |
| Define comparison tolerance for evaluation | Evaluation of predictions against ground truth | [Evaluation configuration — separate execution path](evaluate/numeric-tolerance.json) |

```text
examples/workflows/
├── README.md
├── unbundle_classify_extract/w2-1099-promissory-note.json
├── classify_structured/tax-and-loan-documents.json
├── classify_unstructured/tax-and-loan-documents.json
├── extract_structured/
│   ├── w2.json
│   ├── 1099-common.json
│   └── all-visible-fields.json
├── extract_unstructured/promissory-note.json
├── extract_template/w2-template-reference.json
└── evaluate/numeric-tolerance.json
```

There are no fragments, `$ref` links, generators or imports to resolve before pasting. The W-2, 1099 and note schemas
are intentionally repeated in the mixed-package file so it works on its own. A regression test keeps those copies aligned.

## Create the first version

1. Select your project in Working context and open **New workflow version** with an operator account.
2. Choose the workflow type from the table **before** pasting: changing type resets the editor to its built-in sample.
3. Select the actual Azure OpenAI deployment name in the Model section. The UI initializes it from the server's
   configured deployment when available; a model family name is not necessarily your deployment name.
4. Set the model and chunking controls using the starting values below. Paste the complete JSON file into the editor,
   replacing its existing contents. Do not paste the table, a Markdown code fence, or an outer `{"config": ...}` object.
5. Click **Validate**, resolve any reported issues, then create the workflow version. Shared UI settings become part
   of the saved configuration together with this JSON. Editing either the JSON or the controls requires validation again.
6. For processing workflows, upload documents to the intended dataset, start a run using the new version, and review
   the results and source evidence. Evaluation uses the separate path below. Modify the field definitions and save
   another version when the business requirements change.

### Shared UI controls

| Setting | Starting value for these examples | Why |
| --- | --- | --- |
| Maximum output tokens | **16000** for W-2, mixed packages and generic exploration; **8000** for a note or 1099; **4000** for classification | Trial budgets, subject to the deployed model's limits. More fields and evidence require more output. |
| Temperature | **0** | Start with the existing deterministic configuration convention; provider/model support still applies. |
| Chunking strategy | **Whole document** for short forms, classification and short mixed packages | Preserve nearby labels, values and note continuation context. |
| Fallback | **Context length** | The whole-document strategy can fall back when its character limit is exceeded. |
| Chunk size / overlap | **24000 / 1500** characters | Starting values for context-length chunks, especially longer notes. |
| Layout controls | Keep tables, source IDs and row-band linking enabled initially | Preserve form structure and evidence references. |
| Scan enhancement | **Use original** initially | The JSON does not enable optional normalization or DI add-ons. |

The token setting is a maximum **per LLM call**, not a per-document or per-run total, and increasing it does not
guarantee completeness. A mixed package makes multiple calls. Inspect finish reasons and actual token usage; if
output is truncated, reduce requested fields/chunk size or increase the supported limit. For long notes, choose
**Context length** directly and keep the reconciliation policy in the example.

Do not add `model.max_tokens`, `input_quality` or `di_analysis` to these editor bodies: the UI rejects them in favor
of its dedicated controls. These samples also leave model, chunking and layout settings out so they cannot silently
contradict the controls. Credentials, resource URLs and tenant/client settings belong in deployment configuration.

The files alone are not full headless API requests. See [INTEGRATION.md](../../INTEGRATION.md) for invoking a saved
workflow. Creating a version through the API requires `project`, `name`, `workflow_type` and the composed `config`.

## Mixed-bundle document identification

The mixed-package example has a separate `segmentation` block. Its defaults inspect at most
12 pages per window, overlap by two analyzed pages, and sample up to 3,000 characters per page.
The 60,000-character request guardrail counts instructions, categories, source metadata, output
schema, and a reserve of four characters per each of the 4,000 segmentation output tokens.
This reserve is a budgeting approximation, not a tokenizer or a provider context-limit guarantee.
Extraction output tokens remain controlled independently by the Model section.

Repeated categories remain separate document instances. Overlapping windows compare whether
adjacent pages belong to the same instance; a disagreement gets one bounded boundary check.
Missing pages, repaired ranges, omitted dense-page evidence, or unresolved boundaries require
review. An extracted value being accepted never establishes that document boundaries are correct.
No whole-bundle segmentation fallback is made. Multiple forms on one page and interleaved documents
require manual review/reprocessing; they are not automatically supported document structures.

`segmentation_strategy` is retired and rejected during validation. Use `segmentation` for document
identification and `chunking` for extraction within each identified document. These controls are
independent; choosing per-page extraction does not repair incorrectly grouped documents.

## What the extraction examples ask for

**W-2:** employer and employee identity/address, tax year, boxes 1–8, 10–11, separate code and amount fields for
**12a, 12b, 12c and 12d**, the three box-13 selection states, box-14 entries and two separate state/local rows
across boxes 15–20. A blank/reserved box is not a field type. This is a broad standard-form starter: add explicit
fields for extra rows, attachments or nonstandard forms rather than assuming the schema discovers them automatically.
Printed masking on identifiers is preserved; missing amounts are not inferred as zero.

**1099:** the common schema preserves the printed subtype, payer name and **street address/city/state/postal code**,
recipient details and account number. `reported_amounts` is a list carrying each printed box number, label, amount
and optional row identifier. The 1099 family has different box meanings; this sample deliberately does not treat
every 1099 as a 1099-NEC. If your consumers require stable named scalar values, copy this schema and replace the list
with the exact fields for the subtype you accept. Do not reuse a box's meaning across different subtypes.

**Promissory note:** borrower, lender, principal, dates, rate/interest terms, payment terms, late charges, prepayment,
collateral, governing law and loan number. It copies stated terms; it does not calculate rates or interpret legal clauses.

**Mixed package:** category keys route each recognized segment to its named inline schema. Continuation guidance
keeps note pages together. Unknown documents remain `other` and need review; they are not automatically sent through
a generic extractor. Standalone extraction/classification examples do not replace unbundling when a file contains
multiple logical documents or repeated forms. Unbundling is page-based: it is not a way to split multiple forms on
one physical page into independent documents.

**Generic extraction:** `mode: "default"` asks the LLM for explicit key/value pairs without a fixed business schema.
It is useful for exploration. Field names can vary and repeated keys are deduplicated; use the W-2 custom schema
for predictable output or unbundling for repeated logical documents. Both default and custom structured extraction
use the configured LLM after layout preservation; "structured" does not mean DI-only extraction.

Lists use `type: "list"` with the desired entry shape described in `guidance`; nested JSON Schema `properties` or
`items` are not part of this workflow FieldSpec. Row pairing and list entries still require manual review; automatic
scalar grounding does not verify every entry or provide a separate bounding box for every list cell. Separate scalar
fields, as used for W-2 box 12, are preferable when each position needs its own review/evidence target.

## Prerequisites and limits

- Real scans require `DOCAI_LAYOUT_ADAPTER=azure_di` and configured Azure credentials. The local `pypdf` adapter
  reads text layers; it does not OCR images. Real LLM extraction also needs the Azure OpenAI adapter enabled in the
  environment. The local `mock` adapter is useful for pipeline tests, not extraction accuracy.
- All pages must reach the layout adapter. A partial DI response cannot supply evidence or fields for omitted pages;
  increasing tokens or changing workflow JSON cannot recover those pages. Check the layout-completeness warning.
- Validation checks configuration shape and schema routing. It does not call Azure, prove extraction quality, or
  confirm that a named extraction template exists. Test your deployment and representative documents separately.
- The examples route all predictions to human review using an unconditional rule. Replace that rule only when you
  deliberately design acceptance policy. Routing is **first match wins**: missing evidence, validation failures,
  disagreement and uncertain segmentation should be considered before confidence-based acceptance.
- For template extraction, an administrator must first create `w2-template`, version `1`, **in the same project**,
  with its schema, prompt and model configuration. Or edit the reference to an existing name/version. The reference
  JSON does not create those records. Template definitions supply the schema and template-specific settings.
- The evaluation JSON validates and can be saved as a workflow configuration, but **Start a run cannot execute it**.
  Use **Evaluation → Evaluate a run** on an existing processing run with finalized ground-truth labels and set numeric
  tolerance to `0.01`. That screen sends its own settings to `/evaluations/`; it does not load this saved config.

## Maintaining the examples (humans and agents)

- Keep `examples/workflows/<exact_workflow_type>/<scenario>.json` as the convention. Use lowercase kebab-case
  scenario names and two-space JSON indentation with a final newline. Add each file to the table above.
- Keep every file independently pasteable and free of credentials, customer values, comments, `$ref` and API wrappers.
- Use the backend [configuration schemas](../../backend/docai/schemas/config.py) as the contract and the frontend
  [composeWorkflow function](../../frontend/src/pages/WorkflowBuilder.tsx) for editor restrictions and control precedence.
  [Workflow strategies](../../backend/docai/workflows/) determine what the settings actually do.
- Keep category `extraction_schema` names consistent with inline `schemas[].name`; use `schema` (singular) for standalone
  custom extraction. Use only supported field types. `required` means a missing extraction triggers validation, not
  permission to invent a value. Keep names unique within each schema.
- Update the matching standalone and mixed schemas together. The examples are documentation assets, not production
  defaults: do not silently replace seeded or already saved workflow configurations.
- Run the example contract tests from `backend/`: `uv run pytest docai/tests/test_workflow_examples.py`.
  They exercise the UI's validate/create API sequence offline for every example and detect silently ignored keys.
  Live extraction and institutional review remain separate checks.
