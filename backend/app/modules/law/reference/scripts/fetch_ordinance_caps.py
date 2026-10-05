"""Derive a land/data/ordinance_overrides/<code>.json from a 도시계획 조례 on law.go.kr.

The national 시행령 (§84/§85) only sets the *maximum* a local ordinance may
choose; the number that binds a parcel is the ordinance's. Seoul's 도시계획 조례
§44/§48 puts 일반상업지역 at 60 % / 800 % where the 시행령 allows 80 % / 1300 %,
and until 2026-09-10 the calculator answered with the 시행령 ceiling.

    python law/scripts/fetch_ordinance_caps.py 11    "서울특별시 도시계획 조례"
    python law/scripts/fetch_ordinance_caps.py 41150 "의정부시 도시계획 조례"
    python law/scripts/fetch_ordinance_caps.py 11 "서울특별시 도시계획 조례" --dry-run

<code> is the 2-digit 시도 code (ordinance applies city-wide, e.g. 서울 11) or the
5-digit 시군구 code (a 시/군 ordinance, e.g. 의정부 41150); the calculator layers
시도 then 시군구. Every value carries its article and the ordinance's ID /
시행일자, and the file records when it was fetched. Re-run to refresh.
"""
from __future__ import annotations

from backend.app.modules.design.generation import paths as _design_paths

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

HERE = _design_paths.package_root('law/scripts')
BACKEND = HERE.parent.parent
sys.path.insert(0, str(BACKEND))

ZONES = [
    "제1종전용주거지역", "제2종전용주거지역", "제1종일반주거지역", "제2종일반주거지역", "제3종일반주거지역",
    "준주거지역", "중심상업지역", "일반상업지역", "근린상업지역", "유통상업지역",
    "전용공업지역", "일반공업지역", "준공업지역", "보전녹지지역", "생산녹지지역", "자연녹지지역",
]
BCR_TITLE = re.compile(r"용도지역\s*안?에서의\s*건폐율")
FAR_TITLE = re.compile(r"용도지역\s*안?에서의\s*용적률")


def api(url: str) -> dict:
    with urllib.request.urlopen(url, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def find_ordinance(oc: str, name: str) -> dict:
    """Exact-name match, paging through the search (a 시 name also matches every
    구 ordinance, and '서울특별시 건축 조례' sits behind 25 구 entries)."""
    seen: list[str] = []
    for page in (1, 2, 3, 4):
        d = api(f"https://www.law.go.kr/DRF/lawSearch.do?OC={oc}&target=ordin&type=JSON"
                f"&query={urllib.parse.quote(name)}&display=100&page={page}")
        items = d.get("OrdinSearch", {}).get("law", [])
        items = [items] if isinstance(items, dict) else items
        if not items:
            break
        exact = [x for x in items if x.get("자치법규명") == name]
        if exact:
            exact.sort(key=lambda x: x.get("시행일자", ""), reverse=True)
            return exact[0]
        seen.extend(x.get("자치법규명") for x in items[:8])
    raise SystemExit(f"ordinance not found: {name!r}; candidates: {seen[:8]}")


def fetch_articles(oc: str, ordinance_id: str) -> tuple[dict, list[dict]]:
    d = api(f"https://www.law.go.kr/DRF/lawService.do?OC={oc}&target=ordin&type=JSON&ID={ordinance_id}")
    law = d.get("LawService") or d
    units = law["조문"]["조"]
    units = [units] if isinstance(units, dict) else units
    return law.get("자치법규기본정보", {}), units


def _num(text: str) -> int:
    text = text.replace(",", "").replace(" ", "")
    text = text.replace("천", "000") if re.fullmatch(r"\d천", text) else text
    return int(text)


def parse_caps(content: str) -> dict[str, dict]:
    """'8. 일반상업지역: 800퍼센트(단, 서울도심: 600퍼센트)' -> {'일반상업지역': {'pct': 800, 'note': '서울도심: 600퍼센트'}}"""
    text = content.replace("\n", " ")
    out: dict[str, dict] = {}
    for zone in ZONES:
        m = re.search(rf"{re.escape(zone)}\s*[:：]?\s*([\d,]+천?)\s*퍼센트\s*(?:이하)?\s*(?:\((단,?[^)]*)\))?", text)
        if m:
            out[zone] = {"pct": _num(m.group(1)), "note": (m.group(2) or "").strip() or None}
    return out


def article_no(unit: dict) -> str:
    raw = unit.get("조문번호")
    raw = raw[0] if isinstance(raw, list) else str(raw or "")
    raw = raw.strip()
    if raw.isdigit() and len(raw) == 6:          # '004800' -> 제48조, '004503' -> 제45조의3
        main, branch = int(raw[:4]), int(raw[4:])
        return f"제{main}조" + (f"의{branch}" if branch else "")
    return f"제{raw}조"


def _annex_text(unit: dict) -> str:
    flat: list[str] = []

    def walk(x):
        if isinstance(x, list):
            for y in x:
                walk(y)
        elif x is not None:
            flat.append(str(x))
    walk(unit.get("별표내용"))
    text = re.sub(r"[│┌┬┐├┼┤└┴┘─┃]+", " ", "\n".join(flat))
    return "\n".join(re.sub(r"\s{2,}", " ", l).strip() for l in text.splitlines())


# Curated readings of the tables that the API returns only as wrapped text.
# Keyed by ordinance ID; every number is re-checked against the fetched text
# at run time, so a re-issued ordinance that changes a value fails loudly.
_PARKING_CURATED = {
    "2000351": {  # 서울특별시 주차장 설치 및 관리 조례
        "article": "제20조·별표 2",
        # 장애인전용주차구획: 조례 제25조제1항 (시행령 별표 1 비고 10의 2~4 % 위임). 10대 미만 제외.
        "accessible": {"ratio_pct": 3, "min_cars": 10, "article": "제25조제1항",
                       "verify": "주차대수의 3퍼센트 이상을 장애인전용주차구획으로"},
        "rows": [
            {"uses": ["위락시설"], "m2_per_car": 67},
            {"uses": ["문화 및 집회시설", "종교시설", "판매시설", "운수시설", "의료시설", "운동시설", "업무시설"], "m2_per_car": 100,
             "note": "관람장·옥외수영장·오피스텔 제외; 공공업무시설은 200"},
            {"uses": ["공공업무시설"], "m2_per_car": 200},
            {"uses": ["제1종 근린생활시설", "제2종 근린생활시설", "숙박시설"], "m2_per_car": 134},
            {"uses": ["단독주택"], "rule": "시설면적 50㎡ 초과 150㎡ 이하 1대; 150㎡ 초과 1+(시설면적-150)/100대"},
            {"uses": ["다가구주택", "공동주택", "오피스텔"], "rule": "주택건설기준 등에 관한 규정 제27조제1항"},
            {"uses": ["수련시설", "공장", "발전시설"], "m2_per_car": 233},
            {"uses": ["창고시설"], "m2_per_car": 267},
            {"uses": ["방송통신시설 중 데이터센터"], "m2_per_car": 400},
            {"uses": ["학생용 기숙사"], "m2_per_car": 400},
            {"uses": ["학교시설"], "m2_per_car": 250},
            {"uses": ["그 밖의 건축물"], "m2_per_car": 200},
        ],
        "restricted": {
            "article": "제21조·별표 3",
            "rule": "주차장설치제한지역(상업·준주거)에서는 별표 3이 최고한도. 교통약자·긴급차·화물 구획 1대 이상은 별도",
            "rows": [
                {"uses": ["위락시설"], "m2_per_car_max": 134},
                {"uses": ["문화 및 집회시설", "종교시설", "판매시설", "운수시설", "의료시설", "운동시설", "업무시설"], "m2_per_car_max": 122},
                {"uses": ["국가 및 지방자치단체의 청사"], "m2_per_car_max": 200},
                {"uses": ["제1종 근린생활시설", "제2종 근린생활시설", "숙박시설"], "m2_per_car_max": 268},
                {"uses": ["수련시설", "공장", "발전시설"], "m2_per_car_max": 466},
                {"uses": ["창고시설"], "m2_per_car_max": 534},
                {"uses": ["기타 건축물"], "m2_per_car_max": 400},
            ],
            # 별표 3 비고 1: 상업·준주거지역 안에서, 도로로 둘러싸인 구역 (경계 도로에 접한 대지 포함)
            "districts": [
                {"name": "4대문 주변지역", "sigungu": ["11110", "11140"], "boundary": "사직로ㆍ율곡로ㆍ종로ㆍ난계로ㆍ퇴계로ㆍ통일로"},
                {"name": "신촌지역", "sigungu": ["11410", "11440"], "boundary": "경의선철도ㆍ이화여대길ㆍ대흥로ㆍ구 용산선철도ㆍ양화로ㆍ연희로"},
                {"name": "영등포지역", "sigungu": ["11560"], "boundary": "여의도 및 경인로ㆍ도림로ㆍ선유로ㆍ노들로"},
                {"name": "강남ㆍ서초지역", "sigungu": ["11680", "11650"], "boundary": "반포대로ㆍ올림픽대로ㆍ분당수서로ㆍ남부순환로"},
                {"name": "잠실지역", "sigungu": ["11710"], "boundary": "올림픽로ㆍ석촌호수로ㆍ삼학사로ㆍ잠실로ㆍ송파대로ㆍ신천로ㆍ오금로ㆍ위례성대로ㆍ백제고분로"},
                {"name": "천호지역", "sigungu": ["11740"], "boundary": "올림픽로ㆍ상암로ㆍ양재대로ㆍ풍성로"},
                {"name": "청량리지역", "sigungu": ["11230"], "boundary": "제기로ㆍ전농로ㆍ서울시립대로ㆍ천호대로ㆍ정릉천"},
                {"name": "용산ㆍ마포지역", "sigungu": ["11170", "11440"], "boundary": "강변북로ㆍ마포대로ㆍ충정로ㆍ통일로ㆍ한강대로"},
                {"name": "미아지역", "sigungu": ["11305"], "boundary": "도봉로ㆍ오현로ㆍ오패산로ㆍ정릉로ㆍ삼양로ㆍ솔샘로"},
                {"name": "목동지역", "sigungu": ["11470"], "boundary": "목동동로ㆍ목동서로ㆍ안양천로"},
            ],
        },
    },
}


_PARKING_CURATED["2141334"] = {  # 의정부시 주차장 설치 및 관리 조례 별표 3 (첨부 HWP)
    "accessible": {"ratio_pct": 3, "min_cars": 10, "article": "별표 3 비고 2",
                   "verify": "3퍼센트를 장애인전용주차구획으로"},
    "rows": [
        {"uses": ["위락시설"], "m2_per_car": 70},
        {"uses": ["문화 및 집회시설", "종교시설", "판매시설", "운수시설", "의료시설", "운동시설", "업무시설", "방송통신시설 중 방송국", "장례식장"], "m2_per_car": 100},
        {"uses": ["제1종 근린생활시설", "제2종 근린생활시설", "숙박시설"], "m2_per_car": 134, "note": "생활숙박시설은 호실당 1대"},
        {"uses": ["단독주택"], "rule": "시설면적 50㎡ 초과 134㎡ 이하 1대; 134㎡ 초과 1+(시설면적-134)/85대", "tier": {"first_max_m2": 134, "step_m2": 85, "under_50_divisor_m2": 85}},  # 별표 3 비고 1: 50㎡ 이하는 85㎡로 나눈 대수
        {"uses": ["다가구주택"], "rule": "주택건설기준 등에 관한 규정 제27조제1항"},
        {"uses": ["공동주택", "오피스텔"], "rule": "전용면적 합계 기준 85㎡ 이하 70㎡당 1대, 85㎡ 초과 65㎡당 1대; 세대(호실)당 1대에 미달하면 세대당 1대"},
        {"uses": ["수련시설", "공장", "발전시설"], "m2_per_car": 350},
        {"uses": ["창고시설"], "m2_per_car": 350},
        {"uses": ["기타 건축물"], "m2_per_car": 250},
    ],
    "restricted": None,
}


def _hwp_text(url: str) -> str:
    """Text of a law.go.kr attachment: hwpx (zip/xml) or HWP 5.0 (OLE, zlib body)."""
    import io
    import re as _re
    import urllib.request as _ur
    import zipfile
    import zlib
    import struct
    req = _ur.Request(url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.law.go.kr/"})
    data = _ur.urlopen(req, timeout=60).read()
    if data[:2] == b"PK":
        z = zipfile.ZipFile(io.BytesIO(data))
        xml = b"".join(z.read(n) for n in z.namelist() if n.startswith("Contents/section"))
        return _re.sub(r"\s+", " ", _re.sub(r"<[^>]+>", " ", xml.decode("utf-8", "replace")))
    if data[:4] == b"\xd0\xcf\x11\xe0":
        import olefile
        ole = olefile.OleFileIO(io.BytesIO(data))
        flags = struct.unpack("<I", ole.openstream("FileHeader").read()[36:40])[0]
        out = []
        for st in ole.listdir():
            if st[0] != "BodyText":
                continue
            body = ole.openstream(st).read()
            if flags & 1:
                body = zlib.decompress(body, -15)
            i = 0
            while i + 4 <= len(body):
                h = struct.unpack("<I", body[i:i + 4])[0]
                tag, size = h & 0x3FF, (h >> 20) & 0xFFF
                i += 4
                if size == 0xFFF:
                    size = struct.unpack("<I", body[i:i + 4])[0]
                    i += 4
                if tag == 67:
                    out.append(_re.sub(r"[\x00-\x1f]", " ", body[i:i + size].decode("utf-16le", "ignore")))
                i += size
        return _re.sub(r"\s+", " ", " ".join(out))
    return ""


def fetch_parking(oc: str, name: str) -> dict | None:
    hit = find_ordinance(oc, name)
    oid = str(hit["자치법규ID"])
    d = api(f"https://www.law.go.kr/DRF/lawService.do?OC={oc}&target=ordin&type=JSON&ID={oid}")
    law = d.get("LawService") or d
    info = law.get("자치법규기본정보", {})
    annexes: list[dict] = []
    # Seoul's JSON has 별표단위 at the top level; 의정부's nests it under 별표.
    raw_annex = law.get("별표단위") or (law.get("별표") or {}).get("별표단위") or []
    for b in ([raw_annex] if isinstance(raw_annex, dict) else raw_annex):
        if isinstance(b, dict) and "별표" in b:
            annexes.extend([b["별표"]] if isinstance(b["별표"], dict) else b["별표"])
        elif isinstance(b, dict):
            annexes.append(b)
    # 별표 and 별지서식 share the 별표번호 sequence ('0003' is both 설치제한 별표 and
    # 가족배려주차장 서식), so key by position + kind + number, never by number alone.
    texts = {f"{i}:{x.get('별표구분') or ''}:{x.get('별표번호') or ''}": _annex_text(x)
             for i, x in enumerate(annexes) if x.get("별표내용")}
    # 자치법규 often carry the 별표 only as an attached HWP/HWPX (의정부). Fetch and
    # read those so the curated values can still be verified against the text.
    for i, x in enumerate(annexes):
        link = x.get("별표첨부파일명") or ""
        if not x.get("별표내용") and link.startswith("http") and "설치기준" in str(x.get("별표제목") or ""):
            try:
                texts[f"{i}:attach:{x.get('별표번호') or ''}"] = _hwp_text(link)
            except Exception as exc:  # keep going: verification below reports the gap
                print(f"  (attachment unreadable: {exc})")
    out: dict = {"ordinance": {"name": name, "id": oid, "effective": info.get("시행일자") or hit.get("시행일자")},
                 "annexes_found": sorted(texts)}
    cur = _PARKING_CURATED.get(oid)
    if cur:
        alltext = "\n".join(texts.values())
        bad = [r for r in cur["rows"] if r.get("m2_per_car") and f"{r['m2_per_car']}㎡당" not in alltext]
        if cur.get("restricted"):
            bad += [r for r in cur["restricted"]["rows"] if f"{r['m2_per_car_max']}㎡당" not in alltext]
        if bad:
            raise SystemExit(f"{name} (ID {oid}): curated parking values not found in fetched 별표 text: {bad[:3]} - ordinance changed, re-review")
        out.update({"article": cur.get("article", "부설주차장 설치기준 별표"), "rows": cur["rows"],
                    "restricted": cur.get("restricted"), "verified_against_text": True,
                    "source_kind": "attachment" if any(k.split(":")[1] == "attach" for k in texts) else "api"})
        if cur.get("accessible"):
            # The 장애인전용주차구획 ratio sits in a 조문 (서울 제25조) or an annex 비고 (의정부);
            # check the curated sentence against both, whitespace-insensitive.
            jos = (law.get("조문") or {}).get("조") or []
            article_text = "\n".join(str(j.get("조내용") or "") for j in ([jos] if isinstance(jos, dict) else jos))
            if re.sub(r"\s+", "", cur["accessible"]["verify"]) not in re.sub(r"\s+", "", alltext + article_text):
                raise SystemExit(f"{name} (ID {oid}): accessible-parking sentence not found: {cur['accessible']['verify']!r} - ordinance changed, re-review")
            out["accessible"] = {k: v for k, v in cur["accessible"].items() if k != "verify"}
    elif texts:
        out["raw_annex_text"] = {k: v[:4000] for k, v in texts.items()}
        out["needs_review"] = "별표 text fetched but no curated reading for this ordinance id"
    else:
        out["needs_review"] = "별표 not exposed by the API (attached file only) - use a reviewed structured seed or the national table"
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("code", help="2-digit 시도 or 5-digit 시군구 code")
    ap.add_argument("name", help="ordinance name as on law.go.kr, e.g. '서울특별시 도시계획 조례'")
    ap.add_argument("--oc", default=os.getenv("LAW_API_OC") or os.getenv("LAW_OC") or "hanvit4303")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--building-ordinance", default="",
                    help="the city's 건축 조례 name (default: '<city> 건축 조례'); its 조경 tiers go to common.landscaping")
    a = ap.parse_args()

    hit = find_ordinance(a.oc, a.name)
    ordinance_id = str(hit["자치법규ID"])
    info, units = fetch_articles(a.oc, ordinance_id)
    bcr = far = None
    for u in units:
        title = str(u.get("조제목") or "")
        body = str(u.get("조내용") or "")
        if BCR_TITLE.search(title) and bcr is None:
            bcr = (article_no(u), parse_caps(body))
        elif FAR_TITLE.search(title) and far is None:
            far = (article_no(u), parse_caps(body))
    if not bcr or not far:
        raise SystemExit(f"could not find both 건폐율/용적률 articles (bcr={bool(bcr)}, far={bool(far)})")

    overrides: dict[str, dict] = {}
    for zone in ZONES:
        b, f = bcr[1].get(zone), far[1].get(zone)
        if not b and not f:
            continue
        row: dict = {}
        if b:
            row["bcr_default"] = b["pct"]
            row["bcr_article"] = f"{a.name} {bcr[0]}" + (f" ({b['note']})" if b["note"] else "")
        if f:
            row["far_default"] = f["pct"]
            row["far_article"] = f"{a.name} {far[0]}" + (f" ({f['note']})" if f["note"] else "")
        overrides[zone] = row

    # 건축 조례: 조경 tiers (건축법 §42 -> 조례). Both Seoul (§24) and 의정부 (§29) tier by
    # 연면적 (2,000m2+ 15 %, 1,000-2,000 10 %, under 1,000 5 %), not by zone.
    common: dict = {}
    b_name = a.building_ordinance or a.name.replace("도시계획 조례", "건축 조례")
    try:
        b_hit = find_ordinance(a.oc, b_name)
        b_info, b_units = fetch_articles(a.oc, str(b_hit["자치법규ID"]))
        for u in b_units:
            title = str(u.get("조제목") or "")
            if "조경" in title and "대지" in title:
                body = str(u.get("조내용") or "").replace("\n", " ")
                tiers = []
                for m in re.finditer(r"연면적[^\d]{0,40}?([\d,천]+)\s*제곱미터\s*이상(?:\s*([\d,천]+)\s*제곱미터\s*미만)?[^:：]*[:：]\s*대지면적의\s*([\d]+)\s*퍼센트", body):
                    tiers.append({"min_floor_area_m2": _num(m.group(1)), "min_pct": int(m.group(3))})
                m = re.search(r"연면적[^\d]{0,40}?([\d,천]+)\s*제곱미터\s*미만[^:：]*[:：]\s*대지면적의\s*([\d]+)\s*퍼센트", body)
                if m:
                    tiers.append({"min_floor_area_m2": 0, "max_floor_area_m2": _num(m.group(1)), "min_pct": int(m.group(2))})
                if tiers:
                    tiers.sort(key=lambda t: -t["min_floor_area_m2"])
                    common["landscaping"] = {
                        "threshold_m2": 200, "tiers": tiers,
                        "article": f"{b_name} {article_no(u)}",
                        "ordinance": {"name": b_name, "id": str(b_hit["자치법규ID"]), "effective": b_info.get("시행일자") or b_hit.get("시행일자")},
                    }
                break
        print(f"{b_name}: landscaping tiers {common.get('landscaping', {}).get('tiers')}")
    except SystemExit as exc:
        print(f"(building ordinance not resolved: {exc})")

    # 주차장 조례: 부설주차장 설치기준 별표 (주차장법 §19 -> 시행령 §6 별표1 -> 조례 강화) and,
    # for Seoul, the 설치제한지역 cap table (별표3) with the districts it covers.
    p_name = a.name.replace("도시계획 조례", "주차장 설치 및 관리 조례")
    try:
        parking = fetch_parking(a.oc, p_name)
        if parking:
            common["parking"] = parking
            print(f"{p_name}: parking rows {len(parking.get('rows', []))}, restricted rows {len((parking.get('restricted') or {}).get('rows', []))}")
    except SystemExit as exc:
        print(f"(parking ordinance not resolved: {exc})")

    doc = {
        "__comment": f"{a.name} 용도지역별 건폐율·용적률 (law.go.kr 자치법규 API에서 생성; 손으로 고치지 말고 fetch_ordinance_caps.py를 다시 돌릴 것)",
        "code": a.code,
        "level": "sido" if len(a.code) == 2 else "sigungu",
        "sigungu_code": a.code,
        "sigungu_name": a.name.replace(" 도시계획 조례", ""),
        "ordinance": {"name": a.name, "id": ordinance_id, "effective": info.get("시행일자") or hit.get("시행일자"),
                      "promulgated": info.get("공포일자"), "no": info.get("공포번호"),
                      "bcr_article": bcr[0], "far_article": far[0]},
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "overrides": overrides,
        "common": common,
    }
    print(f"{a.name} (ID {ordinance_id}, 시행 {doc['ordinance']['effective']}): {bcr[0]} 건폐율 {len(bcr[1])} zones, {far[0]} 용적률 {len(far[1])} zones")
    for zone, row in overrides.items():
        print(f"  {zone:12s} 건폐율 {row.get('bcr_default'):>4}%  용적률 {row.get('far_default'):>5}%")
    if a.dry_run:
        return
    from backend.app.modules.land.reference import config
    out = Path(config.ORDINANCE_DIR) / f"{a.code}.json"
    existing = json.loads(out.read_text(encoding="utf-8")) if out.exists() else {}
    keep = {k: v for k, v in (existing.get("overrides") or {}).items() if k not in overrides}
    if keep:  # hand-reviewed rows for zones the ordinance article does not name
        doc["overrides"].update(keep)
        doc["__comment_kept"] = f"kept {len(keep)} zone rows not covered by the fetched articles"
    out.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
