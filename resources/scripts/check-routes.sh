#!/usr/bin/env bash
# Every route the product exposes, exercised through the one origin the shell
# serves from. A route is only "ok" if it answers the way its contract says.
B=http://127.0.0.1:5173
pass=0; fail=0

check() { # name expected actual
  if [ "$2" = "$3" ]; then printf "  \033[32mok\033[0m   %-46s %s\n" "$1" "$3"; pass=$((pass+1));
  else printf "  \033[31mFAIL\033[0m %-46s got %s want %s\n" "$1" "$3" "$2"; fail=$((fail+1)); fi
}
code() { curl -s -o /dev/null -w '%{http_code}' --max-time 240 "$@"; }

echo "=== shell pages (one origin, path-addressed) ==="
for p in / /dwg /planm /editor /editor/scenes; do
  check "GET $p" 200 "$(code "$B$p")"
done

echo
echo "=== editor API (proxied under its base path) ==="
check "GET /editor/api/health" 200 "$(code "$B/editor/api/health")"
check "GET /editor/api/scenes" 200 "$(code "$B/editor/api/scenes")"

echo
echo "=== DWG service ==="
check "GET /api/health" 200 "$(code "$B/api/health")"

echo
echo "=== PLANM backend: create + poll ==="
RID=$(curl -s -X POST "$B/api/v1/planm/runs" -H 'content-type: application/json' --max-time 900 \
  -d '{"contract_version":"planm-run-create/v1","mass":{"project_id":"route-check","floors":2,
      "footprint_polygon":[[0,0],[30,0],[30,12],[0,12]],
      "site_edges":[{"edge_index":0,"kind":"street"}],
      "access_candidates":[{"edge_index":0,"position":0.5}],
      "use_mix":{"office":1.0}}}' \
  | python -c "import json,sys; print(json.load(sys.stdin)['run_id'])")
echo "  run_id: $RID"

for _ in $(seq 1 90); do
  S=$(curl -s "$B/api/v1/planm/runs/$RID" --max-time 60 | python -c "import json,sys; print(json.load(sys.stdin)['status'])")
  [ "$S" = "delivered" ] || [ "$S" = "blocked" ] || [ "$S" = "approved" ] && break
  sleep 10
done
check "GET  /runs/{id}  (status=$S)" delivered "$S"
check "GET  /runs/{id}/alternatives" 200 "$(code "$B/api/v1/planm/runs/$RID/alternatives")"

ALT=$(curl -s "$B/api/v1/planm/runs/$RID/alternatives" --max-time 120 \
  | python -c "import json,sys; print(json.load(sys.stdin)['accepted_alternative_ids'][0])")
check "GET  /alternatives/{alt}/preview" 200 "$(code "$B/api/v1/planm/runs/$RID/alternatives/$ALT/preview")"
check "POST /runs/{id}/execute" 200 "$(code -X POST "$B/api/v1/planm/runs/$RID/execute")"
check "POST /runs/{id}/approval" 200 "$(code -X POST "$B/api/v1/planm/runs/$RID/approval" \
  -H 'content-type: application/json' -d "{\"contract_version\":\"planm-approval/v1\",\"alternative_id\":\"$ALT\"}")"
check "GET  /runs/{id}/artifacts/..." 200 "$(code "$B/api/v1/planm/runs/$RID/artifacts/planm-manifest.json")"
check "POST /runs/{id}/dwg/handoff" 201 "$(code -X POST "$B/api/v1/planm/runs/$RID/dwg/handoff")"

echo
echo "=== the bridge ==="
PUB=$(curl -s -X POST "$B/api/v1/planm/runs/$RID/pascal" -H 'content-type: application/json' \
  -d '{"contract_version":"planm-pascal-publish/v1"}' --max-time 900)
echo "$PUB" | python -c "
import json,sys
d=json.load(sys.stdin)
print('  published :', d.get('published'))
print('  totals    :', d.get('totals'))
print('  editor_url:', d.get('editor_url'))
print('  warnings  :', len(d.get('conversion_warnings',[])), 'conversion,', len(d.get('unplaced_openings',[])), 'unplaced')
open('scene_url.tmp','w').write(d.get('editor_url') or '')
"
SCENE=$(cat scene_url.tmp 2>/dev/null); rm -f scene_url.tmp
[ -n "$SCENE" ] && check "GET  published scene" 200 "$(code "$SCENE")"
check "POST /runs/{id}/pascal (dry_run)" 201 "$(code -X POST "$B/api/v1/planm/runs/$RID/pascal" \
  -H 'content-type: application/json' -d '{"contract_version":"planm-pascal-publish/v1","dry_run":true}')"
check "POST /runs/{id}/pascal (plan_only)" 201 "$(code -X POST "$B/api/v1/planm/runs/$RID/pascal" \
  -H 'content-type: application/json' -d '{"contract_version":"planm-pascal-publish/v1","plan_only":true}')"

echo
echo "=== error contracts ==="
check "unknown run -> 404" 404 "$(code "$B/api/v1/planm/runs/$(printf 'f%.0s' {1..32})")"
check "malformed run id -> 404" 404 "$(code "$B/api/v1/planm/runs/nope")"

echo
echo "passed $pass, failed $fail"
exit $([ "$fail" -eq 0 ] && echo 0 || echo 1)
