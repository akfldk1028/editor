import { useEffect, useMemo, useState } from "react";
import {
  approveAlternative,
  artifactUrl,
  createCadHandoff,
  createRun,
  footprintPolygon,
  getAlternatives,
  getRun,
  manifestUrl,
  inspectCadHandoff,
  previewUrl,
} from "./api";
import type {
  AlternativesResult,
  CadHandoff,
  DwgInspection,
  MassForm,
  PlanmRun,
  ShapeFamily,
  SprinklerState,
  TravelLimit,
} from "./types";
import { registerPlanmDrawing } from "../../integrations/dwg/api";

const stages = ["normalize", "analyze", "alternatives", "review", "deliver"];
const settledStatuses = ["delivered", "approved"];
const haltedStatuses = ["needs_input", "retryable", "blocked"];
const requiredAcceptedCount = 2;

const shapeFamilies: Array<{ value: ShapeFamily; label: string }> = [
  { value: "rectangle", label: "Rectangle" },
  { value: "l", label: "L" },
  { value: "t", label: "T" },
  { value: "u", label: "U" },
];

const travelLimits: Array<{ value: TravelLimit; label: string }> = [
  { value: "general_30", label: "General 30 m" },
  { value: "qualified_50", label: "Qualified 50 m" },
  { value: "highrise_residential_40", label: "High-rise residential 40 m" },
];

const sprinklerStates: Array<{ value: SprinklerState; label: string }> = [
  { value: "unknown", label: "Not asserted" },
  { value: "none", label: "None" },
  { value: "standard", label: "Standard" },
  { value: "qualifying", label: "Qualifying" },
];

// The screening only verifies analysis dates inside the checked ruleset window.
const earliestAnalysisDate = "2026-02-27";
const latestAnalysisDate = "2026-07-28";

const initialForm: MassForm = {
  projectId: "seongsu-corner",
  floors: 5,
  width: 30,
  depth: 12,
  shape: "rectangle",
  notchRatio: 0.3,
  commercialShare: 0.2,
  jurisdiction: "",
  effectiveDate: "",
  travelLimit: "",
  sprinkler: "unknown",
};

interface Props {
  onOpenDwg(): void;
}

function App({ onOpenDwg }: Props) {
  const [form, setForm] = useState(initialForm);
  const [run, setRun] = useState<PlanmRun | null>(null);
  const [alternatives, setAlternatives] = useState<AlternativesResult | null>(null);
  const [cadHandoff, setCadHandoff] = useState<CadHandoff | null>(null);
  const [dwgInspection, setDwgInspection] = useState<DwgInspection | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const completedStage = useMemo(() => {
    if (!run) return -1;
    if (settledStatuses.includes(run.status)) return stages.length - 1;
    return stages.indexOf(run.stage);
  }, [run]);

  useEffect(() => {
    if (!run || !["queued", "running"].includes(run.status)) return;
    const timer = window.setTimeout(async () => {
      try {
        const next = await getRun(run.run_id);
        setRun(next);
      } catch (reason) {
        setError(reason instanceof Error ? reason.message : "Status polling failed");
      }
    }, 900);
    return () => window.clearTimeout(timer);
  }, [run]);

  useEffect(() => {
    if (!run || alternatives) return;
    const halted = haltedStatuses.includes(run.status);
    if (!settledStatuses.includes(run.status) && !halted) return;
    let cancelled = false;
    getAlternatives(run.run_id)
      .then((value) => {
        if (!cancelled) setAlternatives(value);
      })
      .catch((reason) => {
        // A run halted before the alternatives stage has no summary to read.
        if (cancelled || halted) return;
        setError(reason instanceof Error ? reason.message : "Alternatives unavailable");
      });
    return () => {
      cancelled = true;
    };
  }, [run, alternatives]);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    setAlternatives(null);
    setCadHandoff(null);
    setDwgInspection(null);
    try {
      setRun(await createRun(form));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Run creation failed");
    } finally {
      setBusy(false);
    }
  }

  async function prepareCad() {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      setCadHandoff(await createCadHandoff(run.run_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "CAD handoff failed");
    } finally {
      setBusy(false);
    }
  }

  async function inspectCad() {
    if (!run || !cadHandoff) return;
    setBusy(true);
    setError(null);
    try {
      setDwgInspection(await inspectCadHandoff(run.run_id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "DWG inspection failed");
    } finally {
      setBusy(false);
    }
  }

  async function openInDwg() {
    if (!run || !cadHandoff) return;
    setBusy(true);
    setError(null);
    try {
      await registerPlanmDrawing(
        run.run_id,
        cadHandoff.drawing_path,
        `${run.project_id} / ${cadHandoff.alternative_id}`
      );
      onOpenDwg();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "DWG session registration failed");
    } finally {
      setBusy(false);
    }
  }

  async function approve(alternativeId: string) {
    if (!run) return;
    setBusy(true);
    setError(null);
    try {
      setRun(await approveAlternative(run.run_id, alternativeId));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Approval failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <main className="shell">
      <header className="masthead reveal">
        <a className="brand" href="#top" aria-label="PLANM home">
          <span className="brand-mark">P/M</span>
          <span>PLANM Concept Studio</span>
        </a>
        <div className="system-state"><span /> Evidence-first planning</div>
      </header>

      <section className="hero reveal delay-1" id="top">
        <p className="eyebrow">Mass to verified alternatives</p>
        <h1>Plans with proof.</h1>
        <p className="hero-copy">
          Generate distinct building concepts, inspect the validation evidence,
          and approve only what survives the review loop.
        </p>
      </section>

      <div className="workspace">
        <aside className="brief-panel reveal delay-2">
          <div className="section-label"><span>01</span> Project brief</div>
          <form onSubmit={submit}>
            <label>
              Project ID
              <input value={form.projectId} onChange={(event) => setForm({ ...form, projectId: event.target.value })} required />
            </label>
            <div className="field-pair">
              <label>Floors<input type="number" min="1" max="40" value={form.floors} onChange={(event) => setForm({ ...form, floors: Number(event.target.value) })} /></label>
              <label>Commercial %<input type="number" min="0" max="100" value={Math.round(form.commercialShare * 100)} onChange={(event) => setForm({ ...form, commercialShare: Number(event.target.value) / 100 })} /></label>
            </div>
            <div className="field-pair">
              <label>Width <small>m</small><input type="number" min="8" max="120" value={form.width} onChange={(event) => setForm({ ...form, width: Number(event.target.value) })} /></label>
              <label>Depth <small>m</small><input type="number" min="8" max="120" value={form.depth} onChange={(event) => setForm({ ...form, depth: Number(event.target.value) })} /></label>
            </div>
            <div className="field-pair">
              <label>
                Plate shape
                <select value={form.shape} onChange={(event) => setForm({ ...form, shape: event.target.value as ShapeFamily })}>
                  {shapeFamilies.map((family) => (
                    <option key={family.value} value={family.value}>{family.label}</option>
                  ))}
                </select>
              </label>
              {form.shape !== "rectangle" && (
                <label>
                  Cut ratio <small>% of plate</small>
                  <input type="number" min="15" max="45" value={Math.round(form.notchRatio * 100)} onChange={(event) => setForm({ ...form, notchRatio: Number(event.target.value) / 100 })} />
                </label>
              )}
            </div>
            <PlatePreview form={form} />
            <div className="code-facts">
              <h4>Code facts <small>only an asserted fact is screened</small></h4>
              <label>
                Jurisdiction
                <select value={form.jurisdiction} onChange={(event) => setForm({ ...form, jurisdiction: event.target.value })}>
                  <option value="">Not asserted</option>
                  <option value="KR">KR — Republic of Korea</option>
                </select>
              </label>
              <label>
                Analysis as-of date
                <input type="date" min={earliestAnalysisDate} max={latestAnalysisDate} value={form.effectiveDate} onChange={(event) => setForm({ ...form, effectiveDate: event.target.value })} />
              </label>
              <label>
                Travel limit
                <select value={form.travelLimit} onChange={(event) => setForm({ ...form, travelLimit: event.target.value as TravelLimit | "" })}>
                  <option value="">Not asserted</option>
                  {travelLimits.map((limit) => (
                    <option key={limit.value} value={limit.value}>{limit.label}</option>
                  ))}
                </select>
              </label>
              <label>
                Sprinkler protection
                <select value={form.sprinkler} onChange={(event) => setForm({ ...form, sprinkler: event.target.value as SprinklerState })}>
                  {sprinklerStates.map((state) => (
                    <option key={state.value} value={state.value}>{state.label}</option>
                  ))}
                </select>
              </label>
            </div>
            <button className="primary-action" disabled={busy} type="submit">
              {busy ? "Starting run…" : "Generate alternatives"}<span>↗</span>
            </button>
          </form>
        </aside>

        <section className="results-panel reveal delay-3" aria-live="polite">
          <div className="section-label"><span>02</span> Review board</div>
          {error && <div className="error-banner">{error}</div>}
          {!run && <EmptyBoard />}
          {run && (
            <>
              <div className="run-header">
                <div><p>Run {run.run_id.slice(0, 8)}</p><h2>{run.project_id}</h2></div>
                <StatusPill status={run.status} />
              </div>
              <ol className="stage-rail">
                {stages.map((stage, index) => (
                  <li className={index <= completedStage ? "complete" : ""} key={stage}>
                    <span>{String(index + 1).padStart(2, "0")}</span>{stage}
                  </li>
                ))}
              </ol>
              {(run.unresolved_facts?.length ?? 0) > 0 && (
                <div className="unresolved-facts">
                  <span>Unresolved code facts</span>
                  <ul>
                    {run.unresolved_facts?.map((fact) => (
                      <li key={fact}>{fact}</li>
                    ))}
                  </ul>
                </div>
              )}
              {haltedStatuses.includes(run.status) && (
                <HaltEvidence run={run} alternatives={alternatives} />
              )}
              {alternatives && (
                <div className="alternatives-grid">
                  {alternatives.alternatives.filter((item) => item.accepted).map((item, index) => (
                    <article className="alternative-card" style={{ "--order": index } as React.CSSProperties} key={item.alternative_id}>
                      <div className="drawing-frame">
                        <img src={previewUrl(run.run_id, item.alternative_id)} alt={`${item.alternative_id} first-floor plan`} />
                        <span className="rank">#{item.rank}</span>
                      </div>
                      <div className="card-body">
                        <div className="card-title"><h3>{item.alternative_id}</h3><strong>{Math.round(item.score * 100)}</strong></div>
                        <p>{item.strategy.replaceAll("-", " ")}</p>
                        <div className="checks">
                          <span>Geometry <b>{item.internal_validation}</b></span>
                          <span>Render <b>{item.render_validation}</b></span>
                          <span>Code <b className={item.regulatory_screening === "not_checked" ? "pending" : ""}>{item.regulatory_screening}</b></span>
                        </div>
                        <button disabled={busy || run.status !== "delivered"} onClick={() => approve(item.alternative_id)} aria-label={`Approve ${item.alternative_id}`}>
                          {run.approved_alternative_id === item.alternative_id ? "Selected" : "Approve concept"}
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              )}
              {run.status === "approved" && (
                <>
                  <div className="delivery-banner">
                    <div><span>Approval recorded</span><h3>Approved for delivery</h3><p>{run.approved_alternative_id}</p></div>
                    <a href={manifestUrl(run.run_id)} download>Download delivery manifest</a>
                  </div>
                  <section className="cad-capability" aria-label="Optional CAD capability">
                    <div className="cad-heading">
                      <div><span>Optional capability</span><h3>CAD handoff</h3></div>
                      <strong>{dwgInspection ? "DWG verified" : cadHandoff ? "DXF ready" : "Not started"}</strong>
                    </div>
                    <p>Prepare the approved geometry as layered DXF, then inspect it through the independent DWG Agent.</p>
                    <div className="cad-actions">
                      <button disabled={busy} onClick={prepareCad}>Prepare layered DXF</button>
                      <button disabled={busy || !cadHandoff} onClick={inspectCad}>Run DWG inspection</button>
                      <button disabled={busy || !cadHandoff} onClick={openInDwg}>Open in DWG workspace</button>
                      {cadHandoff && <a href={artifactUrl(run.run_id, cadHandoff.drawing_path)} download>Download DXF</a>}
                    </div>
                    {cadHandoff && <small>{cadHandoff.source_floor_count} floors / {cadHandoff.entity_count} entities / {cadHandoff.units}</small>}
                    {dwgInspection && <small>{dwgInspection.evidence.result.matches.length} grounded entities on {dwgInspection.layer}; {dwgInspection.evidence.warning_codes.length} warnings</small>}
                  </section>
                </>
              )}
            </>
          )}
        </section>
      </div>
    </main>
  );
}

function PlatePreview({ form }: { form: MassForm }) {
  const points = footprintPolygon(form);
  const width = Math.max(...points.map(([x]) => x));
  const depth = Math.max(...points.map(([, y]) => y));
  // Drawn y-up, so the street frontage on edge 0 sits along the bottom.
  const outline = points.map(([x, y]) => `${x},${depth - y}`).join(" ");
  const area =
    Math.abs(
      points.reduce((sum, [x, y], index) => {
        const [nextX, nextY] = points[(index + 1) % points.length];
        return sum + (x * nextY - nextX * y);
      }, 0)
    ) / 2;
  return (
    <div className="mass-diagram" aria-label="Building mass diagram">
      <svg viewBox={`-2 -2 ${width + 4} ${depth + 4}`} preserveAspectRatio="xMidYMid meet" role="img" aria-label={`${form.shape} plate`}>
        <polygon points={outline} />
        <line x1="0" y1={depth} x2={width} y2={depth} />
      </svg>
      <span>{width} × {depth} m · {Math.round(area)} m² · street on edge 0</span>
    </div>
  );
}

function HaltEvidence({
  run,
  alternatives,
}: {
  run: PlanmRun;
  alternatives: AlternativesResult | null;
}) {
  const violations = run.violations ?? [];
  const rejected = alternatives?.rejected_families ?? [];
  return (
    <section className="halt-evidence" aria-label="Halt evidence">
      <div className="halt-heading">
        <div>
          <span>Halted at {run.stage}</span>
          <h3>
            {alternatives
              ? `This mass reached ${alternatives.accepted_count} of ${requiredAcceptedCount} accepted alternatives.`
              : "The run stopped before it produced alternatives."}
          </h3>
        </div>
      </div>
      {violations.length > 0 && (
        <ul className="violation-list">
          {violations.map((violation) => (
            <li key={violation.code}>
              <code>{violation.code}</code>
              <p>{violation.message}</p>
            </li>
          ))}
        </ul>
      )}
      {rejected.length > 0 && (
        <div className="rejected-families">
          <h4>Refused core families</h4>
          <ul>
            {rejected.map((family) => (
              <li key={family.family}>
                <strong>{family.family}</strong>
                {family.reasons.map((reason) => (
                  <span key={reason}>{reason}</span>
                ))}
              </li>
            ))}
          </ul>
        </div>
      )}
    </section>
  );
}

function EmptyBoard() {
  return <div className="empty-board"><div className="axis x" /><div className="axis y" /><span>A</span><span>B</span><p>Submit a mass brief to begin the evidence loop.</p></div>;
}

function StatusPill({ status }: { status: string }) {
  return <span className={`status-pill status-${status}`}><i />{status.replace("_", " ")}</span>;
}

export default App;
