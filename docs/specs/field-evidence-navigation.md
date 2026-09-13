# Locate extracted-field evidence

Small review-workspace improvement requested September 13, 2026. Selecting a field should make
its location easy to find, using the existing viewer and saved source spans. No new dependency,
backend endpoint, persisted preference, or processing job.

## Acceptance

- Mouse and keyboard activation select the field, navigate to its evidence page, and reveal the
  bounding box inside the document preview. Activating the same field again locates it again.
- Show one brief primary-colour emphasis, then keep a clear selected outline. Reduced motion
  uses instant scrolling and a static outline. Keep keyboard focus on the field; announce location.
- Wait for the matching PDF page/image to render. Old pages, run changes and background refetches
  must not steal scroll position or flash stale coordinates.
- Locate evidence on the processing representation that matches the run. Explain a switch from
  an incompatible original; do not draw processing coordinates over the original.
- Missing spans or geometry get a quiet, honest explanation. Preserve existing sheet/text viewers.
- Preserve run and origin URL context and existing review actions/RBAC.
- Follow DESIGN.md; verify both themes, four documented viewport sizes and reduced motion.

## Local task graph

1. Extend field selection and the existing document pane; focused interaction tests.
2. Verify real PDF rendering and navigation with the optional, isolated Playwright suite.
3. Integrate, review against this specification and design standards, and run repository checks.
