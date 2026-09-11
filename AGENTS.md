# Agent instructions for DocAI

These instructions apply to every AI coding agent working in this repository (OpenAI Codex,
GPT-based tools, Claude Code, and others). Read them before changing code.

## Frontend design rules (mandatory)

* The frontend design rulebook is [`frontend/DESIGN.md`](frontend/DESIGN.md). Follow it for any
  change under `frontend/src` that a user can see: layout, color, type, components, states,
  copy, and accessibility.
* Use design tokens and the shared components in `frontend/src/components/ui.tsx`. Never write raw
  hex colors in components; add a token to both themes in `frontend/src/app.css` instead.
* Check every visual change in both themes (`extract-light`, `extract-dark`) and at the sizes in
  DESIGN.md §12, including tablet 768×1024 and 1024×768.
* Brand Orange is the brand voice, not a status color; warnings are amber (DESIGN.md §6.4).
* New UI patterns are added to DESIGN.md in the same change that introduces them.

## Verification before you finish

```bash
cd frontend && npm run lint && npm test && npm run build
cd backend && .venv/bin/python -m pytest
```

Lint runs `jsx-a11y`; an accessibility lint error blocks the change.

## Repository map

* `frontend/` React 19 + Vite + Tailwind 4 + daisyUI 5. Entry `src/main.tsx`, tokens `src/app.css`,
  shell `src/layouts/AppShell.tsx`, pages `src/pages/`, shared UI `src/components/`.
* `backend/` Django 5.2 (`docai` app). See `README.md` for the keyless local quickstart.
* `ARCHITECTURE.md` explains the design decisions; `KNOWN_LIMITATIONS.md` what is not real yet.
