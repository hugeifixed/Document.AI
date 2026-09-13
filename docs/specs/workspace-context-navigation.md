# Workspace context navigation

The Working context selectors control which project's and dataset's documents, results, runs,
and review items are shown. Changing context never moves documents or changes their ownership.

## Expected behavior

- Changing project or dataset on a list refreshes that list in the selected scope and resets
  pagination. Keep independent search and status filters where they still make sense; remove
  resource-specific URL parameters that could restore the previous scope.
- From an individual document's inspect, review, or label page, changing context opens
  `/datasets` in the new scope. From an individual run, it opens `/runs`.
- Confirm discarding unsaved labels or configuration before either selector or page changes.
  Cancel and Escape preserve the page, entered values, and both previous selectors. Confirm
  applies the scope and navigation together. A confirmed switch from the workflow builder
  opens `/configurations`.
- Disable context selectors during a save. Successful saves clear the draft warning; failed
  saves retain it, including label evidence selections and configuration JSON changes.
- A direct document link aligns the selectors with the document's actual authorized dataset
  and project. A direct run link does the same when its authorized scope is available. Stale
  selected context and late responses must not overwrite a newer context choice. A dataset
  missing from the first page of options is not evidence that it is unavailable.
- On document routes, show the quiet hint “Changing workspace opens its documents.” beneath
  the selectors. Associate it with both controls using `aria-describedby` on desktop and mobile.

## Starting a run

Group the optional Document limit and Choose documents action in a calm, full-width
“Documents to process” section below the setup fields. Explain that a blank limit includes
all eligible documents, a limit takes the oldest eligible uploads first, and an explicit
selection includes only the chosen documents. Stack controls when space is limited and use
the existing design tokens.

Keep existing selection semantics: selections survive chooser pagination and search, applying
a selection clears the limit, Cancel and Escape preserve the previous selection, and changing
dataset clears it. Eligibility remains enforced by the server when the run starts.

## Verification

Cover scoped list navigation, direct links, inaccessible resources, late responses, and draft
cancel/discard and save outcomes. Verify keyboard and mobile dialog behavior and the changed
controls in both themes at the viewport sizes and zoom described in `frontend/DESIGN.md`.
