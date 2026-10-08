# Decisions (newest first)

One dated line per decision with its commit.

- 2026-10-08 `14778a6f` Composer live → Law Agent (user: "lawagent가 있는데 조례 다 볼 수 있잖아", "메시지도
  계속 입력되게"). `POST /api/v1/platform/ask` {text, pnu?, assessment_date?} → backend picks `law_ordinance` (조례 이름+조)
  or `law_search` and returns `AskAnswer` (types.ts). Frontend: proxy allowlist `ask`; `api.askLaw`; `site-context.ts`
  (the conversation's site, set on save) so 관련 법규 보기 opens its 조문; `useAsk` (one at a time, user bubble →
  "Law Agent에게 묻는 중" → Law Agent turn with `links` card: law (kind) article + passage ≤220 chars, or the ordinance with
  its law.go.kr edition + article text; 503 → 시스템 보기). Composer: Enter sends, maxLength 500. Live: search 0.5 s, ordinance
  2 s. Open: the hop is editor→Law Agent directly until the Orchestrator exposes a question door (request filed);
  answers are not kept across reloads (feed is memory); the 요약 tab still says 미확정 for split-zoned parcels
  (editor calculator) while the Law Agent run gives weighted caps — next: show the Law Agent's cap there.
- 2026-10-08 `39c4b8dd` Per-agent detail from the agents' own code (user: "INTERFACE도 디테일하게 각 AGENT
  코드 보고"). Read: SiteContextAgent `facts.py` (SITE_KEYS 8, CONFIDENCE 4, BLOCKS_SITING boundary/roads/north),
  Lawagent `district_plan_review.py` (categories), live 683 run (Law whole). Backend parser gained site `facts[]`, law
  capacities/zones/ceilings/articles/height/ordinance sources(url)+limitations/evidence (fixture `limits-single-683`).
  Conversation: step line → replaced by the agent's detailed turn when `results` parse (Site 8-fact checklist `checks`,
  Law tiles with hints + 법적 근거 `links` with law.go.kr + 관련 법규 보기 → law tab articles, Revision `findings`);
  Orchestrator relay "<Agent>에게 <tool> 요청 중" while a step runs (dismissed on completion); header = nothing while
  empty, then "<site> / 법규·한계 검토 · 보류" (`thread.conversationTitle`); `FeedCard.tsx` + `feed-card.css` shared with
  the strip. Labels: `SITE_FACTS`, confidence/category/height/limitation/frontage labels. Verified live (고산동 919 run
  6b99698a: relay +7.5 s, Site +11 s, Law +16 s, Revision/verdict +18 s). Open: big parcels' Site answers are cut before
  most facts (8000-char cap → "응답이 잘려 읽지 못함"), Law's district finding carries the project's pnu (684-1) not the
  reviewed parcel — both for the Orchestrator/Law sessions.
- 2026-10-08 `aa50c6fa` Agents in English with their own marks; the user drives. `agentLabel` →
  Orchestrator / Site / Law / Revision / MasterPlan … Agent (bodies Korean). `shell/conversation/agentMarks.tsx`: icon per
  agent + tint by `data-agent` (Orchestrator = accent). Selecting a site posts the Orchestrator's question "<site> 대지가
  준비됐어요. 무엇을 할까요?" [법규·한계 검토 시작 | 대지 정보 보기 | 법규 요약 보기] — nothing runs until the user
  answers. 검토 시작 is a `command` (`lib/orchestrator-runs/commands.ts`: one-slot bus, a command waits for its owner to
  mount; `conversation/act.ts` opens site-map when nobody listens); `useSiteRun` runs it or answers why not (project not
  chosen / bad date) with the same button again. Verified live on 683 (run 55e92636). Open: a prompt is dismissed on any
  answer, so the error line re-offers the button; after a reload the thread is empty though the card shows 선택됨.
- 2026-10-08 `978965ec` Centre column = agent conversation, multi-agent (user: "대지 고르면 오케스트라에서 LAW로 뜨는
  대화창에 그게 떠야 해, ChatGPT나 Claude처럼" + "멀티에이전트니까 설계 잘해야"). Feed entries carry `agent`
  (`site_context` / `law` / `revision` / `orchestrator`; kind `user` for the user's own lines). `thread.ts` folds
  consecutive lines of the same agent in the same run into one turn; `AgentConversation.tsx` renders user bubbles
  (right), receipts (centred), agent turns (mark = label initial, Orchestrator mark = accent; steps folded under the
  lead line, folded 진행 중 dots rest), Law tiles, evidence chips, the Orchestrator's question with answer buttons, a
  disabled composer ("다음 단계에서 연결"). Shell picks it unless `manifest.conversation === 'page'` (cad). The busy
  '전달하는 중' line is dismissed in both start paths' `finally`. 275 tests. Open: after a reload the thread is empty
  while the card shows 선택됨 (selection is announced only on save); composer input not wired.
- 2026-10-08 `1186aad0` 검토 시작 answers at once + fast polling. Measured through the editor door with 1 s polls
  (scratchpad time_run.py): context 0.35 s, submit 0.83 s, 대지 +3.9 s, 법규 +6.3 s (Law itself ~2.4 s), 검토 조정 +7.5,
  end +8.7 s — "법규 검색이 느리다" was the UI's 3 s cadence + silence until the POST answered. Now `requestingLine`
  ('검토 요청 중 · 대지 · 기준일 · 용도', busy dot) posts before any request in both start paths (site card, law tab),
  `requestFailedLine` on a refused submission, and `poll.ts` `pollInterval`: 1 s for the first 20 s, then 3 s. Live in
  the browser: first line +0.1 s, 접수 +5.6 s (dev-only: the proxy route handlers compile on first hit after a reload),
  question +16 s. `25435317` also: CAD conversation opens empty (`useProviderChat` activeSessionId null) — it used to
  reopen the newest localStorage session, which read as a stray sample chat.
- 2026-10-08 `8d7229ad` Agent feed relays a run as cards + a question (user: "오케스트라 에이전트가 전해주는 거 시각화하고
  법규를 보시겠어요? 이런식으로"): `lib/orchestrator-runs/feed` gains `tone` (step dot ok/warn/busy), `card` (`stats` =
  Law numbers as tiles; `chips` = missing evidence in Korean), kind `prompt` (bubble whose actions are the answers;
  an action without `artifact` only dismisses) and `dismiss(id)`. `feed-lines`: stepTone, lawCard, evidenceCard,
  resultPrompt (보류 / 완료 / 실패 wording; 법규 보기 -> law tab `orchestrator` on the site under the run's binding;
  실패 adds 시스템 보기). `useRunFeed` order: 접수 -> step lines -> law line+tiles -> 결과+chips -> prompt. CSS: feed rows
  are `.agent-feed > ol > li` (nested chip li must keep flex), feed may take 60% of the column. Verified live 3 runs on
  고산 684-1; 법규 보기 lands on 오케스트레이터 검토 and removes the prompt.

- 2026-10-08 `7f65ee78` Orchestrator <-> UI: shared `lib/orchestrator-runs/` (api, poll, feed store, Korean labels,
  ConditionsRow) used by site-map and law; law tab 오케스트레이터 검토 (latest limits run per pnu: timeline, Law numbers vs
  own analysis, ordinance receipt, missing evidence + actions, 검토 시작); shell `conversation/AgentFeed.tsx` shows the
  run feed in the chat (대지 선택 -> 연결 확인 -> 접수 -> step lines -> 결과 + 법규 결과 보기). agent-dialogue/runs.ts
  now re-exports the shared lib. Known: shell params persist across artifacts (?project= changes selection scope).
- 2026-10-08 (feat: orchestrator review) shared `lib/orchestrator-runs/` (api, types, labels, conditions, submit, poll,
  feed, feed-lines, useRunFeed, connection, ui/ConditionsRow) — the one platform-run door; `agent-dialogue/{runs,projects,
  communications}.ts` re-export from it; site-map's site-run/run-conditions re-export the shared parts. Law artifact tab
  `orchestrator` (오케스트레이터 검토: latest `limits` run per pnu, 대지→법규→검토 조정 timeline, Law vs 요약 numbers with
  ≠ marks, 부족한 근거 with actions, 검토 시작; `shell.openArtifact('law', {tab})` lands on it). Shell: `AgentFeed` above the
  conversation body renders `lib/orchestrator-runs/feed` (대지 선택 → /platform/status?refresh=1 connectivity line → run
  receipt → one line per step state change → Law numbers → verdict + 법규 결과 보기). Site card run panel: 법규 결과 보기 after
  a terminal run. Idempotency attempts start from a per-mount nonce (a reload replaying key -1 got 409 because the run had
  moved the source versions). Known: shell params persist across artifacts (opening law with `project` changes the site
  map's selection scope when you go back); dev CSS HMR drops a stylesheet after a CSS edit until a full reload.

- 2026-10-08 `8aadbfd1` 검토 시작 sends `{goal:'limits', pnu, parcels[all], building_type?, assessment_date}` (conditions row:
  기준일 default today + 용도 from shared `lib/building-types.ts`, persisted in localStorage); contiguity notice only when
  the saved site is non-contiguous; `parcels_not_contiguous` surfaces from inside the run (runNotice), not as 409.
  LIVE: 684-1 and 684-1+684-3 (they touch) -> site_resolve needs_evidence (access/hazards/utilities), law_parcel_limits
  succeeded (2,499.7 m², BCR 59.92 / FAR 249.67, 5 floors, policy gosan-public1-molit-2026-334), revision_triage
  needs_user_input -> run `blocked`; a far parcel pair -> `failed parcels_not_contiguous`.
- 2026-10-08 `9d177a32` artifact `law` (법규·한계): target = ?pnu= else saved site's first parcel; `POST /land/analyze`
  with 조건(용도·연면적·기준일) from the ⋯ menu; tabs summary/regulations/articles/setbacks; reuses features/land-map
  LandAnalysisPanel/LawArticlesList/types read-only (debt: fold land-map into this slice, its inline dark palette).
  Site card gained 법규 보기. Known: /land/analyze is single-PNU (bundle = first parcel); shell.openArtifact does
  not update ?artifact=; sunlight description renders raw JSON (pre-existing /land bug); site card horizontal scrollbar.
  고산 684-1 live: 건폐율/용적률 미확정(조례 증거 부족, 법정 상한 59.9/249.7), 대지 2,500 ㎡, 제한 11.
- 2026-10-08 `9bd8d015` site-map slice in FSD segments: manifest / ui/ / model/ / api/ (only place with /api/v1
  literals: selection.ts, mapConfig.ts) / lib/ (picks.ts types+pure, site-run.ts, engine/, layers/). Run panel
  gets `shell` and shows 시스템 보기 when the Orchestrator is unavailable. Rule for every artifact slice.
- 2026-10-08 `1ce68ad9` artifact `system` (features/artifacts/system/{manifest,api,model,lib,ui}): service/agent
  status table from /platform/status, Korean down-hints, 다시 확인 = ?refresh=1. First slice written in the FSD
  segment layout; site-map still to be reorganised (P5). Run panel lacks a 시스템 보기 link (needs shell prop).
- 2026-10-08 `a978fce0` saved site -> Orchestrator: card shows "검토 시작 (법규·한계)" (site-map/run/: site-run.ts,
  useSiteRun.ts, SiteRunPanel.tsx); project = shell ?project= else the only binding else select; request
  {goal:'limits', pnu: parcels[0].pnu} via POST /platform/projects/{id}/runs (Idempotency-Key site-<sel>-<n>),
  polls /platform/runs/{id} every 3 s; Orchestrator down -> Korean error + retry. Bundles send only the first
  PNU until Orchestrator accepts `parcels[]` (requested). `agent-dialogue/runs.ts` gained generic submitRun.
- 2026-10-08 `588ac348` reopening a saved site uses its stored facts + `POST /land/selections/outlines` (outlines only,
  own memory cache, cap = MAX_PARCELS 50) instead of the preview (whose 20-new-PNU budget broke large restores).
- 2026-10-08 UI/UX review fixes `65c5755d` (site-map+shell) `3a63f1c8` (CAD pkg, Korean labels) `12aa371e` (backend):
  save/restore races (snapshot+generation), AbortController, click policy (plain click in bundle = only that parcel;
  re-click sole parcel = deselect; Shift/추가 = add/remove), Esc inner-first + defaultPrevented, hidden 3D stops
  render loop, narrow keeps ArtifactHost mounted (hidden+inert; Naver size from outer element), focus restore,
  separator hit 20px, prefs saved on drag end, Korean copy, dark tokens, role=application. Backend: per-PNU facts+
  geometry memory cache (10 min, 500, never disk), no reverse geocode (addr from parcel layer), selections.scope
  (land.sqlite v5, `latest?scope=`, site-map passes ?project= else default). Dev server on webpack grows to ~15 GB over a day:
  restart it daily until the production build (/_global-error prerender failure) is fixed.
- 2026-10-07 `06f1dae9` site-map 3D: World3D uses useWorld3D directly, creates the engine only once the site is
  known, places the camera instantly (flyTo + completeFlight, verified within 1.5 km) -> first context request at
  고산, 305 buildings in 15-18 s, no Seoul requests. Cause was order: engine opened at MAP_CONFIG_3D.center (Seoul),
  queued ~30 Seoul cells (PARALLEL=3, ~23 s each via SceneAgent). Context cells are uncached (7-23 s each).
  REQUESTS for the features/world owner (not done by us): (1) useWorld3D({initialCenter}) opening there;
  (2) public instant setView(lng,lat); (3) drop far queued cells (queue+asked) on a >1.5 km move; (4) ringOf
  must handle MultiPolygon (non-contiguous bundles draw only the first parcel today). Speed plan: nearest-first
  cell loading + cancel off-screen (world), one bbox request instead of 26 cells, SceneAgent parallel upstream
  calls (agents session), long-term nationwide building PMTiles.
- 2026-10-07 `1636df69` backend + `17b047f5` frontend: site selection. Click = whole parcel polygon (no points),
  Shift+click/카드 토글 = 묶음(합필) add/remove, union outline, contiguity (shapely 0.05 m). API
  `POST /land/selections/preview` (no save), `POST /land/selections`, `GET /land/selections[?limit]`,
  `GET /land/selections/latest` (404 if none). land.sqlite v4 `site_selections` (facts+sources+contiguity,
  no geometry/raw Vworld). Map engine created once (callbacks via refs), no pan/zoom on click, no router
  navigation (history.replaceState only), resize() via ResizeObserver, [2D|3D] toggle (3D = features/world,
  lazy, both kept alive, `?view=3d`). Outline vs Naver 지적편집도 offset 1.2-1.8 m measured at 686-2 only =
  source data difference (no transform in code). Open: 3D highlight not visually checked; terrain-heights
  502 in 3D (world feature); narrow-panel card sheet not live-verified; preview re-fetches facts per click.
- 2026-10-07 `2a5404ea` editor-owned shell `features/shell/` (Shell, layout/, artifact-host/, conversation/,
  sidebar/, artifact-types.ts contract, registry.ts) + right panel = artifact modules `features/artifacts/<id>/`
  (manifest + lazy component; ArtifactChrome fills header/menu). CAD is artifact `cad`, using only the CAD
  package public entry (`@click-around/workspace` public.ts: DwgWorkspaceProvider, DwgSidebar,
  DwgConversation, useDwgArtifact...). `c9a91919` default artifact `site-map`: engine adapter (naver when
  NEXT_PUBLIC_NAVER_MAP_KEY_ID is set -> naver.maps CadastralLayer 지적편집도, colors as given; else / on auth
  failure OpenLayers + Vworld as given), parcel red dashed outline + search marker only, default PNU
  4115011300106840001 (고산 공공1), `?artifact= ?pnu= ?address= ?engine=`. New features = new
  `features/artifacts/<id>/` folder + registry entry. Naver key: NCP Maps app `editor`, Dynamic Map only,
  URLs 127.0.0.1:3003, localhost:3003, 127.0.0.1:3005; key in frontend/app/editor/.env.local (ignored).
  Open: CAD e2e specs for the old frame need moving to the shell; CAD styles.css still duplicates shell tokens;
  backend only accepts Origin :3003 (3005 POSTs 403).
- 2026-10-07 `c424ea49` /dwg shell rebuilt: modes by own width (layoutModes.ts single source, CSS checked by
  unit test): wide>=1200 sidebar 240 [200..320] + rail 56, artifact 45% (stored as ratio, prefs v3); medium
  768-1199 sidebar drawer; narrow<768 one panel ([대화|도면] switch). One header row; chat column 48rem,
  bubble/plain replies, model chip in composer; artifact header = title + Run agents + ⋯ menu (Ctrl+K) + close;
  3 tabs. 11 widths: no overflow, min font 11, 0 buttons <24px. Unit 37/37, tsc 0. e2e specs updated but NOT
  run (playwright chromium not installed). Open: dwg styles.css 570 lines (>500); editor global top nav (20
  links) still scrolls horizontally above the shell -> move into the shell sidebar when features come in.
- 2026-10-07 /dwg responsive rebuild (user: "반응형웹이 아닌데 제대로 해, 최신기술로"): platform CSS only —
  container queries (mode by the workspace's own width: wide >=1200 / medium 768-1199 / narrow <768),
  grid+clamp, dvh, :has(), View Transitions; no new npm dep (risk of a 2nd React from
  infra/services/dwg/node_modules). Numbers from research: sidebar 260 [220..360] (ChatGPT), chat column
  max 48rem centered, artifact beside chat only while chat >= 320px else overlay (Claude), artifact default
  45% min 360; narrow = one panel at a time; type 11/12/14/16, targets >= 28px.
  Sources: openskillindex ChatGPT sidebar CSS, aiuxplayground Claude artifacts, chatjs chat-layout,
  servicetitan artifact-panel-layout, shadcn resizable. Module findings: shell lives inside the CAD package
  and is CAD-specific; app/dwg/page.tsx deep-imports src/app/App instead of the package export (public.ts).
- 2026-10-07 User: `/dwg` (Claude/ChatGPT-style 3 panels: sidebar | chat | artifact) is THE fixed shell —
  every feature will go inside it. Its code lives in `infra/services/dwg/apps/workspace` (layout: App.tsx,
  styles.css, useWorkspaceControls.ts breakpoints 1280/886, workspacePreferences.ts widths sidebar 320
  [280..420], chat min 500, artifact min 520). Layout audit 10-07 (1920..390): no page overflow, but chat
  1066px wide at 1920 while artifact stays 520 (27%); composer spans full chat width; 83/89 text items <12px
  (some 4-7px); artifact tabs overflow at all widths; global top nav (20 links) scrolls horizontally <1920;
  at 1280 artifact squeezed to 446 (<520 min); crossing below 1280 leaves the sidebar open as a covering
  overlay; <=886 artifact opens full-screen over the chat by default; at 390 the artifact close/maximize
  buttons are pushed off-screen (cannot close). CAD needs the gateway: `npm run gateway` in
  infra/services/dwg (:4317, EDITOR_DWG_BACKEND_URL in frontend/app/editor/.env.local).
- 2026-10-06 `d9992018` Split pieces live in the feature's own `components/`, `hooks/`, `lib/` —
  never as siblings of the page (user: "폴더구조 제대로 지키고").
- 2026-10-06 Modularization round 1 (pure splits, originals keep every export): `293cac0a` design
  (mass-entities 513, sunlight, facade-materials, DesignPage, BookLanguageFlow, execution-graph-model);
  `bbd24c52` workspace (PlaygroundPage 505, use-vworld-3d, layout-generator, TeamsPage, LawChat).
  Upstream Pascal files (`components/`, `elements/`, app `build-tab`/`viewer-toolbar`) are not split.
- 2026-10-06 Workspace models run locally on the Claude Code login (backend
  `EDITOR_MODEL_AUTH=oauth`); `/settings` keys are for deployment. (backend `792b4644`)
- 2026-10-05~06 ARR and AG frontends absorbed: AG workspace pages under `(workspace)/`, AG
  frontend unit tests ported to `bun:test` (8 files), labels "Editor Workspace" / "에디터
  워크스페이스", Studio provider names mapped to `autogen_agentchat`. ARR screens `/law`,
  `/map`, `/design` moved; design client URLs lost their trailing slashes, the land
  proxy became `app/api/v1/land/[...path]` (streams SSE), and `lib/api-surface.test.ts` +
  backend `route-inventory.json` guard against dead calls.
