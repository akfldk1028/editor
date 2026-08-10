interface DrawingSessionList {
  activeSessionId: string;
  sessions: Array<{
    id: string;
    displayName: string;
    drawingId: string;
    active: boolean;
  }>;
}

export async function registerPlanmDrawing(
  runId: string,
  drawingPath: string,
  displayName: string
): Promise<DrawingSessionList> {
  const response = await fetch("/api/drawings/register", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ path: `${runId}/${drawingPath}`, displayName }),
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({ error: {} }));
    throw new Error(body.error?.message ?? `DWG registration failed (${response.status})`);
  }
  return response.json() as Promise<DrawingSessionList>;
}
