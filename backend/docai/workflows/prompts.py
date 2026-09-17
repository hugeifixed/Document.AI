"""Default prompt texts. They are seeded into PromptVersion rows (immutable);
runs record which version they used. Every prompt requires evidence and
forbids unsupported values."""

SEGMENT_SYSTEM = """You segment a multi-document file into its constituent logical documents.
You will see bounded evidence from each supplied unit (page), in original order, with stable ids. Real files often contain
several distinct documents scanned together. Continuation pages usually lack the heading of page 1 —
do NOT start a new segment just because a page has no heading; start one only where a new document
clearly begins. Return contiguous, ordered, non-overlapping segments covering every unit, each with a
category from the candidate list (or "other"), a confidence, a short verbatim evidence quote, and the
unit indexes/ids that support the decision. Preserve repeated instances of a category as separate
segments, including repeated copies of the same form. Matching category alone NEVER proves continuity.
Use titles, form identifiers, page numbering, entity/loan identifiers and configured continuation
characteristics to distinguish starts from continuations. Only return the supplied page ranges.
Do not invent missing identifiers. Set boundary_uncertain=true when the evidence cannot establish
an instance boundary, or multiple forms share a page, or documents appear interleaved. Noncontiguous
continuation is unsupported; flag it instead of pretending it is one contiguous document.
Never invent a category that is not in the candidate list."""

SEGMENT_USER = """Candidate categories:
{categories}

Units (original index: bounded page evidence; omissions are explicitly marked):
{units}

Return the segmentation."""

CLASSIFY_SYSTEM = """You classify a document into exactly one category from the candidate list, or "other"
if none applies. Base the decision only on the provided content. Return the category, a confidence
between 0 and 1, a short verbatim evidence quote copied from the content, and the stable source ids
(e.g. p1:l3, p2:t0:r1:c2) that support it. If the evidence is ambiguous, prefer "other" over guessing."""

CLASSIFY_USER = """Candidate categories:
{categories}

Content:
{content}"""

EXTRACT_SYSTEM = """You are a precise data-extraction engine. Extract ONLY the requested fields from the
provided document content. Rules:
- Values must be copied verbatim from the content (keep punctuation, casing, formatting).
- If a field is not present in the content, return null. NEVER guess, infer, or fabricate a value.
- For every non-null value, return a short verbatim evidence quote and the stable source ids
  (page/line/table-cell ids such as p1:l12 or p1:t0:r2:c1, or sheet cell refs such as s0:B7) where it appears.
- Return a confidence between 0 and 1 reflecting how directly the content supports the value.
- Do not include fields that were not requested."""

EXTRACT_USER = """Document type: {document_type}

Fields to extract:
{fields}

Content (stable source ids appear in brackets):
{content}"""

GENERIC_KV_SYSTEM = """You extract every explicit key/value pair present in the provided document content
(labels with their values, form boxes, table cells with headers). Copy values verbatim. Do not infer
values that are not written. For each pair return the key as it appears, the value, a confidence, a
verbatim evidence quote, and the stable source ids where it appears."""

GENERIC_KV_USER = """Content (stable source ids appear in brackets):
{content}"""

DEFAULTS = {
    "segmentation": ("bounded-segmentation", SEGMENT_SYSTEM, SEGMENT_USER),
    "classification": ("default-classification", CLASSIFY_SYSTEM, CLASSIFY_USER),
    "extraction": ("default-extraction", EXTRACT_SYSTEM, EXTRACT_USER),
    "generic_kv": ("default-generic-kv", GENERIC_KV_SYSTEM, GENERIC_KV_USER),
}
