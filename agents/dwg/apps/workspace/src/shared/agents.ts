export const agents = [
  { id: "orchestrator", label: "Orchestrator", role: "요청 분해 및 최종 응답", state: "active" },
  { id: "drawing-index-agent", label: "Drawing Index", role: "DWG 인덱스 준비", state: "active" },
  { id: "search-agent", label: "Search", role: "객체 및 텍스트 검색", state: "active" },
  { id: "evidence-agent", label: "Evidence", role: "근거 완전성 검증", state: "active" },
  { id: "rule-check-agent", label: "Rule Check", role: "결정적 규칙 검사", state: "planned" },
  { id: "viewer-agent", label: "Viewer", role: "선택 및 줌 연결", state: "planned" },
  { id: "report-agent", label: "Report", role: "사이드카 보고서", state: "planned" }
] as const;
