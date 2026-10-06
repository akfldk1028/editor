# Nationwide 도시계획 조례 caps (offline generator, 2026-10-06)

Writes `land/reference/data/ordinance_overrides/<code>.json` for every jurisdiction.

1. `ordinance_batch.py` — runs `../fetch_ordinance_caps.py` for every 특별·광역시/도의 시·군
   (legal-dong table); former 광주 구 use the (구)광주광역시 ordinance, marked transitional.
2. `ordinance_pass2.py` — the ones it misses: name variants (계획 조례, 도시계획조례, 관리계획
   조례 …), other article titles, caps in a 별표 HWP attachment.
3. `ordinance_rebuild.py` — re-parses every file with one item-aware parser and keeps only
   values inside 국토계획법 시행령 제84조/제85조 ranges (out-of-range parses are dropped;
   서울 11 and 의정부 41150 hand-verified values are kept). Writes `checked` into each file.

Run 2 and 3 with the SiteContext venv: they read HWP with
`agents/SiteContextAgent/sitecontextagent/district_documents.hwp_text` (path inserted at the top
of `ordinance_pass2.py`). Paths in the scripts are this machine's; adjust before re-running.
law.go.kr OC defaults to the account in `fetch_ordinance_caps.py`.
