# 법규 검토 이후 요구사항 설계 의도 프로그램 연결 설계

2026-10-09 설계 제안. 대상은 editor와 Orchestrator 및 Requirement, DesignIntent, Program의 연결이다. 구현·배포 완료를 의미하지 않는다. Law 화면과 엔진은 다른 세션에서 수정 중이므로 이 문서는 그 구현을 변경하지 않는다.

사용자의 핵심 요구는 연결이다. 법규 결과를 본 사용자가 같은 대화에서 건축 목적과 설계 생각을 말하면, 필요한 담당이 참여하고 결과가 다음 담당에게 실제 입력으로 전달되어야 한다. 건축사와 클라이언트를 고정 순서로 분기하거나 건물 용도·질문·면적을 에디터에 하드코딩하지 않는다.

## 확인한 현재 구조

| 위치 | 확인한 동작 | 연결에 필요한 변화 |
|---|---|---|
| editor `backend/app/modules/platform/goals.py`, `schemas/site_run.py` | 로컬 목표 목록 및 limits 중심 제출 계약 | Orchestrator 소유 capabilities와 입력 계약을 소비 |
| editor `modules/platform/situation.py` | 대지·날짜·목표·에이전트 상태를 판단기에 전달 | 대화 이력, 현재 owner 상태, 미응답 질문과 제안 버전 연결 |
| editor `modules/platform/routing/__init__.py` | 모델이 담당을 골라도 default_goal로 변환; 키워드 fallback 존재 | 실제 다음 행동과 인자를 owner 계약에 연결; 모델 실패 시 임의 라우팅 금지 |
| Orchestrator `orchestrator/editor_goals.py` | capabilities, program·intent·masterplan·mass 등 제공 | editor의 중복 목록을 제거할 기준으로 사용 |
| Orchestrator `orchestrator/ask/__init__.py` | 질문 판단과 handoff; 현재 전문 도구 직접 호출은 Law 읽기 작업 중심 | 대화에서 초안 작성·확인·실행·재개를 연결하는 조정 기능 필요 |
| Orchestrator `program_flow.py` | Program 번역, 누락 입력 interrupt, 변경된 입력 버전 거부 | 내부 Program 요청 객체를 사용자에게 요구하지 않고 담당의 대화로 해결 |
| Orchestrator `editor_runs.py`, `editor_api.py` | 실행 제출·조회·resume 존재 | editor까지 입력 요청과 답변 연결 |
| Requirement `requirementagent/brief.py`, `a2a_service/tools.py` | 선언·가정·미정·모순 검사; 원문에서 값 추출 안 함 | 담당 모델이 원문 근거가 있는 구조화 초안을 제안하는 단계 필요 |
| DesignIntent `designintentagent/intent.py` | 선언된 의도와 술어 보관·검사; 형상 생성 안 함 | 담당 모델의 개념 대화·제안과 선언 도구를 연결 |
| Program `docs/tool-contract.md` | profile catalog, typology, from_brief, build, immutable revisions | 사용자가 실 목록을 모두 작성하지 않아도 담당이 근거 있는 프로그램 초안을 제안 |

파일들은 다른 세션에서도 변경되고 있다. 구현 직전에 계약과 diff를 재확인한다. 위 내용은 소스 관찰이며 라이브 배포 상태 판정이 아니다.

## 조사 근거와 적용

- [RIBA Plan of Work 2020](https://www.riba.org/media/sszn5kkt/2020ribaplanofworktemplatepdf.pdf)는 Client Requirements, Project Brief, Architectural Concept를 구분하고 개념 단계에서 브리프 변경 합의와 사용자 검토를 둔다. 적용: 요구·개념·공간 프로그램을 서로 다른 산출물로 유지하고 수정 관계를 추적한다. 영국의 실무 단계 자료이며 국내 법규 판정 근거로 쓰지 않는다.
- [Microsoft Magentic orchestration](https://learn.microsoft.com/en-us/agent-framework/workflows/orchestrations/magentic)은 진행 원장에 진행 여부·반복·다음 발언자·지시를 기록하고 재계획을 지원한다. 적용: 한 번의 키워드 분류 대신 상태를 읽는 반복 조정을 사용한다. 기존 LangGraph를 교체하는 요구는 아니다.
- [A2A task lifecycle](https://a2a-protocol.org/latest/topics/life-of-a-task/)은 contextId로 관련 작업을 묶고 입력 대기와 후속 task를 구분한다. 적용: 입력 대기는 같은 작업에 응답하고, 완료된 작업의 수정은 이전 산출물을 참조하는 새 작업으로 기록한다. contextId 자체가 대화나 프로젝트의 영속 저장을 대신하지 않는다.
- [LangGraph interrupts](https://docs.langchain.com/oss/python/langgraph/interrupts)는 checkpoint와 thread를 통한 중단·재개를 제공한다. 적용: 이미 있는 실행 저장소와 resume를 재사용한다. 재개 시 노드 재실행을 고려해 중복 호출·중복 발행을 막는다.
- [A2A specification](https://a2a-protocol.org/latest/specification/)의 Agent Card는 발견과 역량 설명에 사용한다. 설명이나 MIME type을 실행 인자 스키마로 간주하지 않는다. 실제 검증 가능한 도구 스키마는 각 owner의 기존 도구 계약에서 버전과 함께 제공해야 한다.

## 선택한 연결 방식

고정 마법사는 역할·용도가 달라지면 질문을 중복하고 중간 수정에 약하다. 에이전트끼리 자유롭게 상태를 수정하는 방식은 소유권과 변경 추적을 깨뜨린다. 따라서 **Orchestrator의 동적 조정과 각 owner의 검증된 도구를 결합**한다.

Orchestrator는 누가 무엇을 해야 하는지와 의존 관계를 정한다. 요구사항 해석·설계 개념·공간 배분의 전문 판단은 담당 모델이 수행한다. 코드에는 프로젝트 격리, 권한, 타입, 단위, 버전, 중복 실행 방지와 owner 검증을 남긴다. 질문 내용이나 건물 용도별 설계 순서는 코드로 고정하지 않는다.

모델을 사용할 수 없으면 처리 불가 상태와 재시도를 제공한다. 사용자가 명시적으로 고른 작업은 검증 후 실행할 수 있지만, 키워드 표로 사용자의 의도를 대신 확정하지 않는다. 예산·시간·반복 제한에 도달하면 현재 산출물과 막힌 이유를 보존한다.

## 사용자에 따른 대화

건축사·클라이언트는 사용자가 밝힌 역할과 설명 선호로 기록한다. 역할은 질문의 표현과 상세 수준에 영향을 주며, 결정 권한이나 다음 에이전트를 자동 확정하지 않는다. 같은 사람도 요구를 제시하고 개념을 설계할 수 있다.

| 현재 맥락의 예 | 필요한 담당의 관점 | 사용자에게 남는 결과 |
|---|---|---|
| 클라이언트가 용도를 정하지 못함 | Requirement가 목적·이용자·운영을 확인하고 Program에 운영 유형 후보 탐색 요청 | 요구 초안, 선택 가능한 운영 방향, 미정 질문 |
| 클라이언트가 조용하지만 열린 공간을 원함 | Requirement는 운영·성능 요구를 보존; DesignIntent는 이를 해석한 공간 개념을 제안 | 원문 요구와 개념 제안을 구분한 카드 |
| 건축사가 기존 프로그램과 중정 개념을 제시 | Program이 기존 표의 단위·근거·현재성을 확인; DesignIntent가 개념을 선언 | 반복 질문 없는 기존 자료 연결, 의도 버전 |
| 업무시설 같은 넓은 용도만 제시 | Program이 실제 catalog에서 운영 후보를 반환; Law가 법정 분류와 적용성 판단 | 사용 목적과 법정 용도를 구분한 선택 |
| 사용자가 인원·예산·규모를 변경 | Requirement가 변경분을 기록하고 Program·Intent·Law의 영향 검토 요청 | 이전 안과 달라진 항목, 다시 확인할 결정 |

위 표는 평가용 사례다. 그대로 분기문이나 고정 질문 문구로 구현하지 않는다. 이미 답한 내용은 재질문하지 않고, 모르겠다는 답은 unknown으로 유지한다. 제안 가능한 항목은 담당이 가정과 근거를 밝힌 대안을 낸다.

## 매 턴의 처리

1. 사용자 메시지를 project·branch·conversation에 저장한다. 파일이나 조항을 참조했다면 해당 산출물 ID와 버전을 함께 기록한다.
2. Orchestrator는 최근 대화와 원문 참조, 현재 requirements·design_intent·program·법규 검토, 진행 중 task, 미응답 질문, capabilities를 읽는다. 이 요약은 owner의 원본 상태를 대체하지 않는다.
3. 모델은 답변·담당 위임·정보 요청·초안 제안·실행 또는 재개 중 필요한 행동과 근거를 제안한다. 실행할 수 있는 행동은 등록된 계약으로 검증한다. 둘 이상의 담당이 필요하면 의존 관계를 명시한다.
4. 담당 모델이 자기 도구로 근거와 현재 상태를 확인하고 제안을 반환한다. 원문에 없는 수치는 사용자 사실로 저장하지 않는다. "200명 정도"는 근사라는 의미까지 유지한다.
5. 사용자가 직접 말한 명확한 조건은 원문 근거를 붙여 반영한다. 해석이 필요한 내용이나 설계 대안은 제안 상태로 보여준다. 사용자 선택이 필요한 변경만 묻고 매 턴 형식적 승인 버튼을 강제하지 않는다.
6. owner가 검사한 변경을 Orchestrator의 기존 publication 경로로 저장한다. raw brief, declared facts, assumptions, unknowns와 proposed·accepted 구분을 보존한다.
7. 결과 이벤트가 대화와 오른쪽 작업 화면을 함께 갱신한다. 다음 모델 판단은 갱신된 상태와 남은 질문에서 시작한다. 명확한 종료·대기 조건 없이 자동 대화를 이어가지 않는다.

중앙 대화에는 실제 수행한 담당과 결과만 표시한다. Orchestrator가 생성한 설명을 아직 호출하지 않은 Agent의 답변으로 꾸미지 않는다.

## 기존 도구와 새로 필요한 대화 계층

Requirement의 `requirement_structure`는 자연어 자유 대화 API가 아니다. 담당 모델이 원문과 연결된 declared·assumptions·unknowns 초안을 만들고, 기존 도구가 검사한 결과를 사용한다. Program이나 editor가 요구사항을 대신 바꾸지 않는다.

DesignIntent는 파르티, 공간 질서, 외부 관계, 재료 태도와 대안을 자기 모델에서 제안한다. 선택된 의도를 `intent_declare`로 기록한다. 실제로 측정 가능한 항목만 non_negotiables로 연결하고, 평가 불가능한 산문은 미검증으로 보존한다. 자연어를 임의의 기하 지표로 단정하지 않는다.

Program은 `program_profile_catalog` → 필요한 profile/자료 조회 → `program_from_brief` 또는 직접 저작 → `program_build`의 기존 기능을 담당 판단으로 사용한다. catalog 선택은 고정 직렬 순서를 강제하는 제품 마법사가 아니다. 기존 프로그램을 받으면 필요한 확인만 한다. 미지원 유형은 custom profile 제안과 근거 확보로 처리하며 비슷한 유형에 몰래 매핑하지 않는다.

기존 A2A tool service와 담당의 GitAgent 모델 실행 경로가 실제로 연결되는지 먼저 확인한다. 없다면 해당 owner의 conversation capability를 추가해야 한다. editor에서 세 에이전트의 전문 프롬프트를 복제하거나 Orchestrator가 대신 프로그램을 작성하지 않는다.

## 연결 계약 제안

아래는 새 제품 연결에 필요한 의미 계약이며 현재 존재하는 API 필드라고 주장하지 않는다. 기존의 동등한 계약은 재사용한다.

| 연결 | 보존할 정보 |
|---|---|
| 사용자 메시지 | project, branch, conversation_id, message_id, text, 첨부·산출물 참조, 응답할 question/task 식별자 |
| 작업 지시 | owner, capability와 schema version, 원문 참조, input_versions, 현재 산출물 참조, 수행 목적 |
| 담당 답변 | 실제 task/owner, 설명, proposal 또는 artifact 참조, missing inputs, 선택 후보, 원문·자료 근거 |
| 미응답 질문 | question_id, owner, task/run, 요청 필드와 스키마, 묻는 이유, 질문이 생성된 상태 버전 |
| 사용자 결정 | 선택한 proposal/version 또는 질문 ID, 사용자 응답, 적용 대상과 기대 버전 |
| 발행 이벤트 | event_id, project/branch, owner, artifact/revision, 원인이 된 메시지·실행, 변경·미해결 항목 |

동일한 A2A contextId를 모든 서버의 task ID와 혼동하지 않는다. 제품 대화 ID와 owner별 context/task 대응을 Orchestrator에 보존한다. 완료된 작업은 다시 열지 않고 후속 작업으로 연결한다.

resume 응답은 질문이 생성된 snapshot과 대조한다. 그 사이 Program 또는 대지가 바뀌면 오래된 답을 새 상태에 적용하지 않고 영향만 설명해 다시 판단한다. double click, 재전송, 재개 후 노드 재실행은 idempotency로 한 번의 발행만 만든다.

## Law 세션과 접점

법규 검토 응답·산출물은 원본 소유자, project/branch, 대지, 기준일, 용도 조건, 버전, 결과와 미해결 근거를 보존한 참조로 연결한다. 표시용 통신 로그는 길이 제한·생략이 있으므로 다음 단계의 정본 입력으로 사용하지 않는다.

"법규 완료"를 전역 통과 상태로 취급하지 않는다. 요구 대화나 개념 탐색은 미확인 근거를 유지하며 진행할 수 있다. 특정 형상 생성·검증이 가능한지는 해당 실행의 owner 전제 조건으로 결정한다. 용도나 규모가 바뀌면 영향을 받는 Law 결과를 재검토 대상으로 표시한다.

법규 결과 도착은 Orchestrator가 다음 행동을 검토하는 이벤트다. 같은 result/version에 대해 다음 질문이 반복 생성되지 않도록 한다. 이미 프로그램·의도가 있으면 처음부터 용도를 묻지 않는다. 다음 질문 문장은 저장된 결과와 상태로 생성한다.

현재 Law 세션이 수정하는 `useAsk`, `commands`, `types`, `api`, agent lines는 공통 접점이다. 구현 전 최신 변경을 읽고 기존 조항 질문 연결을 포함해 이행한다. 설계 검토 중 다른 세션에 메시지를 보내거나 그 파일을 수정하지 않았다.

## 화면과 지속성

현재 셸을 사용한다. 대화 옆에는 요구사항·설계 의도·공간 프로그램 산출물을 각각 열 수 있게 한다. 미정·가정·제안·사용자 선택과 변경 이력을 보여준다. 화면의 선택지는 담당이 반환한 제안에서 만들며 에디터의 용도 enum이나 면적 기본값에서 만들지 않는다.

프로젝트 전환과 새로고침 후에도 대화, 질문, 선택한 안, 실행 상태를 복구한다. 기존 feed store는 표시용으로 사용할 수 있지만 정본은 서버의 대화·실행·산출물 기록이다. 합성 이벤트와 실제 tool 결과를 구분하고 발행 이벤트 중복을 제거한다.

## 구현 순서와 완료 기준

1. Orchestrator capabilities·ask·resume의 현재 계약 및 배포 상태를 읽기 호출로 검증한다. editor 로컬 목표 목록과 비교하고 Law 변경을 포함한 이행 계약을 확정한다.
2. 프로젝트 대화의 영속 ID·이력·owner snapshot·미응답 질문을 기존 상태 저장소에 연결한다. 기본 목표 하나로 떨어지는 라우팅과 키워드 fallback을 제품 경로에서 대체한다.
3. 세 owner의 대화 모델과 기존 검증 도구를 연결한다. Requirement의 부분 수집은 시설면적이 미정이어도 가능해야 하며, 기존 생성 단계의 필수 조건 검사를 우회해서는 안 된다.
4. 최초 수직 시나리오를 연결한다: Law 결과 → 실제 Requirement 질문 → 사용자 답 → 원문 근거가 있는 변경 저장 → Program 후보/초안 → 같은 프로젝트 화면 표시.
5. DesignIntent의 선행 입력·동시 제안·기존 개념 수입을 연결하고, Program 변경 시 의도 재확인 및 기존 downstream 변경 추적을 연결한다.
6. 배치로 넘길 때 현재 requirements·intent·program·Law 입력 버전을 한 실행에 묶는다. 부분 결과를 전체 승인으로 바꾸지 않는다.

완료 판정은 버튼 표시나 mock 성공으로 하지 않는다. 다음은 연결 평가 시나리오다.

- 처음 온 클라이언트: 용도가 미정이어도 담당 질문과 운영 후보 제안으로 진행한다.
- 기존 프로그램이 있는 건축사: 알고 있는 용도·면적을 반복 질문하지 않고 개념 대화로 진입한다.
- 요구와 의도가 섞인 한 문장: 양쪽 산출물이 같은 원문을 참조한다.
- 새로운 용도: editor 소스 변경 없이 owner catalog를 이용하거나 근거 부족을 설명한다.
- 미정 면적: 임의 기본값을 만들지 않고 탐색은 진행하며 생성의 필수 조건은 유지한다.
- 사용자 수정: 수량·운영 방식 변경이 Program과 필요한 Law·Intent 재검토로 이어진다.
- 늦은 응답·더블 클릭·재시작: 잘못된 버전 발행과 중복 task/발행이 없다.
- 새로고침·프로젝트 전환: 이전 질문과 산출물 복구, 다른 프로젝트 입력 혼입 없음.
- 모델 또는 owner 장애: 실제 실패와 재시도를 표시하며 가짜 답변·키워드 자동 결정 없음.
- 입력이 충분한 실제 A2A 시나리오: 세 owner의 task와 산출물 revision을 추적할 수 있고 다음 설계 실행이 그 정확한 revision을 소비한다.

모델 평가는 정해진 질문 문구 일치가 아니라 담당 선택의 근거, 질문의 필요성, 원문 보존, 미정값 보존, 실제 호출과 산출물 연결로 판정한다. 이 문서 작성 시 이 시나리오들은 실행하지 않았다.
