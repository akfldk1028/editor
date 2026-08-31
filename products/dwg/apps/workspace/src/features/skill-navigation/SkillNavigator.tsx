import { AlertCircle, CheckCircle2, Circle, LoaderCircle, ShieldAlert, XCircle } from "lucide-react";
import { useEffect, useState } from "react";

import type { SkillListItem, SkillPermission } from "@dwg/contracts";

import { loadSkills } from "../../shared/api/skillClient";
import "./styles.css";

type LoadState =
  | { kind: "loading" }
  | { kind: "ready"; skills: SkillListItem[] }
  | { kind: "error"; message: string };

interface Props { query: string; }

export function SkillNavigator({ query }: Props) {
  const [state, setState] = useState<LoadState>({ kind: "loading" });
  const normalizedQuery = query.trim().toLocaleLowerCase();

  useEffect(() => {
    const controller = new AbortController();
    setState({ kind: "loading" });
    loadSkills(controller.signal)
      .then((response) => setState({ kind: "ready", skills: response.skills }))
      .catch((error: Error) => {
        if (error.name !== "AbortError") setState({ kind: "error", message: error.message });
      });
    return () => controller.abort();
  }, []);

  if (state.kind === "loading") return <section aria-label="Skills" className="skill-navigation" role="region"><div className="skill-navigation-state"><LoaderCircle className="spin" size={14} />Loading skills…</div></section>;
  if (state.kind === "error") return <section aria-label="Skills" className="skill-navigation" role="region"><div className="skill-navigation-state error"><AlertCircle size={14} />Unable to load skills: {state.message}</div></section>;

  const skills = state.skills.filter((skill) => skill.id.toLocaleLowerCase().includes(normalizedQuery));
  return (
    <section aria-label="Skills" className="skill-navigation" role="region">
      <div className="skill-navigation-scroll">
        {skills.map((skill) => <SkillRow key={`${skill.id}:${skill.version}`} skill={skill} />)}
        {skills.length === 0 && <div className="skill-navigation-state">No skills available.</div>}
      </div>
    </section>
  );
}

function SkillRow({ skill }: { skill: SkillListItem }) {
  return <article className={`skill-navigation-row ${skill.compatible ? "" : "incompatible"}`}>
    <div><strong title={skill.id}>{skill.id}</strong><small>v{skill.version}</small></div>
    <span className={`skill-compatibility ${skill.compatible ? "compatible" : "incompatible"}`}>{skill.compatible ? <CheckCircle2 size={12} /> : <ShieldAlert size={12} />}{skill.compatible ? "Compatible" : "Incompatible"}</span>
    <div className="skill-permissions">{skill.permissions.map((permission) => <Permission key={permission} permission={permission} />)}</div>
    <span className={`skill-status ${skill.recentStatus}`}>{statusIcon(skill.recentStatus)}{capitalize(skill.recentStatus)}</span>
  </article>;
}

function Permission({ permission }: { permission: SkillPermission }) { return <span>{permission}</span>; }

function statusIcon(status: SkillListItem["recentStatus"]) {
  if (status === "passed") return <CheckCircle2 size={12} />;
  if (status === "failed") return <XCircle size={12} />;
  if (status === "running") return <LoaderCircle className="spin" size={12} />;
  return <Circle size={12} />;
}

function capitalize(value: string) { return `${value.slice(0, 1).toUpperCase()}${value.slice(1)}`; }
