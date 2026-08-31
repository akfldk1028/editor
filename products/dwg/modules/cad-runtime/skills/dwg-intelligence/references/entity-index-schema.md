# Entity Index Schema Notes

DWG uses `cad-index/v0.2`. Consumers still accept legacy
`cad-index/v0.1` input while the DXF adapter migrates.

Required entity fields:

- `id`: local stable ID, usually `h:{handle}` when the CAD handle exists
- `handle`: CAD handle when available
- `type`: CAD entity type such as `LINE`, `LWPOLYLINE`, `TEXT`, `INSERT`
- `layer`: CAD layer
- `space`: `model`, `paper`, or `unknown`
- `layout`: layout name, `Model` for model space
- `bbox`: min/max point box or null
- `text`: TEXT/MTEXT/ATTRIB content when available
- `blockName`: block name for INSERT when available
- `attributes`: INSERT attribute tag/value evidence
- `geometry`: one typed discriminated geometry object
- `warnings`: parser or confidence warnings

Typed v0.2 geometry kinds:

- `line`: `start`, `end`
- `circle`: `center`, `radius`, `normal`
- `arc`: `center`, `radius`, `startAngle`, `endAngle`, `normal`
- `lwpolyline`: vertices with point/bulge/widths, closure, elevation, normal
- `point`: position
- `text`: insertion/alignment points, height, rotation, width
- `insert`: insertion point, rotation, XYZ scale, normal
- `bbox`: explicit supported-renderer fallback with reason
- `unavailable`: explicit missing-geometry reason

Coordinates use drawing units and three-number tuples. Angles use radians.
INSERT geometry describes the reference transform; it does not expand nested
block definitions. Model and Paper Space evidence comes from layout-associated
block records.

The model must not calculate bbox, length, area, closure, intersections,
containment, block expansion, or missing geometry by itself.
