# DWG Intelligence Agent Skill

Use this skill when a user asks questions about DWG/DXF drawing search, checking, comparison, or extraction.

## Rules

1. Never infer CAD geometry directly from the language model.
2. Open or build the drawing index before answering object-level questions.
3. Use CAD tools for layer, type, text, block, geometry, and unsupported-object queries.
4. Mention entity `id` or `handle`, `type`, `layer`, and bbox when tool output provides them.
5. Do not modify the source DWG/DXF. Save findings as sidecar JSON or overlay records.
6. If unsupported, proxy, missing bbox, xref, font, or codepage warnings exist, include the limitation in the answer.

## Minimum Tool Loop

```text
cad.open_drawing
cad.build_index
cad.get_layers or cad.find_entities_by_layer/type/text
cad.get_entity for exact handle evidence when needed
cad.list_unsupported before reporting completeness
```

Viewer select/zoom actions and sidecar writes are not currently exposed by the
MCP server. Do not claim that they ran.

## Answer Format

Keep answers short and grounded in tool output:

- query interpreted
- count of matched entities
- top entity IDs/handles with layer/type
- visible action taken, such as highlight or zoom, if available
- warnings or unsupported-object limits
