# ARR / selected AG integration status

**Overall: incomplete. ARR is still a runtime dependency.**
This is the current status, not another target architecture or completion claim.

| Area | Current evidence | Remaining gate |
|---|---|---|
| Product shell | Existing Editor routes extended with agents/projects/runs/land | Complete selected original user workflows |
| ARR local feature ownership | Zones, overlap limits, PNU parsing, address/parcel provider adapters under Editor modules/adapters | Real provider checks; remaining calculation/data/job ownership |
| ARR analysis/statistics | Product UI/API works through LandClient | Remove legacy service dependency after feature parity |
| Design/parking/3D | Existing Editor capabilities and earlier isolated scene evidence | Entire ARR source/data/artifact migration and end-to-end equivalence not established |
| Selected AG work management | Catalog, project binding, health run/history | General task inputs, attachments, stop/resume, direct commands and selected results UX |
| Communication | Saved request/reply and top-level flow; new real A2A health3 verified | Downstream peer hops, full topology and streaming |
| Shared agents | Remain in D:/Data/25_ACE/agents by user decision | Complete consumer/owner contracts; specialists still partial |
| Runtime cutover | Per-slice source changes committed; isolated validation | Load verified operational changes and prove original ARR/AG roots are unnecessary |

Concrete remaining dependency: `backend/app/api/routes_land.py` builds LandClient
from EDITOR_ARR_URL; analyze/stats still use it. `infra/config/services.json`
marks ARR as legacy-pending-relocation. The domain migration manifest explicitly
sets complete_backend_integration=false. Four local backend feature slices
are recorded there; that is not a percentage of the full migration.

Completion requires selected AG functions and all required ARR product functions
to run in Editor, preserving data/artifacts and existing routes, with original
ARR/AG service/source roots excluded from runtime. Shared agents are intentionally
external and do not need relocation. Original directories must not be deleted
before those gates and preservation checks pass.

Continuation: absorb raw-zone analysis with local persistence/statistics, then
provider/geometry/law branches. Downstream communication identity remains pending. Track both workstreams
in the existing function matrix and per-feature migration manifest; do not treat
successive UI slices as completion of backend absorption.
