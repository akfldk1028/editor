# Preserved design portfolio archives

The portfolio endpoints read Editor-owned directories under `EDITOR_DESIGN_DATA_DIR`: `creative-portfolios` and `portfolio-evaluations`. This installation uses `runtime/editor/design`. They serve historical source artifacts; importing does not create a new design run, refresh legal evidence, or change acceptance status.

Use the repeatable importer from the repository root:

```powershell
python -m backend.scripts.import_portfolio_archives --kind evaluations --source D:/Data/25_ACE/ARR/docs/playwright/design-route-live-verify --destination runtime/editor/design/portfolio-evaluations
python -m backend.scripts.import_portfolio_archives --kind evaluations --source D:/Data/25_ACE/ARR/docs/playwright/design-route-live-verify --destination runtime/editor/design/portfolio-evaluations --apply
```

Without `--apply`, the utility validates the source catalog and PNGs and reports the exact closure size. `--run RUN_ID` may be repeated to select a subset. Evaluation closure includes each selected manifest and every catalog preview. Creative closure includes portfolio/board, candidate JSON/render, and each referenced MASS directory containing the manifest and elevation handoff evidence. It does not copy unrelated run-tree files.

The importer validates source identities with the production catalog, verifies PNG structure, preflights all destination collisions, creates files exclusively, preserves original bytes and file timestamps, checks SHA256 after copying, and replays every selected destination catalog. `archive-import-manifest.json` records the source root, original run IDs, file paths, sizes, source mtimes and SHA256 hashes. Repeating the same import is safe. Existing different bytes or a different import manifest fail without replacement; no source files are changed. Absolute evaluation preview paths are rejected because preserving those bytes would otherwise keep an external filesystem dependency.

On 2026-10-05, all 124 evaluation runs were imported: 670 candidate records, 707 files, 65,309,824 bytes, including 583 PNG previews. The newest source manifest by original mtime is `legal-mass-v38-c181-uijeongbu-civic-live-vlm`, which has zero records. That ordering is preserved. A populated historical example is `legal-mass-v36-c179-law-online-capacity-advisory`; select its original run ID for preview verification.

The originally stated creative source `D:/Data/25_ACE/docs/mass` was absent. The preserved source collection was located at `D:/Data/25_ACE/ARR/backend/tmp_mass_check/c260-book`. Source audit and import results are described below. Source paths in these import receipts are provenance only; runtime catalog and image reads use the Editor copies.

Tests: `python -m pytest backend/tests/test_portfolio_archive_import.py -q` checks byte/timestamp preservation, repeatability, exact closure selection, collision non-overwrite, invalid PNGs, missing roots, and traversal rejection.

Creative source replay selected 54 of 77 runs: 29,613 files / 571,785,778 bytes including the referenced MASS evidence folders. The 23 excluded runs failed the existing `creative candidate geometry hash replay mismatch` check. No candidate hashes or validator rules were changed to make them pass. The complete selected IDs and exclusion reasons are in `design-creative-archive-source-audit.json`; excluded source folders remain untouched and their referenced artifacts are also preserved in the separate Editor quarantine described below.

To reproduce the creative import using that audited selection:

```python
import json
from pathlib import Path
from backend.scripts.import_portfolio_archives import migrate_archive

audit = json.loads(Path('docs/integrations/design-creative-archive-source-audit.json').read_text())
migrate_archive(audit['source_root'], 'runtime/editor/design/creative-portfolios',
                'creative', audit['selected_runs'])
```

Runtime archive bytes are local data, not application source. Retain/back up both destination directories together with their `archive-import-manifest.json` receipts. Their JSON source documents preserve old evidence/provenance strings verbatim; those strings are not runtime path fallbacks. The importer intentionally does not reconstruct missing evidence, treat failed historical review as passing, or execute new agent requests.

Completed destination validation results:

```json
{
  "creative-portfolios": {
    "manifest_sha256": "c1503c09b12f2e678412a1b632470757aa3e8cbceeb5efeeda3ee437cc644cd5",
    "runs": 54,
    "candidates": 1405,
    "files": 29613,
    "bytes": 571785778,
    "pngs": 9889
  },
  "portfolio-evaluations": {
    "manifest_sha256": "441b0427858fc1110c633077d37d41cb5a61ded35c67c295f2d6ef25a6da090c",
    "runs": 124,
    "candidates": 670,
    "files": 707,
    "bytes": 65309824,
    "pngs": 583
  },
  "default_creative": {
    "run_id": "book-develop-portfolio200-b10-20260928",
    "candidates": 2,
    "created_at": "2026-09-28T07:52:17.563370+00:00"
  }
}
```

## Failed-replay archive quarantine

The 23 runs excluded from the active creative catalog are retained under `runtime/editor/design/archive-quarantine/creative-portfolios`. They remain quarantined, not validated or promoted into the active 54-run catalog. The dedicated importer requires the `archive-quarantine/creative-portfolios` destination shape and refuses runs that pass the production catalog. No runtime catalog roots or validation gates are changed.

```powershell
python -m backend.scripts.quarantine_portfolio_archives --audit docs/integrations/design-creative-archive-source-audit.json --destination runtime/editor/design/archive-quarantine/creative-portfolios
python -m backend.scripts.quarantine_portfolio_archives --audit docs/integrations/design-creative-archive-source-audit.json --destination runtime/editor/design/archive-quarantine/creative-portfolios --apply
```

The first command performs the size preflight. The second preserves the bounded portfolio, board, candidate and referenced MASS evidence closure. Original bytes and timestamps remain unchanged. The same collision preflight and exclusive copy routine used by the active importer verifies every destination SHA256. The quarantine receipt records `archive_status: quarantined_validation_failure`, `active_catalog_eligible: false`, the exact per-run source error type/reason and manifest hash, and per-file hashes. It rechecks that the destination still fails the catalog with the same failure provenance. Damaged PNGs, if present, are preserved with explicit image-failure evidence rather than silently discarded or called valid.

Back up this quarantine directory and its `archive-import-manifest.json` alongside the active archives before retiring ARR storage. Failure records describe the current replay result, not a claim that the historical work never existed or that its bytes should be repaired automatically.

Verification: `python -m pytest backend/tests/test_portfolio_archive_import.py backend/tests/test_portfolio_archive_quarantine.py -q` (10 tests), including no active promotion, original failure provenance, escaping-reference rejection, destination conflicts, valid-run rejection, and damaged-image preservation.

Completed quarantine preservation (all 23 destination replay failures match their source):

```json
{
  "archive_status": "quarantined_validation_failure",
  "active_catalog_eligible": false,
  "runs": 23,
  "candidates": 792,
  "files": 16678,
  "bytes": 305880559,
  "pngs": 5567,
  "image_failures": 0,
  "manifest_sha256": "23f7f123262b5053a70f18785cf8293719207562bd7676bd41077fc3aa04368b"
}
```
