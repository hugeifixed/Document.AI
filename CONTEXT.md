# Document AI

The platform turns source documents into governed, traceable results and supports human verification of those results.

## Language

**Project**:
A business use case that owns Datasets, workflow configurations, and Runs.
_Avoid_: Folder, tenant

**Dataset**:
A named collection of Documents within one Project. Its split describes its intended use in model and workflow development.
_Avoid_: Project, upload batch

**Working context**:
The Project and optional Dataset currently selected by a user to scope frontend lists and mutations. A selected Dataset must belong to the selected Project; changing Project clears Dataset.
_Avoid_: Preference, authorization scope

**Run**:
One execution of an immutable workflow configuration over a Dataset. A Run owns progress and lifecycle state and snapshots the configuration, prompts, schemas, and adapters it used.
_Avoid_: Celery task, request

**RunItem**:
The independently claimed, retried, and audited work for one Document in a Run. RunItem failures can be retried without repeating completed Documents.
_Avoid_: Run, page task

**Configuration snapshot**:
The fixed workflow configuration and governed versions selected for an execution, including the prompts, schemas, templates, and adapters used. A local preview can select execution overrides without changing the saved workflow or an existing Run's snapshot.
_Avoid_: Latest settings, editable workflow

**WorkflowInvocation**:
A caller's logical request to apply one workflow configuration to Documents in a Dataset. Repeated submissions of that same invocation refer to the same Run or recorded acceptance failure.
_Avoid_: Run, individual request attempt, Celery task

**GroundTruthLabel**:
A versioned human assertion of the expected category or field value for a document. It may identify supporting source evidence or explicitly state that a value is absent.
_Avoid_: Corrected field, extracted result

**Ground-truth selection**:
The transient source evidence a reviewer chooses while creating a GroundTruthLabel: a PDF text region, layout words, or a spreadsheet cell range. An explicit absence needs no source selection.
_Avoid_: Model prediction

**SourceSpan**:
The stored location tying a prediction, an individual collection property, or a GroundTruthLabel to its source document. A property span does not support the entire collection; an absent GroundTruthLabel has no SourceSpan.
_Avoid_: Highlight, bounding box
