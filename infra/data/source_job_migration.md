# Source job migration

`source_jobs/` contains the 37 remaining Python jobs, helpers, and tests formerly maintained in `D:/Data/25_ACE/data/index`. The three publication jobs already managed in `infra/data/jobs` are excluded. Original source hashes are recorded in `source_jobs/migration_manifest.json`; runtime JSON, rasters, archives, credentials, and downloaded originals are not added to git.

Configuration is read by `source_jobs/source_job_paths.py`:

| Environment variable | Default | Purpose |
|---|---|---|
| `DATA_ROOT` | `C:/Data/25_ACE` | External map files, reference downloads, processed exports |
| `NGII_DEM_ROOT` | `D:/Data/NGII_DEM` | Existing DEM inputs, work, receipts, locks |
| `NGII_ORIGINAL_ROOT` | `DATA_ROOT/ngii-original-batch` | Existing authorized package inputs and processing |
| `ACE_SOURCE_DATA_ROOT` | `D:/Data/25_ACE/data` | Existing raw national source data |
| `ACE_INDEX_STATE_ROOT` | `ACE_SOURCE_DATA_ROOT/index` | Existing registry and historical JSON state |
| `EDITOR_ROOT` | Repository containing this module | Editor tools and three managed publication jobs |
| `ACE_AGENT_ROOT` | `EDITOR_ROOT/../agents` | Existing SiteContextAgent implementation |
| `NGII_SOURCE_JOB_CONFIG` | `DATA_ROOT/management/source-job-private.json` | Private NGII order/download values |

All original public/world-buildings readers now resolve below `DATA_ROOT/world-buildings`. No R2 operation is introduced. The source registry keeps raw-folder references relative to `ACE_SOURCE_DATA_ROOT`; processed extraction defaults to `DATA_ROOT/processed`. JSON state remains at its existing location by default, because these receipts feed running jobs. Changing `ACE_INDEX_STATE_ROOT` requires separately copying and verifying that state and configuring every producer/consumer consistently.

The probe and order-recovery utilities no longer embed opaque NGII authorization/order values. On activation, the installer extracts only the existing literal values using Python AST, writes them outside git, and records a private-file hash without values. Existing conflicting or incomplete private configuration is rejected. `NGII_PROBE_DIRECTORY`, `NGII_ORDER_PREFIX`, `NGII_ORDER_SUFFIXES_JSON`, and `NGII_ORDER_NUMBER` environment values override the private file. Preserve the private configuration and original backups; they contain the existing authorized NGII runtime information.

From the editor repository, inspect the dry run:

```powershell
python infra/data/source_job_migration.py
```

Activate the prepared entrypoints (this does not start jobs):

```powershell
python infra/data/source_job_migration.py --apply
```

The installer validates every original hash before writing, copies all originals into a timestamped `DATA_ROOT/management/source-job-backups` directory, verifies the backup hashes, and records the managed-code and launcher hashes in `receipt.json`. It then atomically replaces each legacy Python entrypoint. Both script execution and imported helper exports delegate to the managed source. JSON state and the three preexisting publication entrypoints are untouched. A concurrent source edit rejects activation; partial activation is recorded and can be safely rerun after reviewing the cause. Already active entrypoints are recognized.

Running processes retain their loaded code until their next restart. This migration neither terminates processes nor starts download, conversion, publication, or upload work. Do not infer job completion from migration completion. Backups are never deleted by the installer. To roll back, stop affected jobs through the normal operator procedure and copy the selected timestamped backup `.py` files back to their exact legacy paths after checking the receipt hashes; retain the backup and receipt.

Safe verification:

```powershell
python -m pytest infra/data/source_job_migration_test.py infra/data/source_jobs -q
```

The tests cover dry-run behavior, changed-source refusal, exact backup preservation, import exports, idempotency, private configuration extraction/override, external path configuration, sibling job routing, and the existing geometry/parser/resolver tests. Production network/conversion/publication jobs must not be imported for verification: several run on import.
