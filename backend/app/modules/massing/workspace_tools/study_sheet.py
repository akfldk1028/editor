"""Evaluated alternatives with one identity across captions and final drawings.

    python tools/study_sheet.py <run> [out-name]

Candidates come from the current O board and the run's jury shortlist, including
BOOK. Current shape and numeric certificate must match the recorded judgement.
"""

from backend.app.modules.massing import paths as _mass_paths
from backend.app.adapters.design_storage.bootstrap import ensure_design_runtime


from backend.app.modules.design.generation import paths as _design_paths

import html
import base64
import json
import os
import hashlib
import sys
from pathlib import Path

ROOT = _mass_paths.workspace_root()

from backend.app.modules.massing.workspace_tools.evaluation_contract import active_rubrics, compatible, stage_contract

from backend.app.modules.design.generation.maas.massv2 import composition as composition_module  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.render import render_masses  # noqa: E402
from backend.app.modules.design.generation.maas.massv2.delivery_gate import assess_delivery  # noqa: E402
from backend.app.modules.massing.workspace_tools.vlm_shortlist import rebuild_seat, seat_context, seat_certificate, shape_id  # noqa: E402

STYLE = """<title>매스 대안 검토</title>
<style>
:root { --ink:#1a1a18; --muted:#84847c; --line:#e0e0da; --bg:#fcfcfa; --pick:#a8501a; }
body { background:var(--bg); color:var(--ink); margin:0;
  font-family:"Inter","Pretendard",-apple-system,"Malgun Gothic",sans-serif;
  line-height:1.6; }
main { max-width:1180px; margin:0 auto; padding:44px 28px 100px; }
header { border-bottom:1px solid var(--ink); padding-bottom:14px; margin-bottom:34px; }
h1 { font-size:19px; font-weight:600; margin:0 0 4px; letter-spacing:-0.01em; }
header p { margin:0; color:var(--muted); font-size:12.5px; }
section { border-bottom:1px solid var(--line); padding:30px 0 34px; }
.head { display:flex; align-items:baseline; gap:12px; flex-wrap:wrap; margin-bottom:6px; }
h2 { font-size:17px; font-weight:600; margin:0; }
.tag { font-size:11px; letter-spacing:0.08em; text-transform:uppercase;
  color:var(--muted); border:1px solid var(--line); padding:2px 8px; border-radius:2px; }
.pick { color:var(--pick); border-color:var(--pick); }
.thesis { font-size:14px; max-width:74ch; margin:0 0 18px; }
.mass { display:grid; grid-template-columns:minmax(280px,1fr) minmax(280px,1.1fr); gap:22px;
  align-items:start; }
img { display:block; width:100%; height:auto; border:1px solid var(--line); background:#fff; }
.facts { font-size:12.5px; color:var(--muted); margin:14px 0 0; }
.facts b { color:var(--ink); font-weight:600; }
.seq { margin:0 0 22px; }
.seq h3 { font-size:11px; letter-spacing:0.1em; text-transform:uppercase;
  color:var(--muted); margin:0 0 8px; font-weight:600; }
footer { margin-top:36px; color:var(--muted); font-size:12px; }
h2.rest { font-size:12px; letter-spacing:0.12em; text-transform:uppercase;
  color:var(--muted); margin:40px 0 10px; font-weight:600; }
.grid { display:grid; grid-template-columns:repeat(auto-fill,minmax(250px,1fr)); gap:0;
  border-left:1px solid var(--line); border-top:1px solid var(--line); }
.grid figure { margin:0; border-right:1px solid var(--line);
  border-bottom:1px solid var(--line); background:#fff; }
.grid img { border:0; }
.grid figcaption { padding:6px 10px 9px; font-size:11px; color:var(--muted);
  border-top:1px solid var(--line); }
@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) { --bg:#141413; --ink:#f0efe9; --line:#33322e;
    --muted:#8a8a84; --pick:#e0a06a; }
}
:root[data-theme="dark"] { --bg:#141413; --ink:#f0efe9; --line:#33322e;
  --muted:#8a8a84; --pick:#e0a06a; }
</style>
"""


def _trimmed(text: str, limit: int = 165) -> str:
    """Cut a thesis at a word, not mid-syllable.

    The tile caption is a fixed width and the sentence was sliced at a
    character count, so a scheme's argument ended "the court is not a". The
    whole sentence is on the page below; the tile carries as much of it as
    fits and says so with an ellipsis.
    """

    text = str(text or "").strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(" ")
    return (cut[:space] if space > limit // 2 else cut).rstrip(",;: ") + "…"


def _uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def _family(name):
    return name if name.startswith("book:") else name.split("~")[0].split("^")[0]


def _candidate_rows(run):
    """Current evaluated O board plus the freshly evaluated run, both supply tracks."""
    entries = {}
    book_only = os.environ.get('BOOK_ONLY') == '1'
    contract = stage_contract(ROOT / "runs" / f"vlm-{run}")
    active = contract["rubric_id"] if contract else None
    board = ROOT / "runs/board/board-key.json"
    if board.exists():
        board_rows = json.loads(board.read_text(encoding="utf-8"))
        if not active and any(row.get('rubric_id') for row in board_rows):
            # A historical run must not reopen legacy comparison rules on a
            # new active board. Replay remains available with its old board.
            active = active_rubrics(ROOT).get('O')
            if not active:
                raise ValueError('New board requires an active evaluation rubric')
        for row in board_rows:
            if book_only and not str(row.get("name", "")).startswith("book:"):
                continue
            if active and not compatible(row, active):
                continue
            if str(row.get("label", "")).startswith("O") and row.get("score") is not None:
                entries[row["name"]] = {**row, "score": float(row["score"])}
    scored = ROOT / "runs" / f"vlm-{run}" / "vlm-shortlist.json"
    if scored.exists():
        for row in json.loads(scored.read_text(encoding="utf-8")):
            if book_only and not str(row.get("name", "")).startswith("book:"):
                continue
            if active and not compatible(row, active):
                continue
            if row.get("anchor") or not row.get("pass"):
                continue
            value = row.get("corrected") if row.get("corrected") is not None else row.get("score")
            if value is not None:
                entries[row["name"]] = {**row, "score": float(value), "round": f"vlm-{run}"}
    return sorted(entries.values(), key=lambda r: (-r["score"], r["name"]))


def _picks(run, book):
    """Compatibility preview; final delivery also checks current geometry."""
    picks, seen = [], set()
    for row in _candidate_rows(run):
        name, family = row["name"], _family(row["name"])
        if family in seen or (not name.startswith("book:") and family not in book):
            continue
        seen.add(family)
        picks.append((name, row["score"]))
        if len(picks) == 3:
            break
    return picks


def _score_matches(row, source):
    return bool(row.get("shape_id")) and row["shape_id"] == shape_id(source)


def _recommendation_identity(row):
    """Bind the comparison hint to the exact scored candidate, not its caption."""
    return {**{key: row.get(key) for key in ('name', 'shape_id', 'certificate_id', 'round', 'score')},
            **({'rubric_id':row['rubric_id']} if row.get('rubric_id') else {})}


def _recommendation_lineages(run, rows, path):
    """Read coordinator-owned ancestry; ARR never imports an agent resolver."""
    if path is None:
        return None  # Historical invocations retain explicit score-order behavior.
    context = json.loads(Path(path).read_text(encoding='utf-8'))
    board = ROOT / 'runs/board/board-key.json'
    expected_sha = hashlib.sha256(board.read_bytes()).hexdigest()
    if (not isinstance(context, dict)
            or context.get('schema') != 'arr.maas.recommendation_context.v1'
            or context.get('run') != run or context.get('board_sha256') != expected_sha
            or not isinstance(context.get('candidates'), list)
            or len(context['candidates']) != len(rows)):
        raise ValueError('Malformed or stale recommendation context; regenerate through the cycle')
    lineages = {}
    for row, entry in zip(rows, context['candidates']):
        if (not isinstance(entry, dict) or entry.get('identity') != _recommendation_identity(row)
                or not isinstance(entry.get('lineage'), str) or not entry['lineage'].strip()
                or row['name'] in lineages):
            raise ValueError('Recommendation ancestry does not match the ranked scored candidates')
        lineages[row['name']] = entry['lineage']
    return lineages


def _comparison_rows(rows, lineages, accepted_lineages):
    """Offer independent sources first; only actually delivered rows reserve a source.

    Deferred descendants remain available for backfill and in the full choice pool.
    Ancestry is not geometric equivalence; exact shape checks remain downstream.
    """
    deferred = []
    for row in rows:
        if lineages is not None and lineages[row['name']] in accepted_lineages:
            deferred.append(row)
        else:
            yield row
    yield from deferred


def _argument(record, reading):
    """Observable composition and a development question, without invented access."""
    if reading.lifted:
        strategy = "들린 상부와 지면 사이의 간격"
        argument = "상부 매스를 들어 지면 가까운 빈 영역과 건물 본체를 구분한다."
        tradeoff = "빈 영역의 연결과 지지부의 간섭을 함께 검토해야 한다. 출입 위치와 이용 방식은 아직 정하지 않았다."
    elif reading.tiers > 1:
        strategy = "높이가 다른 부분의 단계적 결합"
        argument = f"{reading.tiers}개의 높이 단계를 통해 낮은 부분과 높은 부분의 관계를 만든다."
        tradeoff = "각 단의 실내 깊이와 층간 연결을 발전시켜야 한다. 단차만으로 옥외 활동이나 동선이 성립한다고 판단하지 않는다."
    elif reading.parts > 1:
        strategy = "여러 매스와 사이 공간의 관계"
        argument = f"{reading.parts}개 부분의 배열과 간격이 전체 형상을 구성한다."
        tradeoff = "부분 사이 빈 영역이 외부공간으로 쓰일 폭인지, 내부 연결이 어디에 필요한지 후속 평면에서 확인해야 한다."
    else:
        strategy = "하나의 몸체와 비워진 부분의 관계"
        argument = "연속된 몸체의 외곽과 잘려 나간 부분을 하나의 형상으로 읽는다."
        tradeoff = "깊은 내부의 채광과 단면의 점유 가능성을 검토해야 한다. 용도와 실 배치는 확정되지 않았다."
    declared = record.get('design_argument_ko') or {}
    if isinstance(declared, str):
        # One line of Korean is the strategy itself; the three-part form is
        # the fuller shape. Both are authored, so neither may crash the sheet.
        declared = {"title": declared}
    elif not isinstance(declared, dict):
        declared = {}
    return {"strategy": declared.get('title') or strategy,
            "argument": argument,
            "tradeoff": declared.get('tradeoff') or tradeoff,
            "author_intent": declared.get('spatial_strategy') or record.get("formal_principle") or record.get("thesis") or ""}


def _parking_html(block, out):
    evidence = block['site_parking']
    esc = lambda value: html.escape(str(value))
    if evidence.get('status') == 'unavailable':
        return '<h3>마당과 주차 공간</h3><p>주차 공간 진단을 보류했습니다: ' + esc(evidence['reason']) + '</p>'
    from backend.app.modules.design.generation.maas.massv2.site_planning import parking_status_text
    requirement = evidence['requirement']
    required = requirement.get('required_spaces')
    reserve_note = ('건물 전체 투영의 볼록껍질 안 빈 영역을 마당·집 사이 길로 예약한 임시 보수적 가설입니다.'
        if evidence['public_reserve_basis'].startswith('temporary') else '확정 저작의 공공 공간 예약 영역을 우선 적용했습니다.')
    return ('<h3>마당과 주차 공간</h3>'
        f'<p>매스 면적 기준의 조건부 주차: 공공업무시설·장애인주차 적용을 가정할 때 필요 {required if required is not None else "미정"}대 · '
        f'현재 배치 {evidence["provided_spaces"]}대(장애인 {evidence["provided_accessible_spaces"]}대).</p>'
        f'<p>{esc(parking_status_text(evidence))}</p>'
        f'<img src="{_uri(out / block["parking_plan"])}" alt="건물과 마당 예약 영역을 제외한 주차 구획 및 차로 평면">'
        f'<p class="facts">{reserve_note} 예약 면적 {evidence["public_reserve_area_m2"]:,.1f}㎡. '
        f'분리된 잔여 영역 {evidence["component_count"]}곳 중 {evidence["evaluated_component_count"]}곳을 개별 검토했습니다. '
        '필요 대수가 확정되면 모든 영역을 검토한 후 한 곳을 선택합니다. '
        '합산 주차장이나 대지의 최대 주차대수를 계산한 결과는 아닙니다.</p>'
        '<p class="facts">인증서의 매스 면적을 조건부 시설면적으로 사용하며 실제 실별 면적과 법정 주차 산정 제외 항목은 미확정입니다. '
        '확정 출입구·보행 연결·차량 회전 궤적과 실제 용도는 미검증입니다. '
        '배치 수량만으로 법적 적합을 판단하지 않습니다. 상부 투영도 제외해 필로티 아래 주차는 검토하지 않았습니다.</p>'
        f'<p class="facts">조건부 수량 근거: {esc((requirement.get("source") or {}).get("source_appendix") or "기준 미확정")}</p>')


def main(run, out_name="", recommendation_context=None):
    from backend.app.modules.massing.workspace_tools.presentation import write_sequence, drawing_evidence, artifact_stem
    from backend.app.modules.massing.workspace_tools.book_import import _refused, entry_for_judged_row
    from backend.app.modules.design.generation.maas.massv2.site_planning import assess_site_parking, write_site_parking_plan
    rows = _candidate_rows(run)
    lineages = _recommendation_lineages(run, rows, recommendation_context)
    book, site, buildable, axis, base = seat_context()
    out = ROOT / "runs" / (out_name or f"study-{run}")
    out.mkdir(parents=True, exist_ok=True)
    blocks, rejected, seen, shown_shapes = [], [], set(), set()
    from backend.app.modules.massing.workspace_tools.solid_presentation import SolidPresentationRegistry
    solid_forms = SolidPresentationRegistry()
    accepted_lineages = set()
    for row in _comparison_rows(rows, lineages, accepted_lineages):
        name, family = row["name"], _family(row["name"])
        if lineages is None and family in seen:
            continue
        try:
            book_entry = entry_for_judged_row(row) if name.startswith('book:') else None
        except ValueError as error:
            rejected.append({'name': name, 'reason': str(error)})
            continue
        try:
            source, caption = rebuild_seat(name, book, site, buildable, axis, base, book_entry=book_entry)
        except ValueError as error:
            # A seat from an earlier round the executor no longer rebuilds
            # as judged (comp21: a comp19 BOOK seat's floor evidence moved
            # under the seam fix) is set aside like the board's ghosts, not
            # a crash of the whole sheet.
            rejected.append({'name': name, 'reason': f'재건 시 인증 불일치 — 재심사 필요 ({error})'})
            continue
        if source is None or not _score_matches(row, source):
            rejected.append({"name": name, "reason": "재건 불가 또는 심사 당시 형상과 불일치 — 재심사 필요"})
            continue
        cert = seat_certificate(name, source, book, site, book_entry=book_entry)
        if row.get('certificate_id') != cert['certificate_id']:
            rejected.append({'name': name, 'reason': '심사 당시 수치 증명과 불일치 — 재심사 필요'})
            continue
        if cert["ground_m2"] > site.ground_capacity_m2 + 1e-6 or cert["gross_m2"] > site.far_capacity_m2 + 1e-6:
            rejected.append({"name": name, "reason": "현재 수치가 대지의 면적 한도를 초과함"})
            continue
        # The gate also verifies registered frontages in the parcel's coordinate
        # frame. Keep the real LegalSite; a numeric-only wrapper loses that frame.
        # BOOK's gate already reads its own retained storey ruler from source.
        if name.startswith('book:'):
            refusal = _refused(source, site)
        else:
            assessment = assess_delivery(source, site, storey_m=cert['storey_m'])
            refusal = '; '.join(assessment.reasons) if not assessment.accepted else ''
        if refusal:
            rejected.append({"name": name, "reason": refusal})
            continue
        record = book_entry if book_entry is not None else book.get(family, {})
        reading = composition_module.read(source)
        discussion = _argument(record, reading)
        # Captions are explanations, not geometric identity. A ring and a
        # curved bar can share a display title while remaining different
        # evaluated alternatives. Conversely, renaming one mesh adds no option.
        if cert['shape_id'] in shown_shapes:
            rejected.append({'name': name, 'reason': 'The same evaluated geometry is already shown'})
            continue
        form_comparison = solid_forms.find_or_add(name, source)
        if form_comparison.get('duplicate_of'):
            rejected.append({'name': name, 'reason': 'The same occupied 3D form is already shown',
                             'same_form_as': form_comparison['duplicate_of'],
                             'certificate': cert, 'comparison': form_comparison})
            continue
        tile = out / (artifact_stem(name, cert["shape_id"]) + "-mass.png")
        render_masses([(f"대안 {len(blocks) + 1}", source, caption)], tile,
                      site_ring=list(buildable.exterior.coords), columns=1, tile=(900, 800), style="massing")
        sequence = write_sequence(name, source, book=book, site=site,
                                  buildable=buildable, axis=axis, out_dir=out, certificate=cert)
        drawings = drawing_evidence(name, source, buildable, out, storey_m=cert["storey_m"])
        parking_plan = None
        try:
            parking = assess_site_parking(source, site, cert, source_shape_id=shape_id(source))
            parking_plan = write_site_parking_plan(parking, out, stem=artifact_stem(name, cert['shape_id'])).name
        except ValueError as error:
            parking = {'status':'unavailable', 'reason':str(error), 'source_shape_id':cert['shape_id'],
                       'certificate_id':cert['certificate_id'], 'legal_approval':False}
        blocks.append({**row, **cert, **discussion, "tile": tile.name,
                       'solid_presentation': form_comparison,
                       "sequence": sequence.name, "drawings": drawings.name,
                       'site_parking':parking, 'parking_plan':parking_plan,
                       "source_track": "BOOK" if name.startswith("book:") else "저작 문장"})
        seen.add(family)
        shown_shapes.add(cert['shape_id'])
        if lineages is not None:
            accepted_lineages.add(lineages[name])
        if len(blocks) == 3:
            break
    (out / "study.json").write_text(json.dumps({"run": run,
                                               "site": site.evidence() if hasattr(site, 'evidence') else {},
                                               "alternatives": blocks,
                                               "comparison_selection": {
                                                   "policy": "source-ancestry-first-with-shape-backfill.v1" if lineages is not None else "legacy-score-order.v1",
                                                   "context": str(recommendation_context) if recommendation_context is not None else None,
                                                   "ranked_candidates": rows,
                                                   "note": "Scores and the full judged choice pool are unchanged; unshown candidates are not individually revalidated by this sheet."},
                                               "rejected": rejected}, ensure_ascii=False, indent=2), encoding="utf-8")
    if not blocks:
        (out / 'study.html').write_text(
            '<!doctype html><meta charset="utf-8"><title>대안 재심사 필요</title>'
            '<h1>현재 형상과 심사 증명이 일치하는 대안이 없습니다.</h1>'
            '<p>사이클에서 다시 생성·심사한 뒤 대안을 제시합니다. 상세 사유는 study.json에 기록했습니다.</p>',
            encoding='utf-8')
        print("No evaluated candidate has matching current geometry; see study.json. Restage/rejudge through cycle.")
        return 1
    esc = lambda value: html.escape(str(value))
    sections = []
    for i, b in enumerate(blocks):
        storey = f"{b['storey_m']:.2f}m" if b["storey_m"] else "BOOK 원본 면적 증명 기준"
        sections.append(
            f'<section><div class="head"><span class="tag">'
            f'{"심사 우선 검토안" if i == 0 else "비교 대안"} · {esc(b["source_track"])}</span>'
            f'<h2>{i + 1}. {esc(b["strategy"])}</h2></div>'
            f'<p class="thesis">{esc(b["argument"])}</p><p>{esc(b["tradeoff"])}</p>'
            f'<p class="facts"><b>저작 의도</b> {esc(b["author_intent"])}</p>'
            f'<img src="{_uri(out / b["tile"])}" alt="최종 매스 액소노메트릭">'
            f'<p class="facts">연면적 {b["gross_m2"]:,.0f}㎡ · 건폐율 {b["coverage_pct"]:.1f}% · '
            f'용적률 {b["far_pct"]:.1f}% · 심사 {b["score"]:.2f}/5<br>'
            f'층고 {storey} · 수치 근거: {esc(b["floor_area_basis"])}</p>'
            f'<p class="facts">층수 제한 {b["storey_limit"]["max_storeys"]}층 · 보수적 개념 층수 proxy '
            f'{b["storey_limit"]["conceptual_storey_proxy"]} · 실제 설계층수 검증 전</p>'
            f'<h3>평면 점유와 단면</h3><img src="{_uri(out / b["drawings"])}" alt="평면 두 장 및 A-A 단면">'
            '<p class="facts">' +
            ('BOOK 평면과 A-A 단면은 최종 표면 메시를 절단한 형상이다. ' if b['source_track'] == 'BOOK'
             else '평면은 표시 높이의 실제 솔리드 점유 영역이며, 곡면 단면은 표본으로 표시했다. ') +
            'A-A는 대지 중심을 지나는 절단선이다. 실 배치와 출입구는 표현하지 않았다.</p>'
            + _parking_html(b, out) +
            f'<h3>기본 조작 연구와 선택 변형</h3><img src="{_uri(out / b["sequence"])}" alt="선택 변형으로 끝나는 조작 순서">'
            f'<p class="facts">{esc(b["name"])} · 형상 {esc(b["shape_id"])} · 심사 {esc(b.get("round", ""))}</p></section>')
    parcel = float(site.parcel_area_m2)
    datum_note = '지형 기준: 실측 자료 사용' if getattr(site, 'datum_is_measured', False) else '지형 기준: 실측 미확인, 대체 지면 사용'
    document = '<!doctype html><html lang="ko"><meta charset="utf-8">' + STYLE + (
        f'<main><header><h1>매스 대안 검토 · {len(blocks)}안</h1>'
        f'<p>필지 {esc(getattr(site, "pnu", ""))} · 대지 {parcel:,.0f}㎡ · 현재 대지 엔진 면적 한도: '
        f'건폐율 {site.ground_capacity_m2 / parcel * 100:.1f}% / 용적률 {site.far_capacity_m2 / parcel * 100:.1f}%</p>'
        f'<p>{datum_note}</p>'
        '<p>심사를 받은 BOOK과 저작 문장을 함께 비교했다. 첫 안은 심사 점수가 가장 높은 검토안이다. '
        '공모 제출 수준의 평면·동선·구조 및 용도 적합성은 추가 설계와 검토가 필요하다.</p></header>'
        + ''.join(sections) + '<footer>최종 뷰와 시퀀스 마지막 프레임은 같은 선택 변형의 형상이다. '
        '면적 수치는 명시한 모델 및 증명에 따른다. BOOK 중간 형상 기록이 없는 경우 최종 프레임만 제공한다.'
        '</footer></main></html>')
    (out / "study.html").write_text(document, encoding="utf-8")
    print(f"wrote {out / 'study.html'} ({len(blocks)} alternatives, {len(rejected)} rejected)")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(*sys.argv[1:]))
