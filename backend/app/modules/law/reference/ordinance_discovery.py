"""Nationwide official ordinance candidates; identity is returned, never guessed."""
from datetime import date
import urllib.parse
import urllib.request
import json


def public_record(value):
    """The official API echoes OC in detail links; strip it before returning/storing."""
    if isinstance(value, dict):
        return {key: public_record(item) for key, item in value.items()}
    if isinstance(value, list):
        return [public_record(item) for item in value]
    if isinstance(value, str) and "oc=" in value.lower() and "?" in value:
        parts = urllib.parse.urlsplit(value)
        query = urllib.parse.urlencode([(key, item) for key, item in urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
                                       if key.lower() not in {"oc", "apikey", "api_key"}])
        return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    return value


def discover_ordinances(query, assessment_date, api_oc, *, max_pages=5, fetch_json=None):
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must contain a jurisdiction or ordinance name")
    when = date.fromisoformat(assessment_date)
    if when.isoformat() != assessment_date:
        raise ValueError("assessment_date must be YYYY-MM-DD")
    if type(max_pages) is not int or not 1 <= max_pages <= 20:
        raise ValueError("max_pages must be 1 to 20")

    def fetch(params):
        url = "https://www.law.go.kr/DRF/lawSearch.do?" + urllib.parse.urlencode({"OC": api_oc, **params})
        with urllib.request.urlopen(url, timeout=30) as response:
            return json.load(response)

    candidates, seen, truncated = [], set(), False
    try:
        for edition_set in (1, 2):
            for page in range(1, max_pages + 1):
                params = {"target": "ordin", "type": "JSON", "query": query.strip(),
                          "nw": edition_set, "display": 100, "page": page}
                payload = (fetch_json or fetch)(params)
                search = payload.get("OrdinSearch")
                if not isinstance(search, dict):
                    raise ValueError("invalid official ordinance response")
                rows = search.get("law", [])
                rows = [rows] if isinstance(rows, dict) else rows
                if not isinstance(rows, list):
                    raise ValueError("invalid ordinance result list")
                for row in rows:
                    effective = str(row.get("시행일자", ""))
                    if len(effective) != 8 or not effective.isdigit():
                        continue
                    try:
                        effective_date = date.fromisoformat(f"{effective[:4]}-{effective[4:6]}-{effective[6:]}")
                    except ValueError:
                        continue
                    if effective_date > when:
                        continue
                    mst = str(row.get("자치법규일련번호") or "")
                    if not mst or mst in seen:
                        continue
                    seen.add(mst)
                    candidates.append({"name": row.get("자치법규명"), "edition_id": mst,
                        "ordinance_id": row.get("자치법규ID"), "effective_date": effective_date.isoformat(),
                        "agency": row.get("지자체명") or row.get("소관부처명"),
                        "source_url": "https://www.law.go.kr/자치법규/" + urllib.parse.quote(str(row.get("자치법규명", "")), safe=""),
                        "official_record": public_record(row), "status": "candidate_not_body_verified"})
                total = search.get("totalCnt")
                ended = not rows or (total is not None and page * 100 >= int(total)) or (total is None and len(rows) < 100)
                if ended:
                    break
            else:
                truncated = True
    except Exception as exc:
        # Never include a request URL carrying OC in errors or stored evidence.
        return {"status": "external_failure", "error_type": type(exc).__name__, "query": query,
                "assessment_date": assessment_date, "partial_candidates": candidates, "coverage_complete": False}
    candidates.sort(key=lambda x: (x["name"] or "", x["effective_date"], x["edition_id"]), reverse=True)
    return {"status": "retrieved", "query": query, "assessment_date": assessment_date,
            "candidates": candidates, "truncated": truncated, "coverage_complete": False,
            "instruction": "Candidates are nationwide source discovery. Match official agency/jurisdiction, then retrieve exact-name clauses and applicable annexes; no authority or permit inferred from a name."}
