"""The refusal-trap numbers, derived from their owners instead of remembered.

Every author brief so far carried these values as hand-typed prose - "declare
gaps at 4.4 or better", "reach stops at 0.40" - and the session that mixed up
extract's host-ratio gap with the metre rule showed what a copied number
costs. The rule the user set after that: one owner, derive the rest. The
gates own their thresholds; this tool reads them and prints the author-facing
ledger with each number's derivation beside it, so editing a constant updates
what the next author is told without anyone re-remembering 4.4.

The empirical calibrations (how much the pipeline shaves a declared gap, the
delivered fold inflation) have no code owner - they are measurements - so
they live HERE, once, with their dates, rather than in n briefs.

    python tools/trap_ledger.py            # print the ledger (used by briefs)
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.modules.design.generation import paths as _design_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


import os
import sys
from pathlib import Path


import django  # noqa: E402

ensure_design_runtime()

from backend.app.modules.design.generation.maas.floor_viability import DEFAULT_MINIMUM_CLEAR_DEPTH_M  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.ablation import GAP_IS_A_SPACE_M  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.grammar import MIN_OFFSET_RATIO  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.structure import CANTILEVER_BACKSPAN_RATIO, POTENTIAL_WELL_FLOOR_M
from backend.app.modules.design.generation.maas.source_geometry.ir import MAX_CREASED_PROFILE_POINTS  # noqa: E402

# Measurements, not code: calibrated in-session, dated, owned here alone.
GAP_SHAVE_WORST = 0.39          # 2026-08-30: delivery shaved declared gaps 22-39%
FOLD_DELIVERY_INFLATION = 0.35  # 2026-08-31: authored 5.1 m drop delivered at 6.9 m
CANTILEVER_REACH_MEASURED_OK = 0.28   # 2026-08-27: survived delivery; 0.35 grew to 1.61
CANTILEVER_CEILING_SHARE = 0.65       # of the gate-implied step r/(1+r)


def ledger() -> str:
    gap_declare = GAP_IS_A_SPACE_M / (1.0 - GAP_SHAVE_WORST)
    reach_ceiling = (CANTILEVER_CEILING_SHARE * CANTILEVER_BACKSPAN_RATIO
                     / (1.0 + CANTILEVER_BACKSPAN_RATIO))
    return "\n".join([
        "## 거부 함정 원장 (코드 상수에서 생성 — tools/trap_ledger.py)",
        f"1. 틈(gap)은 **{gap_declare:.1f}m 이상**으로 선언하라 — 게이트 문턱 "
        f"{GAP_IS_A_SPACE_M:.1f}m ÷ (1 − 최악 감쇄 {GAP_SHAVE_WORST:.0%}).",
        "2. rotate와 선언한 gap을 한 문장에 같이 두지 마라 (회전이 틈을 닫는다).",
        "3. `grade`의 toward는 열거형 — \"open\"만 산다.",
        "4. gable은 발자국을 넓혀 선언한 틈을 닫는다 — 틈이 논지면 gable 금지.",
        "5. `extract`의 gap은 **호스트폭 비율** 좌표계다 — 미터 규칙과 혼동 금지.",
        "6. stack으로 밴드가 된 몸에 cantilever는 조용하다.",
        "7. 대지 꽉 찬 몸 위에서 cantilever·stagger 금지 — 일조 봉투가 먹는다.",
        f"8. `cantilever`·`canopy`의 reach 상한 {reach_ceiling:.2f} — 구조 게이트 "
        f"backspan {CANTILEVER_BACKSPAN_RATIO}의 역산 r/(1+r) × {CANTILEVER_CEILING_SHARE}. "
        f"실측 통과값 {CANTILEVER_REACH_MEASURED_OK}.",
        f"9. `fold`의 낙차는 배달에서 +{FOLD_DELIVERY_INFLATION:.0%}까지 부푼 실측 — "
        f"얕게 선언하라. 접힘은 렌더 이음선 상한(점 {MAX_CREASED_PROFILE_POINTS}개 = "
        f"접힘 {(MAX_CREASED_PROFILE_POINTS - 1) // 2}개)까지.",
        f"10. 방은 유효깊이 {DEFAULT_MINIMUM_CLEAR_DEPTH_M}m — 그보다 얇은 판을 원하면 "
        "canopy(방 면제)로 말하라.",
        f"11. 관계·이동 비율의 바닥 {MIN_OFFSET_RATIO} — 그 아래 선언은 침묵 게이트가 "
        "잡는다.",
        f"12. 물리: 퍼텐셜 우물 {POTENTIAL_WELL_FLOOR_M}m 아래는 기각 (눈먼 라운드로 "
        "캘리브레이션).",
    ])


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    print(ledger())
