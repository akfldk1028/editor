import { useDwgWorkspace } from "./DwgWorkspaceProvider";

/** Shown by any DWG piece while the drawing index is loading or failed to load. */
export function DwgLoadState() {
  const { error } = useDwgWorkspace();
  if (error) return <div className="load-state error-state">DWG 인덱스를 불러오지 못했습니다. {error}</div>;
  return <div className="load-state"><span className="loading-mark" /> 로컬 DWG 인덱스를 불러오는 중</div>;
}
