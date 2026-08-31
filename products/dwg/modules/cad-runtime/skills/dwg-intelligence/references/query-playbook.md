# Query Playbook

## Layer Query

Use `cad.find_entities_by_layer` with the exact layer name. If the user gives a loose name, inspect `cad.get_layers` first.

## Text Query

Use `cad.find_text`. Return matched text and IDs. Do not OCR unless CAD text is unavailable.

## Type Query

Use `cad.find_entities_by_type` for `LINE`, `LWPOLYLINE`, `TEXT`, `MTEXT`, `INSERT`, `HATCH`, and similar entity types.

## Unsupported Summary

Use `cad.list_unsupported` when a result may be incomplete or when opening a new drawing.
