# 2026-10-13 법규 소유자와 배치 적용

MasterPlan의 지상 주차도 LawAgent에서 지하 기본 프로필을 받던 경로를 수정했다. 법규 값은 `law/reference/data/structured/siting_design_rules.json`, 기준 선택은 `siting_rules.py`와 기존 masterplan `rules.py`가 소유한다. Agent에 법규 수치를 복제하지 않는다.

신규 provider `POST /api/v1/law/agent/siting-requirements`를 LawAgent `law_siting_requirements`로 노출한다. 연면적 합계와 용도를 명시적으로 받고 시설면적을 임의 전용하지 않는다. MasterPlan은 task ID와 필지·프로그램을 결속한다.

검증기 `legal_siting.py`는 접도 GIS 치수 관측과 법적 도로 판정을 구분한다. 법적 도로 공급자는 아직 없으므로 판정은 needs_evidence다. 주차 규칙 범위는 실제 설치 대수 및 지하·상층·필로티 여부로 다시 검증한다.

현재 조건부 도로 차로 사용·종렬 주차 생성과 소규모 건축물식 램프 적용 판정은 미완료. 데이터에 조건이 있다는 사실을 실제 생성기 완성으로 보고하지 않는다. 실제 668 대지 재생성에서 기존 대수·건물 면적 유지, 독립 기하 통과. 증거는 MasterPlan `docs/evidence/law-siting-20261013/README.md`와 `runs/law-siting-20261013/668`.
