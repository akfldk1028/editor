"""Before/after probe pairs: a pool tile beside the same name rebuilt now.

Eye verification for an executor change without waiting on the full delta:
"before" is cropped from an already-rendered pool's contact sheets, "after"
is the same variant rebuilt with the code as it stands.

    python tools/probe_pair.py <pool-dir-name> <out.png> <name> [<name> ...]
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.band_probe import corpus, schedule_of  # noqa: E402
from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, BUILDING_TYPE  # noqa: E402
from backend.app.modules.massing.workspace_tools.pool_sheets import COLUMNS, PER_SHEET, TILE  # noqa: E402

from PIL import Image  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()


def main(pool_dir: str, out_path: str, *names: str) -> int:
    pool = ROOT / "runs" / pool_dir
    index = {row["name"]: row["rank"] for row in json.loads(
        (pool / "pool-index.json").read_text(encoding="utf-8"))}
    book = corpus()
    schedule = schedule_of(pool_dir.replace("pool-", ""))
    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    base = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2)))

    befores: list[Image.Image | None] = []
    batch = []
    kept: list[str] = []
    for name in names:
        # "old::new" crops one pool's tile while rebuilding another name.
        # NOTE the band tag in a name is the REQUESTED band (static table in
        # design_space/axes.py) and survives executor changes - the mapping
        # exists for pools whose variant sets differ (dropped sitings etc.),
        # not because names drift. A rebuild failure here usually means the
        # shell fed CR-tainted names, not a retired variant.
        crop_name, _, build_name = name.partition("::")
        name = build_name or crop_name
        rank = index.get(crop_name)
        family = name.split("~")[0].split("^")[0]
        parti = book.get(family)
        if parti is None:
            print(f"skip (no parti): {name}")
            continue
        asked = max((float(op.get("storeys") or 0) for op in parti["ops"]),
                    default=0.0)
        source = rebuild(name, book, site, buildable, axis,
                         max(base, asked * site.floor_height_m),
                         schedule=schedule)
        if source is None:
            print(f"skip (rebuild failed): {name}")
            continue
        if rank is None:
            befores.append(None)
        else:
            slot = (rank - 1) % PER_SHEET
            sheet = Image.open(
                pool / f"pool{(rank - 1) // PER_SHEET + 1:03d}.png")
            col, row = slot % COLUMNS, slot // COLUMNS
            befores.append(sheet.crop((
                col * TILE[0], row * TILE[1],
                (col + 1) * TILE[0], (row + 1) * TILE[1])))
        batch.append((family[:26], source, {"": "AFTER"}))
        kept.append(name)

    after_png = ROOT / "runs" / "_probe_after.png"
    render_masses(batch, after_png,
                  site_ring=list(buildable.exterior.coords),
                  columns=1, tile=TILE, style="massing")
    afters = Image.open(after_png)

    pairs_per_row = 3
    rows = (len(kept) + pairs_per_row - 1) // pairs_per_row
    canvas = Image.new("RGB", (pairs_per_row * TILE[0] * 2, rows * TILE[1]),
                       "white")
    for i in range(len(kept)):
        after = afters.crop((0, i * TILE[1], TILE[0], (i + 1) * TILE[1]))
        x = (i % pairs_per_row) * TILE[0] * 2
        y = (i // pairs_per_row) * TILE[1]
        if befores[i] is not None:
            canvas.paste(befores[i], (x, y))
        canvas.paste(after, (x + TILE[0], y))
    canvas.save(ROOT / "runs" / out_path)
    print(f"{len(kept)} pairs -> runs/{out_path} (left BEFORE, right AFTER)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(*sys.argv[1:]))
