# 폴더 구조

이 리포는 [pascalorg/editor](https://github.com/pascalorg/editor)의 fork이며, 표준 폴더 규칙
(`frontend` / `backend` / `infra` / `docs` / `agents` / `resources`)으로 재구조했다.

**upstream 코드를 찾을 때는 아래 대응표를 먼저 본다.** pascalorg의 이슈·PR·문서는 전부 옛 경로
(`apps/…`, `packages/…`)로 이야기하므로, 그 경로를 여기서 신규 경로로 옮겨 읽어야 한다.

## 현재 트리

```
frontend/
  app/          애플리케이션
    editor/            Next.js :3002 — 메인 3D 에디터
    ifc-converter/     Next.js :3003 — IFC 변환기
    planm/             Vite :8080 — PLAN 제품 UI (자체 npm 툴체인)
  components/   조합된 UI·렌더링 런타임
    editor/            @pascal-app/editor  — 편집 툴·패널·직접조작 UI
    viewer/            @pascal-app/viewer  — R3F 3D 렌더링 런타임
    capture-viewer/    @pascal-app/capture-viewer — 캡처 소스 런타임
  elements/     최소 단위 요소
    ui/                @repo/ui — 버튼·카드 등 디자인 원자
    nodes/             @pascal-app/nodes — wall/door/window/roof 등 47종 빌딩 요소

backend/
  mcp/          @pascal-app/mcp — MCP 서버. 에이전트가 씬을 생성·검증하는 진입점
  cli/          @pascal-app/cli — 로컬 런타임 설치·프로세스 관리
  ifc-converter/@pascal-app/ifc-converter — IFC → Pascal 그래프 변환
  app/          PLANM FastAPI (:8000) — api/ modules/ adapters/ core/ schemas/
  engine/       PLANM 기하·그래프·제약·메트릭 프리미티브
  tests/        PLANM pytest (971개)

infra/
  docker/       Editor: Dockerfile, docker-compose.yml / PLAN: compose.yml + 서비스별 Dockerfile
  config/
    typescript/       @pascal/typescript-config — 전 패키지가 extends 하는 tsconfig
    typescript-repo/  @repo/typescript-config — elements/ui 전용
    eslint/           @repo/eslint-config
  dev/          PLAN 로컬 오케스트레이터 (`bun run plan:dev`)
  e2e/          PLAN Playwright 설정
  runtimes/     GitAgent 호스트 (PLANM 스킬·워크플로 실행)
  services/     DWG 서비스 (독립 실행, PLANM과 상호 import 없음)

docs/           이 문서, SETUP, CONTRIBUTING, CHANGELOG, architecture/, mcp/

agents/         에이전트 지침·스킬 (skills/, copilot-instructions.md)

resources/
  lib/          공유 라이브러리
    core/              @pascal-app/core — 노드 스키마, 씬 상태(Zustand), 레지스트리, 시스템
    capture-protocol/  @pascal-app/capture-protocol — 캡처 매니페스트·스트림 계약
  data/         icons/, styles/, examples/, plans/ — 샘플 도면
  scripts/      release/, plan-to-3d.ts, clean-cache.ts
  tests/        E2E·통합 테스트 (유닛 테스트는 소스 옆에 둔다)
  datasets/ experiments/ research/   PLAN 연구 입력물과 증거 (PLAN 규칙 그대로 유지)
```

## upstream 경로 → 현재 경로

| pascalorg/editor | 이 리포 |
|---|---|
| `apps/editor` | `frontend/app/editor` |
| `apps/ifc-converter` | `frontend/app/ifc-converter` |
| `packages/editor` | `frontend/components/editor` |
| `packages/viewer` | `frontend/components/viewer` |
| `packages/capture-viewer` | `frontend/components/capture-viewer` |
| `packages/ui` | `frontend/elements/ui` |
| `packages/nodes` | `frontend/elements/nodes` |
| `packages/mcp` | `backend/mcp` |
| `packages/cli` | `backend/cli` |
| `packages/ifc-converter` | `backend/ifc-converter` |
| `packages/core` | `resources/lib/core` |
| `packages/capture-protocol` | `resources/lib/capture-protocol` |
| `packages/eslint-config` | `infra/config/eslint` |
| `packages/typescript-config` | `infra/config/typescript-repo` |
| `tooling/typescript` | `infra/config/typescript` |
| `tooling/release` | `resources/scripts/release` |
| `public/icons`, `styles/` | `resources/data/` |
| `Dockerfile`, `docker-compose.yml` | `infra/docker/` |
| `wiki/architecture` | `docs/architecture` |

재구조 직전 상태는 `pristine-upstream` 태그와 `main` 브랜치에 그대로 보존돼 있다.

```bash
git diff pristine-upstream --stat        # 재구조 이후 바뀐 것 전부
git show pristine-upstream:apps/editor/package.json   # 옛 경로로 원본 파일 열람
git fetch upstream && git log upstream/main --oneline # upstream 신규 커밋 확인
```

## 두 제품이 한 리포에

`akfldk1028/PLAN`을 히스토리째 흡수했다 (`--allow-unrelated-histories`). 두 리포가 이미 같은 최상위 규칙이라 원래 경로에 그대로 안착했고, PLAN 쪽 이탈만 규칙에 맞춰 옮겼다:

| 흡수 시점 | 옮긴 곳 | 이유 |
|---|---|---|
| `frontend/{index.html,src,tests,vite.config.ts,...}` | `frontend/app/planm/` | `frontend/` 바로 아래는 `app`·`components`·`elements` 만 |
| `compose.yml` (루트) | `infra/docker/compose.yml` | Docker 정의는 `infra/docker/` |

스크립트는 접두사로 갈린다 — Editor는 `bun dev`, PLAN은 `bun run plan:dev`.

**`frontend/app/planm`은 bun 워크스페이스가 아니다.** 자체 npm 툴체인과 DWG 서비스로의 `file:` 의존성을 갖고 있어서, 루트 `workspaces`는 glob 대신 Editor 패키지를 이름으로 나열한다. biome도 이 경로를 제외한다 (PLAN은 biome 포맷이 아니다).

## 규칙에서 벗어난 세 가지 (의도된 예외)

**1. 패키지 내부 빌드 스크립트는 패키지 안에 남는다.**
`frontend/app/ifc-converter/scripts/`, `backend/cli/scripts/`, `backend/mcp/scripts/`는
`postinstall`·`prebuild`가 패키지 상대경로로 부르고 npm 배포 tarball에도 들어가야 하므로
`resources/scripts/`로 옮기지 않았다. `resources/scripts/`에는 프로젝트 레벨 스크립트만 둔다.

**2. 유닛 테스트는 소스 옆에 둔다.**
537개 테스트가 `create-wall.ts` / `create-wall.test.ts` 형태로 콜로케이트돼 있다.
`resources/tests/`는 E2E·통합 테스트 자리다. PLAN 쪽 pytest는 `backend/tests/`에 모여 있다 —
PLAN 자체 규칙이며 `pytest.ini`의 `testpaths`가 그것을 가리킨다.

**3. `resources/` 아래 PLAN의 세 디렉터리는 그대로 둔다.**
`datasets/` `experiments/` `research/`는 PLAN의 연구 입력물과 증거다. 규칙의
`data/scripts/tests/lib` 밖이지만, PLAN 문서와 스킬이 이 경로를 참조하므로 옮기지 않았다.

## 루트에 남아야 하는 것

도구가 리포 루트에서만 인식하므로 옮기면 깨진다.

`.github/` (Actions) · `.devcontainer/` (VS Code) · `.claude/` `.cursor/` `.codex/` `.agents/`
`.superpowers/` `.remember/` (에이전트 도구) · `CLAUDE.md` `GEMINI.md` `AGENTS.md` ·
`README.md` `LICENSE` `SECURITY.md` `CODE_OF_CONDUCT.md` (GitHub) ·
`package.json` `bun.lock` `turbo.json` `biome.jsonc` `.gitattributes` `.env*` (JS 툴체인) ·
`pyproject.toml` `pytest.ini` `package-lock.json` (PLAN 툴체인) ·
`.dockerignore` — 두 compose 모두 빌드 컨텍스트가 리포 루트라 Docker 는 이것만 읽는다

## 구조를 바꿀 때 같이 고쳐야 하는 곳

패키지를 옮기면 아래가 전부 따라와야 한다. 소스의 `import`는 패키지명(`@pascal-app/*`) 기반이라
영향받지 않는다.

| 위치 | 무엇 |
|---|---|
| `package.json` | `workspaces` 글롭 |
| 각 패키지 `tsconfig.json` | `references` 상대경로 |
| `frontend/app/editor/package.json` | `dotenv -e ../../../.env.local` 깊이 |
| `frontend/app/editor/app/globals.css` | Tailwind `@source` / `@import` 상대경로 |
| `frontend/app/editor/next.config.ts` | `outputFileTracingRoot` |
| `frontend/app/editor/vercel.json` | `cd ../../..` |
| `biome.jsonc` | `files.includes` 및 override 글롭 |
| `.github/workflows/*.yml` | 트리거 `paths`, `working-directory`, `PKG_DIR` 맵 |
| `infra/docker/Dockerfile` | `WORKDIR` |
| `backend/cli/scripts/stage-runtime.ts` | Next standalone 출력 경로 = 앱의 리포 상대경로 |
| `backend/cli/src/editor-process.ts` | 런타임 매니페스트 fallback entrypoint |
| `resources/scripts/release/*.sh` | `ROOT_DIR` 깊이 |
