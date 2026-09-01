# DWG Intelligence MVP 조사 및 구현 계획

작성일: 2026-07-27

## 1. 프로젝트 루트 판정

- 작업 루트는 `C:\DK\DWG`로 본다.
- 현재 `C:\DK\DWG` 자체는 Git 저장소가 아니다.
- 현재 루트에는 `agent`, `backend`, `frontend`, `docs`, `logs`, `clone` 디렉터리만 있고 제품 코드, `README.md`, `package.json`, `.sln`, `.csproj`, `pyproject.toml`은 없다.
- `clone` 아래의 `cad-viewer`, `realdwg-web`, `ACadSharp`는 이번 조사를 위해 받은 외부 후보 저장소이며 제품 소스 루트로 보지 않는다.

## 2. 현재 저장소 상태

- `frontend`, `backend`, `agent`는 아직 비어 있다.
- `docs`도 이번 문서 작성 전까지 비어 있었다.
- `logs/security/.security-key`만 기존 로컬 파일로 존재한다.
- 따라서 이번 단계에서는 기존 구현과 충돌할 코드가 없다.

## 3. 확인한 후보 저장소와 실제 API

### 후보 A: MLightCAD cad-viewer

확인 위치:

- `clone/cad-viewer`
- `clone/realdwg-web`
- <https://github.com/mlightcad/cad-viewer>
- <https://github.com/mlightcad/realdwg-web>

실제 확인된 구성:

- `@mlightcad/cad-viewer`: Vue 기반 완성형 CAD 뷰어 컴포넌트.
- `@mlightcad/cad-simple-viewer`: 캔버스, 문서 매니저, 선택, 레이어, 명령, 뷰 API 중심의 코어.
- `@mlightcad/data-model`: `AcDbDatabase`, `AcDbEntity`, `AcDbLine`, `AcDbCircle`, `AcDbPolyline`, `AcDbBlockReference`, `AcDbMText`, `AcDbLayerTable` 등 ObjectARX 유사 데이터 모델.
- `@mlightcad/libredwg-converter`: DWG 변환기. Web Worker/WASM 기반. 라이선스는 GPL-3.0.
- `cad-agent-plugin`: 이미 AI Tool Calling 플러그인이 있으나 현재 도구는 주로 그리기, 레이어 생성/변경, 줌이다.

확인된 객체 접근 API:

- 현재 문서: `AcApDocManager.instance.curDocument`
- 현재 DB: `AcApDocManager.instance.curDocument.database`
- Model Space 순회: `db.tables.blockTable.modelSpace.newIterator()`
- 객체 ID: `entity.objectId`
- 객체 타입: `entity.type`
- 레이어: `entity.layer`
- bbox: `entity.geometricExtents`
- 블록 참조 판정/집계 예시: `cad-viewer/src/composable/useCountList.ts`
- 선택 하이라이트: `AcApDocManager.instance.curView.selectionSet.clear()` 후 `selectionSet.add(ids)`
- 카메라 이동: `view.zoomTo(box, padding)` 또는 `view.zoomToFitDrawing()`
- 레이어 목록: `doc.layerStore.getLayers()`

이미 있는 AI 플러그인 도구:

- `get_drawing_context`
- `draw_line`
- `draw_circle`
- `draw_arc`
- `draw_rectangle`
- `draw_polyline`
- `draw_ellipse`
- `draw_hatch`
- `draw_point`
- `draw_ray`
- `draw_xline`
- `draw_spline`
- `draw_text`
- `set_current_layer`
- `create_layer`
- `delete_entities`
- `zoom_extents`

부족한 도구:

- 레이어별 객체 검색
- 타입별 객체 검색
- TEXT/MTEXT 추출
- INSERT/블록 속성 조회
- 폴리라인 폐합 검사
- 객체 ID 목록 선택/줌/오버레이 결과화
- 지원 불가 객체 집계

### 후보 B: ACadSharp

확인 위치:

- `clone/ACadSharp`
- <https://github.com/DomCR/ACadSharp>

실제 확인된 구성:

- C#/.NET CAD 라이브러리.
- DWG/DXF 읽기와 쓰기 지원.
- `CadDocument`, `DwgReader`, `DxfReader`, `doc.Entities`, `doc.Layers`, `doc.Layouts`, `doc.BlockRecords`, `Entity.Handle`, `Entity.Layer`, `Entity.GetBoundingBox()`가 존재한다.
- `CadUtils`에 `kcs5601`, `johab`, `utf16` 등 코드페이지 처리가 있다.
- `ProxyEntity`, `UnknownNonGraphicalObject`, AEC Wall 관련 클래스와 샘플 테스트가 있다.

확인된 DWG/DXF 버전:

- README 기준 DWG Reader: AC1014, AC1015, AC1018, AC1021, AC1024, AC1027, AC1032 지원.
- AC1009, AC1012 DWG Reader는 미지원.

확인된 한계:

- `ProxyEntity.GetBoundingBox()`는 `BoundingBox.Null` 반환.
- `AEC Wall.GetBoundingBox()`는 `NotImplementedException`.
- 즉, 커스텀/AEC 객체는 읽히더라도 MVP 분석 기준 객체로 쓰기 어렵고 별도 집계/경고가 필요하다.

## 4. 라이선스 및 상용화 위험

### MLightCAD

- `cad-viewer`, `cad-simple-viewer`, `data-model` 자체는 MIT로 확인했다.
- 기본 DWG 경로의 `@mlightcad/libredwg-converter`는 GPL-3.0이다.
- 폐쇄형 상용 제품에서 GPL DWG 파서를 번들링하는 것은 법무 검토 전에는 위험하다.
- MLightCAD는 별도 proprietary parser 문서를 제공한다. 문서 기준 가격은 초기 USD 3,000, 이후 업그레이드가 필요하면 USD 1,500/year다.
- 해당 proprietary parser는 사전 빌드 npm 패키지이며 소스는 제공하지 않는다고 설명되어 있다.
- 개인 프로젝트 유지보수 성격이며 공식 SLA는 없다고 명시되어 있다.

### ACadSharp

- MIT 라이선스다.
- .NET 로컬 파서로 쓰기 좋고, 폐쇄형 제품 리스크는 낮다.
- 다만 뷰어와 직접 연결되는 렌더링/선택 UI는 별도로 만들어야 하며, 커스텀 객체 bbox/형상 한계가 있다.

## 5. 실무 호환성 위험

높은 위험:

- GPL DWG 파서 의존성.
- 한글 TEXT/MTEXT, SHX 폰트, 누락 TTF 폰트.
- XRef 경로 누락과 상대/절대경로.
- AutoCAD Architecture/AEC/Proxy 객체의 bbox 및 의미 데이터 부족.
- 대용량 DWG의 브라우저 WASM 메모리 한계.

중간 위험:

- 매우 큰 좌표값에서 WebGL 정밀도와 bbox/줌 안정성.
- Nested Block, Anonymous Block, Dynamic Block 처리.
- Paper Space/Layout/Viewport에서 실제 검수 기준 좌표계 결정.
- 손상 파일이나 부분 읽기 시 사용자에게 명확한 partial load 상태 제공.

초기 대응 원칙:

- 전체 파일 열기 실패 대신 가능한 객체만 처리한다.
- 지원 불가 객체는 type, count, handle/objectId를 집계한다.
- 분석 결과에는 항상 한계와 기준 공간(Model/Paper/Layout)을 기록한다.
- 원본 DWG는 쓰지 않고 sidecar JSON으로 저장한다.

## 6. MVP 수직 기능 설계

첫 MVP는 "DWG/DXF를 열고, A-WALL 같은 레이어 질의를 실행해, 실제 객체 ID를 선택/줌하고 결과 JSON을 남기는 기능"으로 제한한다.

### 수직 기능

사용자 질의:

> A-WALL 레이어 객체만 찾아줘.

처리 흐름:

1. 브라우저 뷰어에서 로컬 DWG/DXF 파일을 연다.
2. CAD DB의 Model Space 엔티티를 순회한다.
3. `entity.layer === "A-WALL"` 조건으로 필터링한다.
4. 각 결과에 `objectId`, `type`, `layer`, `geometricExtents`, 표시 가능 여부를 담는다.
5. 결과 객체를 `selectionSet.add(ids)`로 선택/하이라이트한다.
6. bbox를 합쳐 `view.zoomTo(box, 1.5)`로 이동한다.
7. sidecar JSON 형태의 분석 결과를 생성한다.
8. 에이전트 답변은 객체 수, 대표 타입, 선택된 ID, 지원 불가/경고를 말한다.

### 초기 아키텍처

권장 1차 구조:

```text
frontend
  Vite + React 또는 Vue
  MLightCAD cad-simple-viewer 기반 뷰어
  CAD Query Panel

agent
  CAD tool schema
  rule-based command router first
  LLM tool calling later

docs
  조사/설계/검수 규칙 문서
```

중요 결정:

- 1차는 MLightCAD 기반 브라우저 PoC가 가장 빠르다.
- 단, 상용 폐쇄형 빌드에서는 GPL DWG 파서를 기본 의존성으로 확정하지 않는다.
- DXF 또는 샘플 DWG PoC로 객체 API 검증을 먼저 끝낸다.
- 이후 ACadSharp 로컬 파서를 병렬 후보로 두고 `Normalized CAD JSON` 스키마를 설계한다.

### Normalized CAD JSON 초안

```json
{
  "source": {
    "fileNameRedacted": true,
    "format": "dwg",
    "parser": "mlightcad|acadsharp",
    "partial": false
  },
  "spaces": [
    {
      "name": "Model",
      "entities": [
        {
          "id": "string",
          "handle": "string|null",
          "type": "Line|Polyline|Text|MText|BlockReference|Unknown",
          "layer": "A-WALL",
          "bbox": {
            "min": { "x": 0, "y": 0, "z": 0 },
            "max": { "x": 0, "y": 0, "z": 0 }
          },
          "text": null,
          "blockName": null,
          "supported": true,
          "warnings": []
        }
      ]
    }
  ],
  "unsupported": [
    {
      "type": "AEC_WALL",
      "count": 3,
      "reason": "bbox_not_implemented"
    }
  ]
}
```

## 7. 구현 계획

### Task 1: 프런트엔드 PoC 생성

- `frontend`에 Vite 기반 앱을 만든다.
- `@mlightcad/cad-simple-viewer` 또는 `@mlightcad/cad-viewer` 최소 예제를 붙인다.
- 워커 파일 복사 설정을 추가한다.
- 샘플 DXF/DWG를 로컬에서 열 수 있게 한다.

검증:

- 브라우저에서 도면이 표시된다.
- 레이어 목록을 읽을 수 있다.
- 선택/줌 명령이 동작한다.

### Task 2: CAD Query Core 작성

- `queryEntitiesByLayer(layerName)` 구현.
- `queryEntitiesByType(type)` 구현.
- 결과 DTO에 `objectId`, `type`, `layer`, `bbox`, `supported`, `warnings`를 담는다.
- bbox 없는 객체도 실패시키지 않고 결과에 warning을 넣는다.

검증:

- 샘플 도면에서 특정 레이어 결과 개수가 반환된다.
- 결과 ID를 선택하면 화면에서 하이라이트된다.

### Task 3: Agent Tool 최소 연결

- `find_entities_by_layer`
- `select_entities`
- `zoom_to_entities`
- `get_query_result_summary`

검증:

- "A-WALL 레이어 객체만 보여줘" 입력 시 tool 결과 기반으로 선택/줌이 된다.

### Task 4: Sidecar JSON 저장

- 분석 결과를 원본 DWG와 분리된 JSON으로 저장/다운로드한다.
- 원본 경로, 사용자명 등 민감한 정보는 저장하지 않는다.

검증:

- 결과 JSON에 객체 ID와 bbox가 포함된다.
- 원본 DWG는 수정되지 않는다.

## 8. 다음에 구현할 단 하나의 첫 작업

첫 작업은 이것 하나로 고정한다.

> `frontend`에 MLightCAD `cad-simple-viewer` 기반 최소 뷰어를 만들고, 샘플 파일을 열어 `modelSpace.newIterator()`로 `objectId/type/layer/geometricExtents` 목록을 콘솔 또는 패널에 출력한다.

이 작업이 끝나야 이후 AI tool, 검수 로직, ACadSharp 로컬 파서 비교가 의미 있다.

완료 기준:

- `frontend` 개발 서버가 실행된다.
- 샘플 CAD 파일이 열린다.
- 레이어 목록이 표시된다.
- Model Space 엔티티 목록을 실제 DB에서 읽어온다.
- bbox 없는 객체는 실패 대신 warning으로 표시된다.
- 원본 파일 업로드 없이 로컬 브라우저에서 동작한다.

## 9. 참고 소스

- MLightCAD cad-viewer README: <https://github.com/mlightcad/cad-viewer>
- MLightCAD proprietary parser 문서: <https://github.com/mlightcad/cad-viewer/blob/main/PROPRIETARY-PARSER.md>
- MLightCAD RealDWG-Web README: <https://github.com/mlightcad/realdwg-web>
- ACadSharp README: <https://github.com/DomCR/ACadSharp>
- ACadSharp License: <https://github.com/DomCR/ACadSharp/blob/master/LICENSE>
