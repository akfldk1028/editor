"""Did the surgery help? Render the same sentence before and after, blind.

The canon rewrote ten sentences on an argument. An argument is not evidence:
the pre-surgery corpus is read back out of git, both versions of each sentence
are rebuilt down the identical path, and the pair goes to a judge that is not
told which is which.

    python tools/ab_surgery.py <commit-before>
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import json
import subprocess
import sys
from pathlib import Path

from backend.app.modules.massing.workspace_tools.finalists import PNU, rebuild, scheme_of, BUILDING_TYPE  # noqa: E402

from backend.app.modules.design.generation.maas.massv2.legal import load_legal_site  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.siting import site_open_side_direction  # noqa: E402

ROOT = _mass_paths.workspace_root()
REPO_PREFIX = "ARR/backend/tmp_mass_check/_massv2/inputs"
TOUCHED = [
    ("gen-rel-a.json", "us_hearst_tower_proud_of_the_shell"),
    ("gen-llm.json", "a_low_branch"),
    ("gen-korea.json", "kr_hansol_gym_is_its_own_body"),
    ("gen-llm.json", "c_torsion_field"),
    ("gen-onemove.json", "via57_one_corner_drawn_up"),
    ("gen-llm.json", "b_moyeo_teulda"),
    ("gen-rel-a.json", "ca_ocad_sharp_centre_tabletop"),
    ("gen-onemove.json", "milstein_a_plate_past_its_supports"),
    ("gen-oma.json", "oma_lab_city_saclay"),
    ("gen-f.json", "f_gongjung_jungjeong"),
]


def corpus_at(commit: str, filename: str) -> dict:
    blob = subprocess.run(
        ["git", "show", f"{commit}:{REPO_PREFIX}/{filename}"],
        cwd="D:/Data/25_ACE", capture_output=True, text=True, encoding="utf-8",
    )
    if blob.returncode != 0:
        raise RuntimeError(blob.stderr[:200])
    return {s["name"]: s for s in json.loads(blob.stdout)["schemes"]}


def main(before: str) -> int:
    out = ROOT / "runs" / "ab-surgery"
    out.mkdir(parents=True, exist_ok=True)
    now = {}
    for p in sorted((ROOT / "inputs").glob("gen-*.json")):
        for s in json.loads(p.read_text(encoding="utf-8"))["schemes"]:
            now[s["name"]] = s

    site = load_legal_site(PNU, building_type=BUILDING_TYPE)
    buildable = site.plan_at(0.0)
    axis = site_open_side_direction(site) or (1.0, 0.0)
    height = site.floor_height_m * max(
        1, int(site.far_capacity_m2 // max(1.0, site.ground_capacity_m2))
    )
    ring = [(float(x), float(y)) for x, y in site.site_local_utm.exterior.coords[:-1]]

    cards, pairs, key = [], [], []
    index = 0
    for order, (filename, name) in enumerate(TOUCHED):
        old = corpus_at(before, filename)
        versions = [("before", old), ("after", now)]
        # Alternate which side leads so the judge cannot learn the position.
        if order % 2:
            versions.reverse()
        ids = []
        for label, corpus in versions:
            src = rebuild(name, corpus, site, buildable, axis, height)
            if src is None:
                ids = []
                break
            index += 1
            cid = f"alt-{index:02d}"
            png = out / f"{cid}.png"
            render_masses(
                [(name, src, {"thesis": corpus[name].get("formal_principle", "")})],
                png, site_ring=ring, columns=1, tile=(900, 760),
            )
            cards.append({"id": cid, "png": str(png.resolve()), "scheme": name,
                          "principle": corpus[name].get("formal_principle", "")})
            ids.append((cid, label))
        if len(ids) != 2:
            print(f"  skipped {name} (one side failed to rebuild)")
            continue
        pairs.append([ids[0][0], ids[1][0]])
        key.append({"sentence": name, "pair": [ids[0][0], ids[1][0]],
                    "labels": [ids[0][1], ids[1][1]]})
    (out / "vlm-manifest.json").write_text(
        json.dumps({"run": "ab-surgery", "cards": cards}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "vlm-pairs.json").write_text(
        json.dumps({"run": "ab-surgery", "pairs": pairs}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    (out / "answer-key.json").write_text(
        json.dumps({"key": key}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"{len(pairs)} before/after pairs -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
