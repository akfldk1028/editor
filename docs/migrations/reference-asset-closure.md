# Preserved passport reference images

The 2026-10-05 inventory of 106 imported MASS passports found two distinct local reference-image URLs and no aesthetic-asset URLs. Both source files existed under `D:/Data/25_ACE/docs/ai-session-memory/reference-corpus`. The bounded migration copied only these two files (2,078,638 bytes) into `runtime/editor/design/docs/ai-session-memory/reference-corpus`.

`infra/migration/reference_asset_closure.py` reads verified imported passports, inventories their local reference URLs, rejects missing sources, escaping paths and conflicting destinations before copying, and leaves matching existing files intact. Run with `python -m infra.migration.reference_asset_closure --editor-data <absolute directory> --source-root <original corpus> --dry-run` to inventory; omit `--dry-run` to copy. It does not fetch network assets or rewrite source passports.

The ignored receipt at `runtime/editor/workspace/reference-asset-closure-20261005.json` records source/destination paths, sizes, SHA-256 hashes and HTTP verification. Both canonical `/api/v1/design/maas/reference-assets/...` requests returned 200 with response-body hashes identical to the originals:

- `archdaily_1013628.jpg`: `62321c096b591419142839b57fb03becd1303a74ab5f58205c870c5ef9372435`
- `archdaily_0007.jpg`: `7ba725473e0eb4dc2b746b790bfe4d9fbfe277abfeb4617e6d90be1cccfb0d1c`

Public passport responses normalize local URL fields into the Editor API namespace. Imported files remain byte-preserved; geometry, program and request identities remain unchanged. Archive reads use the same resolved data root as generation, including default and relative configurations.
