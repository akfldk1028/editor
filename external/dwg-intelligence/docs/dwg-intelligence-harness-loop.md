# DWG Intelligence clone, skill, MCP harness loop

작성일: 2026-07-27

## 1. 이번 단계의 목표

이 단계의 목표는 CAD 뷰어를 크게 구현하는 것이 아니라, 다음 루프를 검증 가능한 형태로 고정하는 것이다.

```text
로컬 DWG/DXF 파일
  -> CAD 파서/뷰어
  -> 정규화 Entity Index JSON
  -> MCP CAD tools/resources
  -> Agent skill
  -> 검수/검색 결과
  -> viewer highlight/zoom/select
  -> sidecar JSON audit
```

핵심은 LLM이 도면을 추측해서 읽는 구조가 아니다. CAD 엔진이 객체 ID, handle, layer, type, bbox, text, block, layout, unsupported 요약을 만들고, Agent는 그 인덱스와 tool 결과만 근거로 말해야 한다.

## 2. clone 후보 정리

`C:\DK\DWG\clone`에 받은 후보는 제품 코드가 아니라 조사/참조/PoC 후보로 취급한다.

| 후보 | 역할 | 확인한 장점 | 확인한 위험 | 판단 |
| --- | --- | --- | --- | --- |
| `cad-viewer` | MLightCAD 웹 뷰어/플러그인 후보 | MIT 패키지, entity `objectId`, `type`, `layer`, `geometricExtents`, selection/highlight/zoom API 확인 | 실제 DWG 변환 쪽은 `@mlightcad/libredwg-converter` GPL-3.0 의존 | UI/객체 API PoC 후보. 상용 DWG 파서로 바로 묶으면 위험 |
| `realdwg-web` | MLightCAD DWG/DXF 변환/데이터 모델 | AutoCAD식 data-model, entity converter, text/extents 관련 코드 풍부 | `libredwg-converter` GPL-3.0 | 내부 API 연구용. 상용 배포 전 법무/라이선스 분리 필요 |
| `ACadSharp` | .NET 로컬 DWG/DXF 파서 후보 | MIT, `DwgReader`, `CadDocument`, `Entities`, `Layers`, `Layouts`, bbox API, codepage `kcs5601/johab/utf16` 흔적 확인 | Proxy/AEC Wall bbox 등 일부 객체 미구현/제한 | DWG 로컬 인덱서 1순위 후보 |
| `dxf-vuer` | DXF 브라우저 MVP 후보 | MIT, React/Vue/Lit, `findEntitiesByLayer/Text/Type`, `highlight`, `zoomToEntity`, picking index, unsupported 이벤트 확인 | DWG가 아니라 DXF 중심 | 빠른 하네스/프론트 MVP 1순위 |
| `DXF-Renewed` | DXF indexer 후보 | MIT, `parseString`, `denormalise`, `toPolylines`, `groupEntitiesByLayer` | DWG 미지원 | headless DXF indexer 후보 |
| `dxf-parser` | 단순 DXF parser 후보 | MIT, JS parser, layer/block/text 일부 지원 | entity coverage 제한, DWG 미지원 | fallback/parser 비교용 |
| `dxf-viewer` | 고성능 DXF viewer 참고 | MPL-2.0, WebGL/Three.js | 한글 codepage, paper space, MTEXT, dimension/leader 제약 명시 | 성능 참고. 한국 실무 MVP 1순위는 아님 |
| `dxf-json` | DXF parser 참고 | entity type coverage 넓음 | GPL-3.0 | 제품 의존성 제외 |
| `construction-drawing-analyzer` | 도면 사전 인덱싱 skill 패턴 | sheet classification, cross-reference, symbol-library, master-register 루프가 유용 | PDF/OCR 중심, LICENSE 없음 | 아이디어/하네스 구조 참고 |
| `DDC_Skills_for_AI_Agents_in_Construction` | construction AI skill wording | MIT, 도면 분석 skill 예시 | 실제 CAD 객체 API 구현은 아님 | Agent skill 작성 참고 |
| `engineering-drawing-ai-rag` | RAG 개념 참고 | MIT, 연구형 구조 | 구현 성숙도 낮음 | 장기 RAG 참고 |
| `dxf-viewer-examples` | 상용/opaque viewer 참고 | DWG/DXF, layer/layout/measure/markup/compare 등 UI 기능 참고 가능 | `@x-viewer/core` 라이선스 미확인 | 기능 벤치마크만 참고 |

## 3. 라이선스 기준선

초기 상용화 가능성을 지키려면 다음 원칙으로 간다.

- MIT 계열: PoC와 제품 후보로 사용 가능.
- MPL-2.0: 파일 단위 copyleft 조건이 있으므로 수정/배포 전략을 별도 검토.
- GPL-3.0: 폐쇄형 상용 앱에 직접 번들링하지 않는다.
- LICENSE 없는 repo: 코드 의존성으로 사용하지 않는다.
- 상용/opaque SDK: 기능 참고만 하고, 계약/비용/오프라인 동작/데이터 전송 조건 확인 전에는 제품 핵심에 넣지 않는다.

따라서 첫 구현은 `dxf-vuer` 또는 `DXF-Renewed` 기반의 DXF 인덱스 하네스로 시작하고, DWG는 `ACadSharp` 로컬 파서로 병렬 검토한다. MLightCAD는 viewer/object API 검증 후보로 두되 GPL 변환기를 제품 core로 묶지 않는다.

## 4. 정규화 Entity Index 계약

MVP의 모든 CAD tool은 아래 JSON을 기준으로 동작한다.

```json
{
  "schemaVersion": "cad-index/v0.1",
  "drawingId": "sha256-or-local-id",
  "source": {
    "kind": "dxf",
    "displayName": "sample.dxf",
    "parser": "dxf-vuer|dxf-renewed|acadsharp"
  },
  "summary": {
    "entityCount": 0,
    "layerCount": 0,
    "unsupportedCount": 0,
    "modelSpaceCount": 0,
    "paperSpaceCount": 0
  },
  "layers": [
    {
      "name": "A-WALL",
      "entityCount": 0,
      "visible": true,
      "frozen": false
    }
  ],
  "entities": [
    {
      "id": "stable-local-id",
      "handle": "1A2",
      "type": "LWPOLYLINE",
      "layer": "A-WALL",
      "space": "model",
      "layout": "Model",
      "bbox": { "min": [0, 0, 0], "max": [1000, 1000, 0] },
      "text": null,
      "blockName": null,
      "attributes": {},
      "geometry": {
        "closed": true,
        "length": 0,
        "area": 0
      },
      "warnings": []
    }
  ],
  "unsupported": [
    {
      "type": "PROXYENTITY",
      "count": 0,
      "reason": "parser-not-supported"
    }
  ]
}
```

주의:

- `id`는 앱 내부 stable ID다. 원본 CAD handle이 있으면 `handle`에 유지한다.
- bbox가 없거나 무한대면 `warnings`에 남기고 tool 결과에서 계산 근거를 제한한다.
- 한글 TEXT/MTEXT는 원문 문자열과 정규화 문자열을 추후 분리한다.
- block 내부 entity는 `ownerBlock`, `insertHandle`, `transform` 필드를 추가할 수 있다.

## 5. MCP 설계

MCP 공식 구조상 Tools는 모델이 호출하는 액션이고, Resources는 앱/모델이 읽는 컨텍스트다. TypeScript SDK는 MCP server가 tools/resources/prompts를 노출하고 stdio 또는 Streamable HTTP transport를 사용할 수 있다. 로컬 우선 제품에는 처음에 stdio 또는 localhost HTTP가 맞다.

### 5.1 Tools

초기 tool 이름은 CAD 액션임이 분명하게 `cad.*`로 둔다.

| Tool | 입력 | 출력 | MVP |
| --- | --- | --- | --- |
| `cad.open_drawing` | `{ path }` | `{ drawingId, source, warnings }` | 예 |
| `cad.build_index` | `{ drawingId }` | `{ drawingId, indexUri, summary }` | 예 |
| `cad.get_layers` | `{ drawingId }` | `{ layers[] }` | 예 |
| `cad.find_entities_by_layer` | `{ drawingId, layer }` | `{ matches[] }` | 예 |
| `cad.find_entities_by_type` | `{ drawingId, type }` | `{ matches[] }` | 예 |
| `cad.find_text` | `{ drawingId, query, regex? }` | `{ matches[] }` | 예 |
| `cad.get_entity` | `{ drawingId, entityIdOrHandle }` | `{ entity }` | 예 |
| `cad.list_unsupported` | `{ drawingId }` | `{ unsupported[] }` | 예 |

위 8개가 현재 등록된 read-only MCP tool 전체다. viewer select/zoom,
sidecar write, unclosed-polyline 검사, index 비교는 계획 항목이며 현재 tool
surface로 호출하거나 실행됐다고 보고하면 안 된다.

Tool 결과의 `matches[]`/`issues[]`는 항상 아래 최소 필드를 포함한다.

```json
{
  "id": "stable-local-id",
  "handle": "1A2",
  "type": "TEXT",
  "layer": "A-ROOM",
  "bbox": { "min": [0, 0, 0], "max": [100, 20, 0] },
  "reason": "text contains query",
  "confidence": 1.0
}
```

### 5.2 Resources

```text
cad://drawings
cad://drawings/{drawingId}/summary
cad://drawings/{drawingId}/index
cad://drawings/{drawingId}/layers
cad://drawings/{drawingId}/entities/{entityId}
cad://drawings/{drawingId}/unsupported
cad://drawings/{drawingId}/sidecar
```

Resources는 읽기 전용으로 시작한다. 도면 원본 경로는 외부 LLM에 그대로 노출하지 않고 `displayName`/`drawingId` 중심으로 전달한다.

### 5.3 Prompts

MCP prompt는 사용자가 명시적으로 선택할 수 있는 반복 워크플로 템플릿으로 둔다.

- `dwg_layer_search`: 특정 layer/query/entity type 탐색
- `dwg_text_extract`: 선택 영역 또는 전체 도면 TEXT/MTEXT 추출
- `dwg_basic_health_check`: unsupported, bbox 없음, 닫히지 않은 polyline, 빈 text 등 기본 검사
- `dwg_revision_compare`: 두 인덱스 비교

## 6. Agent skill 설계

초기 skill 위치:

```text
agent/
  skills/
    dwg-intelligence/
      SKILL.md
      references/
        entity-index-schema.md
        query-playbook.md
        risk-checklist.md
      scripts/
        smoke-index-sample.ts
```

`SKILL.md`의 규칙:

1. 도면 질문을 받으면 먼저 `cad://drawings/{drawingId}/summary` 또는 `cad.build_index` 결과를 확인한다.
2. 레이어/타입/문자/블록 검색은 반드시 CAD tool을 호출한다.
3. 길이/면적/폐합/교차는 LLM이 계산하지 않고 CAD tool 결과만 사용한다.
4. 답변에는 가능한 경우 `handle`, `type`, `layer`, `bbox`, `reason`을 포함한다.
5. 원본 DWG 수정은 금지한다. 결과는 sidecar/overlay로만 기록한다.
6. unsupported/proxy/xref/font/codepage 문제가 있으면 결과 신뢰도와 한계를 명시한다.

## 7. Harness 설계

LLM을 붙이기 전에 deterministic harness로 CAD tool이 맞는지 먼저 검증한다.

```text
agent/
  contracts/
    cad-index.schema.json
    cad-tools.schema.json
  harness/
    cases/
      find-layer-a-wall.json
      find-text-room-name.json
      list-door-blocks.json
      unclosed-polyline-smoke.json
      unsupported-summary.json
    run-case.ts
    run-all.ts
  fixtures/
    README.md
```

Case 형식:

```json
{
  "name": "find-layer-a-wall",
  "fixture": "fixtures/sample.dxf",
  "steps": [
    { "tool": "cad.open_drawing", "args": { "path": "$fixture" } },
    { "tool": "cad.build_index", "args": { "drawingId": "$last.drawingId" } },
    { "tool": "cad.find_entities_by_layer", "args": { "drawingId": "$last.drawingId", "layer": "A-WALL" } }
  ],
  "expect": {
    "minMatches": 1,
    "requiredFields": ["id", "handle", "type", "layer", "bbox"]
  }
}
```

이 하네스는 나중에 다음 두 방식으로 재사용한다.

- CAD engine 단위 테스트: LLM 없이 tool 결과만 검증
- Agent 평가: 같은 case를 자연어 질문으로 던지고 tool 호출/최종 답변이 기준을 만족하는지 검증

## 8. MVP 수직 기능 단위

첫 수직 기능은 다음으로 제한한다.

```text
DXF 샘플 열기
  -> entity index 생성
  -> "A-WALL 레이어 객체만 찾아줘"
  -> CAD tool이 matches 반환
  -> viewer가 해당 객체 highlight/zoom
  -> sidecar JSON에 검색 기록 저장
```

이 기능이 통과해야 다음 검수로 넘어간다.

- TEXT/MTEXT 추출
- 문/창호 block 또는 INSERT 검색
- 닫히지 않은 LWPOLYLINE 검사
- 면적 문자와 실제 polyline 면적 비교
- DWG 입력을 ACadSharp 로컬 indexer로 교체

## 9. 다음에 구현할 단 하나의 첫 작업

다음 작업은 UI가 아니라 계약/하네스부터 만든다.

**첫 구현 작업: `agent/contracts`와 `agent/harness`를 만들고, DXF 샘플 1개를 `cad-index/v0.1` JSON으로 변환하는 headless smoke를 통과시킨다.**

이유:

- DWG 파서 라이선스 위험과 무관하게 tool loop를 먼저 고정할 수 있다.
- viewer를 붙이기 전에 `id/handle/type/layer/bbox/text/unsupported` 계약이 맞는지 검증할 수 있다.
- 이후 `dxf-vuer` viewer, MLightCAD viewer, ACadSharp DWG parser가 모두 같은 index 계약으로 붙을 수 있다.
- Agent skill과 MCP tool schema가 실제 데이터 모양에 맞춰진다.

성공 기준:

- `agent/contracts/cad-index.schema.json` 존재
- `agent/harness/cases/find-layer-a-wall.json` 존재
- `agent/harness/run-case.ts` 또는 동등한 runner 존재
- 샘플 DXF에서 entity index JSON 생성
- layer 검색 결과가 `id`, `handle`, `type`, `layer`, `bbox`를 포함
- unsupported entity가 있으면 실패하지 않고 요약에 집계

## 10. 2026-07-28 실제 브라우저 검사 루프

현재 프론트 검사는 데모 scenario 문자열이 아니라 다음 경로를 사용한다.

```text
GET /api/drawing
  -> 서버가 관리하는 동일 DWG의 cad-index/v0.1
  -> Run agents
  -> POST /api/inspections
  -> createInspectionOrchestrator
  -> cad.open_drawing / cad.build_index / cad.find_entities_by_layer
  -> verifyMatches
  -> events / findings / issues / warnings
  -> viewer highlight + evidence dock
```

브라우저는 로컬 파일 경로를 검사 API로 보내지 않는다. 서버의 `DrawingWorkspace`가 workspace 내부 DWG만 선택하며, workspace 밖 상대경로는 거부한다.

검증 명령:

```powershell
$env:DWG_FRONTEND_PORT='4174'
$env:DWG_GATEWAY_PORT='4318'
Set-Location frontend
npx playwright test
```

`DWG_FRONTEND_PORT`와 `DWG_GATEWAY_PORT`는 기존 개발 서버를 종료하지 않고 격리된 worktree 검증을 실행하기 위한 포트다.

유지할 시각 증거:

- `tests/visual/artifacts/loaded-1440x900.png`
- `tests/visual/artifacts/real-inspection-1440x900.png`
- `tests/visual/artifacts/finding-evidence-1440x900.png`
- `tests/visual/artifacts/no-warning-1440x900.png`

실제 DWG 인덱스는 경로별 in-flight Promise를 공유한다. 병렬 브라우저가 같은 도면을 요청해도 `dotnet run` 빌드가 중복 실행되지 않으며, parser 실패 시에는 캐시를 제거해 다음 요청이 재시도할 수 있다.
