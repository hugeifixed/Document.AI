# Brand marks

The app mark is **Rings**: three concentric rings cropped at the top-right of a navy tile
(`#0B2E52`, corner radius 28%), with the sign-in cover's short orange bar (`#F58025`) bottom-left.
Source of truth is `<BrandMark />` in `src/components/ui.tsx`; the same drawing ships as
`/favicon.svg` and `mark-rings.svg` here. Rules: `frontend/DESIGN.md` §3.4.

| File | Name | Use |
| --- | --- | --- |
| `mark-rings.svg` | Rings | The app mark. Keep in sync with `<BrandMark />` and `/favicon.svg`. |
| `mark-signal.svg` | Signal | Option kept for reference. No tile: strokes follow `prefers-color-scheme`. |
| `mark-radius.svg` | Radius | Option kept for reference. Rings with the orange bar as their radius. |
| `mark-quadrant.svg` | Quadrant | Option kept for reference. Rings centred on the tile corner. |

The rings are drawn against the whole tile (24-unit grid over the full 64px) and the bar in the
57% glyph area, so scale the whole file rather than redrawing at another stroke weight.
