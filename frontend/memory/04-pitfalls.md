# Known traps (2026-10-06)

- **"Not the Next.js you know."** `frontend/app/editor/AGENTS.md`: this Next version differs from
  training data — read `node_modules/next/dist/docs/` before using an API you are unsure of.
- **Dead calls.** A client URL with no backend route used to slip through (the `/law` deep
  analysis called a route that did not exist; the land proxy could not stream it). Keep
  `api-surface.test.ts` green and add the proxy path when you add a backend path.
- **Trailing slashes** cause backend 308 redirects; build URLs without them.
- **`NEXT_PUBLIC_*` is inlined at build time**; changing it needs a rebuild, and a remapped port
  can break pages that fetch their own API (see `infra/docker/docker-compose.yml` comment).
- **Running server is a build.** Port 3003 serves `next start`; edits do nothing until rebuilt
  and restarted.
- **Model keys.** A failing OpenAI key in `/settings` is expected locally (no credits); the
  backend uses the local Claude Code login (oauth) for workspace runs.
- **The dev server runs on Turbopack (2026-10-13).** It once broke on `@dwg/contracts` (`./cad.js` not resolved),
  so it ran `--webpack` (first compiles up to 40 s). The dwg files the editor reaches (`apps/workspace/src/public.ts`,
  `packages/contracts/src`) now import by their real `.ts`/`.tsx` extension (dwg tsconfig: `allowImportingTsExtensions`,
  `rewriteRelativeImportExtensions`); a new `./x.js` import in that graph brings the error back.
- **Proxy 404 "Unknown platform/PLANM operation"** is the proxy allowlist, not a missing backend route.
- **CSS edit under `next dev --webpack` drops every stylesheet** in open tabs (page renders unstyled, `styleSheets`
  still 14) until a full reload (seen twice 2026-10-08 editing agent-feed.css). The in-memory agent feed is lost on
  reload, so re-run the flow after the reload rather than trusting the half-styled page.
- **Map selection UX (user, 2026-10-07):** a click selects the whole parcel polygon (fill + outline); never draw
  points/markers/ripples at the click location — it looks wrong. Progress = cursor only; the only overlay on the
  map besides parcels is one info card. A site can be several parcels (합필): Shift+click adds/removes.
- **Naver 지적편집도 is the default cadastral layer (user, 2026-10-09) — do not replace it.** In re-platted districts
  (고산 공공주택지구, 961-3) Naver's lines differ from the Vworld 연속지적도 the parcel outline comes from, so the outline
  looks rotated/shifted against Naver's lines; the Vworld polygon is the registry one (278.4 m2 vs official 279.9).
  A Vworld GroundOverlay replacement was tried and reverted (e15c3115 → f64830f1). The user later rejected
  even an optional toggle as the solution; see the display-only correction below.
- **2026-10-09 user correction: Naver alignment required, NOT a VWorld toggle.** The optional comparison
  was rejected and removed. Do not reintroduce it as a fix.
  Live Chrome at 고산동 961-3 (`4115011200109610003`, NOT 산곡동 `41150113...`) compared actual SVG vertices
  against Naver SDK `fromCoordToOffset`: max error 0.557 px at zoom 18 and 0.500 px at zoom 19 (raster rounding).
  This rules out a several-pixel rendering transform error for that parcel; it does not validate Naver boundary
  coordinates. Naver's documented CadastralLayer API exposes a tiled layer, not per-PNU polygon vertices.
  No arbitrary shifts/rotations were applied. Diagnostic script/screenshots are ignored under
  `test-results/naver-coordinate-diagnostic.cjs`, `naver-coordinate-{0,1}.png`.
  Reference: https://navermaps.github.io/maps.js.ncp/docs/naver.maps.CadastralLayer.html
- **2026-10-09 clarification implemented: keep parcels, fix only our clicked selection display.** Naver engine
  now derives display rings from readable CORS map tiles: `layers/rasterSelection.ts` traces an enclosed region
  and robustly fits its edges, rejecting clipped/leaking/ambiguous contours; `displaySelection.ts` caches only
  display coordinates and handles capture/projection. No parcel-specific PNU, offset or rotation constants.
  Server geometry, picker state, save inputs and 3D still use originals. Bounds changes invalidate pixel data;
  idle/tilesloaded refresh the overlay. A successful detailed contour is retained when zooming out. This is
  raster-derived visual alignment, NOT cadastral geometry. If unreadable/too small/ambiguous, original drawing
  remains (or prior confirmed display contour). Fresh zoom 18 of 961-3 is too small to fit all edges reliably;
  zoom 20 succeeds, and subsequent zoom 19 retains alignment. Do not claim universal precision at every zoom.
  Actual click at 961-3 on Naver verified: outline/fill align, card PNU unchanged, preview geometry byte-equal
  to fetched original, page errors 0. Ignored evidence: `test-results/naver-raster-probe.cjs`,
  `naver-display-selection.png`, `naver-display-selection-zoom.png`. Unit tests cover source immutability,
  missing borders, clipping, internal text and boundary-touching text.
- **Display alignment review fixes:** drawing alone had left hit-testing in source space: the right-hand visible
  strip of 961-3 selected 961-4. Reproduced and fixed with `displayHit.ts`: hit-test displayed parcel/hover rings
  first, and resolve a shifted hit using an interior coordinate of its original polygon. Click and hover share
  this mapping; merged outlines are not parcel identities. Originals remain untouched. Actual same-point Chrome
  rerun now selects 961-3 and preview geometry equals original (`test-results/naver-edge-review.cjs`).
  `naverRaster.ts` accepts only observed Naver cadastral tile format (`mt` includes `lp`), current zoom and one
  style/version; incomplete/unknown/mixed tiles refuse capture and clear corrections. Provider format changes
  therefore disable visual fitting rather than tracing an unrelated layer. Same-zoom new captures revalidate
  cached contours; source/version change and layer switches invalidate them. Site-map tests 26 passed; tsc passed.

## 2026-10-09 법규 검토 버튼의 프로젝트 선택 우회 제거
- 사용자 의도: 법규 검토 클릭은 선택한 대지의 법규 분석을 바로 시작한다. 프로젝트 선택이나 대지 카드 재열기를 요구하지 않는다.
- selectedPrompt의 limits 버튼은 선택 당시 PNU/address/parcelCount를 담은 law(review) action. shell act도 limits start-review를 Law 화면으로 전달하여 기존 채팅 버튼의 카드 재열기 반복을 방지한다.
- SiteRunPanel은 프로젝트 바인딩/실행 제출 대신 조건과 직접 법규 검토 버튼만 표시. SiteCard의 중복 법규 보기 버튼 제거. LawArtifact는 전달받은 기준일/용도를 첫 요청부터 적용하고 조건 객체를 안정화한다.
- 묶음 선택은 기존 Law 단일필지 계약에 따라 첫 필지 검토임을 명시한다. Orchestrator 실행 탭과 useOrchestratorReview는 유지한다. 직접 법규 분석은 Orchestrator run을 생성하지 않는다.
- 검증: 관련 unit 63개, scope browser 4개, tsc 통과. 실제 Next 화면에서 projects=[] 및 Law 503 모의 응답으로 카드 클릭 -> 정확히 한 요청, PNU/기준일 보존, 프로젝트 요구 없음 확인. 법규 실응답 내용 검증은 이번 버튼 수정 검증에 포함하지 않았다.
- 프론트 3003 개발 서버 재기동, host ensure backend 성공.

## 2026-10-09 Law 연결 복구 및 새로고침
- 법규 직접 분석 전 공통 host/ensure(['law'])를 호출하도록 api/analyze.ts에 기동 단계 추가. 준비 실패 시 분석을 보내지 않고, 취소 시 후속 요청을 중단한다.
- LawArtifact 상단 버튼은 새로고침 / 새로고침 중. 기존 rerun이 캐시를 비우고 현재 대지·조건을 재분석하며 연결도 다시 준비한다.
- 연결 장애 실원인: Docker Desktop 미기동으로 ace-law 컨테이너 실행 불가. docker desktop start 후 host ensure law 성공. 실제 Next 화면에서 law-analysis HTTP 200, analysis 존재, limits_error=null 확인.
- 기동 순서/실패 차단 unit 및 browser scope 4개, tsc 통과.
