# Agent instructions for DocAI

These instructions apply to every AI coding agent working in this repository (OpenAI Codex,
GPT-based tools, Claude Code, and others). Read them before changing code.

## Frontend architecture rules (mandatory)

* The frontend architecture rulebook is [`frontend/ARCHITECTURE.md`](frontend/ARCHITECTURE.md).
  It decides where code lives and which module may import which. Read it before adding, moving,
  or renaming any file under `frontend/src`.
* Every new module belongs to one of three target roots — `app/`, `features/`, `common/` — and
  dependencies point one way: `common/` → `features/` → `app/`. Existing files remain in their
  documented current homes until a feature is moved as a behavior-preserving unit.
* A module reaches `common/` only by passing the admission test in ARCHITECTURE.md §5: two
  features already import it, and it carries no domain vocabulary. Otherwise it stays in its
  feature, or gets duplicated.
* Requests are named functions in a feature's `api/` folder with a query-key factory. No inline
  `queryFn`, no hand-written query keys, no `axios` or `fetch` outside the API client.
* Every new file is kebab-case — `run-progress.tsx`, `use-table-state.ts`, `query-keys.ts` —
  whatever it exports. Symbols keep their own casing; only filenames change. Existing files are
  renamed when they move, not before (ARCHITECTURE.md §4.1).
* `frontend/src` is mid-migration to that layout (ARCHITECTURE.md §13). New work lands in the
  target structure; do not add files to `src/pages/` or to the `src` root.
* The boundaries are enforced by `oxlint`. If a lint error quotes an ARCHITECTURE.md section,
  fix the structure — do not add a disable comment.

## Frontend design rules (mandatory)

* The frontend design rulebook is [`frontend/DESIGN.md`](frontend/DESIGN.md). Follow it for any
  change under `frontend/src` that a user can see: layout, color, type, components, states,
  copy, and accessibility.
* Use design tokens and the shared components in `frontend/src/common/components/ui/` (remaining
  legacy primitives are in `frontend/src/components/ui.tsx`). Never write raw
  hex colors in components; add a token to both themes in `frontend/src/app.css` instead.
* Check every visual change in both themes (`extract-light`, `extract-dark`) and at the sizes in
  DESIGN.md §12, including tablet 768×1024 and 1024×768.
* Brand Orange is the brand voice, not a status color; warnings are amber (DESIGN.md §6.4).
* New UI patterns are added to DESIGN.md in the same change that introduces them.
* The Django admin follows the same palette through `UNFOLD["COLORS"]` in
  `backend/config/settings/base.py`. When a color token changes in `frontend/src/app.css`,
  update that block in the same change so the app and the admin do not drift.

## Verification before you finish

```bash
python scripts/verify.py
```

Use `python scripts/verify.py --browser` when a frontend interaction or responsive behavior changes.
The default verification does not install or require Playwright.

## Repository map

* `frontend/` React 19 + Vite + Tailwind 4 + daisyUI 5. Entry `src/main.tsx`, tokens `src/app.css`,
  shell `src/layouts/AppShell.tsx`, legacy pages `src/pages/`, Metrics `src/features/metrics/`,
  shared UI `src/common/components/ui/` and legacy `src/components/`.
* `backend/` Django 5.2 (`docai` app). See `README.md` for the keyless local quickstart.
* `ARCHITECTURE.md` explains the design decisions; `KNOWN_LIMITATIONS.md` what is not real yet.
* `examples/workflows/README.md` indexes standalone, pasteable type-specific JSON for every workflow type.
  Start there when authoring workflow configuration; keep examples aligned with `schemas/config.py` and
  validate changes with `backend/docai/tests/test_workflow_examples.py`. Examples do not replace saved or seeded defaults.
