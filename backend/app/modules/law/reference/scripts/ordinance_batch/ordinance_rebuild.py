"""Rebuild every ordinance file's caps with one parser, checked against the 시행령 ranges.

국토계획법 시행령 제84조(건폐율 최대한도) and 제85조(용적률 범위) bound what an ordinance may
set. A parsed value outside its zone's range is a parse error, not a legal fact: it is
dropped, so the calculator fails closed for that zone instead of using it.
"""
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import ordinance_pass2 as p  # noqa: E402

BCR_MAX = {"제1종전용주거지역": 50, "제2종전용주거지역": 50, "제1종일반주거지역": 60, "제2종일반주거지역": 60,
           "제3종일반주거지역": 50, "준주거지역": 70, "중심상업지역": 90, "일반상업지역": 80, "근린상업지역": 70,
           "유통상업지역": 80, "전용공업지역": 70, "일반공업지역": 70, "준공업지역": 70, "보전녹지지역": 20,
           "생산녹지지역": 20, "자연녹지지역": 20, "보전관리지역": 20, "생산관리지역": 20, "계획관리지역": 40,
           "농림지역": 20, "자연환경보전지역": 20}
FAR_RANGE = {"제1종전용주거지역": (50, 100), "제2종전용주거지역": (50, 150), "제1종일반주거지역": (100, 200),
             "제2종일반주거지역": (100, 250), "제3종일반주거지역": (100, 300), "준주거지역": (200, 500),
             "중심상업지역": (200, 1500), "일반상업지역": (200, 1300), "근린상업지역": (200, 900),
             "유통상업지역": (200, 1100), "전용공업지역": (150, 300), "일반공업지역": (150, 350),
             "준공업지역": (150, 400), "보전녹지지역": (50, 80), "생산녹지지역": (50, 100), "자연녹지지역": (50, 100),
             "보전관리지역": (50, 80), "생산관리지역": (50, 80), "계획관리지역": (50, 100), "농림지역": (50, 80),
             "자연환경보전지역": (50, 80)}
HAND_VERIFIED = {"11", "41150"}  # verified against the text on 2026-09-13; only missing zones are added


def lawful(zone, kind, value):
    if not isinstance(value, int):
        return False
    if kind == "bcr":
        return 5 <= value <= BCR_MAX[zone]
    low, high = FAR_RANGE[zone]
    return low <= value <= high


NUMBER = r"(\d{1,2}천(?:\s*\d{1,3})?|\d{1,2},\d{3}|\d{1,4})"


def to_int(text):
    text = text.replace(",", "").replace(" ", "")
    if "천" in text:
        head, _, tail = text.partition("천")
        return int(head) * 1000 + (int(tail) if tail else 0)
    return int(text)


def item_windows(text):
    """{zone: the text of its list item}. Items run 1., 2., 3. ...; the next item's number is
    often glued to a value ('100분의 402. 제2종…' is 40, then item 2), so it is cut by count."""
    hits = []
    for zone in p.ZONES:
        m = re.search(p.zone_pattern(zone), text)
        if m:
            hits.append((m.start(), m.end(), zone))
    hits.sort()
    first = re.search(r"(\d{1,2})\s*\.\s*$", text[:hits[0][0]]) if hits else None
    number = int(first.group(1)) if first else None
    out = {}
    for index, (_, stop, zone) in enumerate(hits):
        end = hits[index + 1][0] if index + 1 < len(hits) else len(text)
        window = text[stop:end]
        if number is not None:
            # The next item ('2.', or a non-zone item '21.') ends this one, glued or not.
            glued = re.search(re.escape(str(number + 1)) + r"\s*\.(?!\d)", window)
            if glued:
                window = window[:glued.start()]
            number = number + 1 if glued and index + 1 < len(hits) else None
        out[zone] = window[:200]
    return out


def pct_after(text, zone, count, table=False):
    if table:
        m = re.search(p.zone_pattern(zone), text)
        if not m:
            return None
        window = text[m.end():m.end() + 200]
        others = [re.search(p.zone_pattern(z), window) for z in p.ZONES if z != zone]
        window = window[:min((o.start() for o in others if o), default=len(window))]
        found = re.findall(rf"(?<![\d,천]){NUMBER}(?![\d,천])", window)
    else:
        window = item_windows(text).get(zone)
        if window is None:
            return None
        window = re.split(r"[(（]\s*(?:단|다만)", window)[0]  # never take a 단서 exception's figure
        found = [a or b for a, b in re.findall(rf"{NUMBER}\s*(?:퍼센트|%)|100\s*분\s*의\s*{NUMBER}", window)]
    values = [to_int(v) for v in found]
    return values[:count] if len(values) >= count else None


p.pct_after = pct_after
report = {}
for path in sorted(p.OUT.glob("*.json")):
    doc = json.loads(path.read_text(encoding="utf-8"))
    source = doc.get("ordinance") or {}
    comment = str(doc.get("__comment", ""))
    if not source.get("id") or "예시" in comment or "example" in comment.lower():
        continue
    code = path.stem
    try:
        law = p.api(f"https://www.law.go.kr/DRF/lawService.do?OC={p.OC}&target=ordin&type=JSON&ID={source['id']}")
        law = law.get("LawService") or law
        rows, annex = p.caps(law)
    except Exception as exc:
        report[code] = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"}
        print(code, "failed", exc, flush=True)
        continue
    old = doc.get("overrides") or {}
    new, dropped, disagreements = {}, [], []
    for zone in BCR_MAX:
        out = {}
        for kind in ("bcr", "far"):
            key, art = kind + "_default", kind + "_article"
            parsed = rows.get(zone, {}).get(kind)
            before = old.get(zone, {}).get(key)
            if code in HAND_VERIFIED and before is not None:
                out[key], out[art] = before, old[zone].get(art)
                continue
            good_parsed, good_before = lawful(zone, kind, parsed), lawful(zone, kind, before)
            if good_parsed:
                out[key] = parsed
                out[art] = f"{source['name']} {rows[zone][kind + '_article']}"
                if good_before and before != parsed:
                    disagreements.append({"zone": zone, "kind": kind, "fetcher": before, "parser": parsed})
            elif good_before:
                out[key], out[art] = before, old[zone].get(art)
            elif parsed is not None or before is not None:
                dropped.append({"zone": zone, "kind": kind, "fetcher": before, "parser": parsed})
        if out:
            new[zone] = out
    doc["overrides"] = new
    doc.pop("supplemented", None)
    doc["checked"] = {"against": "국토계획법 시행령 제84조 건폐율 최대한도, 제85조 용적률 범위",
                      "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                      "dropped_out_of_range": dropped, "parser_disagreements": disagreements}
    if annex:
        doc["ordinance"]["annex"] = annex
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    full = sum(1 for z in new.values() if "bcr_default" in z and "far_default" in z)
    report[code] = {"status": "ok", "zones_complete": full, "dropped": dropped, "disagree": disagreements}
    print(code, "zones", full, "dropped", len(dropped), "disagree", len(disagreements), flush=True)
Path(__file__).with_name("ordinance_rebuild.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("files", len(report))
