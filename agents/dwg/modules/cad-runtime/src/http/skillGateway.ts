import { randomUUID } from "node:crypto";
import type { IncomingMessage, ServerResponse } from "node:http";

import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";
import {
  parseSkillListResponse,
  parseSkillRunRequest,
  parseSkillRunResponse,
  type SkillListItem,
  type SkillRunResponse
} from "@dwg/contracts";
import {
  discoverCadSkills,
  loadCadSkillWorkflow,
  runCadSkillWorkflow,
  type InstalledCadSkill
} from "@dwg/skill-runtime";

const MAX_SKILL_REQUEST_BYTES = 64 * 1024;
const MAX_RECENT_STATUSES = 128;

export interface SkillGatewayDependencies {
  skillRoot: string;
  capabilities: CadCapabilityRuntime;
  capabilityVersion?: string;
}

export interface SkillGatewayRoutes {
  handle(
    request: IncomingMessage,
    response: ServerResponse,
    pathname: string,
    signal: AbortSignal
  ): Promise<boolean>;
}

interface RecentStatus {
  runId: string;
  status: SkillListItem["recentStatus"];
}

export function createSkillGatewayRoutes(dependencies: SkillGatewayDependencies): SkillGatewayRoutes {
  const statuses = new Map<string, RecentStatus>();
  const skills = discoverCadSkills(
    dependencies.skillRoot,
    (dependencies.capabilityVersion ?? "cad-capabilities/v1") as "cad-capabilities/v1"
  );

  return {
    async handle(request, response, pathname, signal) {
      if (request.method === "GET" && pathname === "/api/skills") {
        try {
          const installed = await skills;
          sendJson(response, 200, parseSkillListResponse({
            skills: installed.map((skill) => toListItem(skill, statuses))
          }));
        } catch {
          sendFailure(response, 500, "SKILL_LIST_UNAVAILABLE", "Installed skills are unavailable.");
        }
        return true;
      }
      if (request.method !== "POST" || pathname !== "/api/skills/run") return false;

      try {
        const run = parseSkillRunRequest(await readSkillJsonBody(request));
        const installed = await skills;
        const skill = installed.find((candidate) => candidate.manifest.id === run.skillId && candidate.manifest.version === run.version);
        if (!skill) throw new SkillGatewayError(404, "SKILL_NOT_FOUND", "Requested skill is not installed.");
        if (!skill.compatible) throw new SkillGatewayError(409, "SKILL_INCOMPATIBLE", "Requested skill is not executable.");

        const runId = randomUUID();
        const identity = skillIdentity(skill);
        setStatus(statuses, identity, { runId, status: "running" });
        try {
          const workflow = await loadCadSkillWorkflow(skill);
          const result = await runCadSkillWorkflow({
            skill,
            workflow,
            input: run.input,
            documentId: run.documentId,
            relatedDocumentIds: run.relatedDocumentIds,
            grantedPermissions: skill.manifest.permissions,
            capabilities: dependencies.capabilities,
            signal
          });
          const responseBody = responseForRun(runId, skill, result);
          setFinalStatus(statuses, identity, runId, responseBody.status);
          sendJson(response, 200, parseSkillRunResponse(responseBody));
        } catch {
          setFinalStatus(statuses, identity, runId, "failed");
          throw new SkillGatewayError(500, "SKILL_EXECUTION_FAILED", "Skill execution could not be completed.");
        }
      } catch (error) {
        const failure = toSkillGatewayFailure(error);
        sendFailure(response, failure.status, failure.code, failure.publicMessage);
      }
      return true;
    }
  };
}

function toListItem(skill: InstalledCadSkill, statuses: ReadonlyMap<string, RecentStatus>): SkillListItem {
  return {
    id: skill.manifest.id,
    version: skill.manifest.version,
    compatible: skill.compatible,
    permissions: [...skill.manifest.permissions],
    recentStatus: statuses.get(skillIdentity(skill))?.status ?? "idle"
  };
}

function responseForRun(runId: string, skill: InstalledCadSkill, result: Awaited<ReturnType<typeof runCadSkillWorkflow>>): SkillRunResponse {
  if (result.status !== "passed") {
    return {
      runId,
      skillId: skill.manifest.id,
      version: skill.manifest.version,
      status: "failed",
      previewId: null,
      changeCount: 0,
      warningCodes: failureCodes(result),
      result: null
    };
  }
  const final = result.steps.at(-1)?.output;
  return {
    runId,
    skillId: skill.manifest.id,
    version: skill.manifest.version,
    status: "passed",
    previewId: previewIdOf(final),
    changeCount: changeCountOf(final),
    warningCodes: [...result.warnings],
    result: final as SkillRunResponse["result"]
  };
}

function failureCodes(result: Awaited<ReturnType<typeof runCadSkillWorkflow>>): string[] {
  const output = result.steps.at(-1)?.output;
  const code = output !== null && typeof output === "object" && !Array.isArray(output)
    ? (output as { error?: { code?: unknown } }).error?.code
    : undefined;
  const codes = [...result.warnings, ...(typeof code === "string" ? [code] : [])];
  return [...new Set(codes.filter((item) => /^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)*$/.test(item)).slice(0, 64))];
}

function previewIdOf(value: unknown): string | null {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return null;
  const previewId = (value as { previewId?: unknown }).previewId;
  return typeof previewId === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(previewId) ? previewId : null;
}

function changeCountOf(value: unknown): number {
  if (value === null || typeof value !== "object" || Array.isArray(value)) return 0;
  const changeCount = (value as { changeCount?: unknown }).changeCount;
  return Number.isSafeInteger(changeCount) && (changeCount as number) >= 0 && (changeCount as number) <= 1_000_000 ? changeCount as number : 0;
}

function setStatus(statuses: Map<string, RecentStatus>, identity: string, status: RecentStatus): void {
  statuses.delete(identity);
  statuses.set(identity, status);
  while (statuses.size > MAX_RECENT_STATUSES) statuses.delete(statuses.keys().next().value!);
}

function setFinalStatus(statuses: Map<string, RecentStatus>, identity: string, runId: string, status: SkillRunResponse["status"]): void {
  if (statuses.get(identity)?.runId === runId) setStatus(statuses, identity, { runId, status });
}

function skillIdentity(skill: InstalledCadSkill): string {
  return `${skill.manifest.id}\u0000${skill.manifest.version}`;
}

async function readSkillJsonBody(request: IncomingMessage): Promise<unknown> {
  const declaredLength = Number(request.headers["content-length"] ?? "0");
  if (Number.isFinite(declaredLength) && declaredLength > MAX_SKILL_REQUEST_BYTES) {
    request.resume();
    throw new SkillGatewayError(413, "SKILL_REQUEST_TOO_LARGE", "Skill request exceeds the limit.");
  }
  return new Promise((resolveBody, reject) => {
    let size = 0;
    const chunks: Buffer[] = [];
    let settled = false;
    const fail = (error: SkillGatewayError) => {
      if (settled) return;
      settled = true;
      request.resume();
      reject(error);
    };
    request.on("aborted", () => fail(new SkillGatewayError(499, "SKILL_REQUEST_ABORTED", "Skill request was cancelled.")));
    request.on("error", () => fail(new SkillGatewayError(400, "SKILL_REQUEST_INVALID", "Invalid skill request.")));
    request.on("data", (chunk: Buffer) => {
      if (settled) return;
      size += chunk.length;
      if (size > MAX_SKILL_REQUEST_BYTES) return fail(new SkillGatewayError(413, "SKILL_REQUEST_TOO_LARGE", "Skill request exceeds the limit."));
      chunks.push(chunk);
    });
    request.on("end", () => {
      if (settled) return;
      settled = true;
      try {
        resolveBody(JSON.parse(Buffer.concat(chunks).toString("utf8")));
      } catch {
        reject(new SkillGatewayError(400, "SKILL_REQUEST_INVALID", "Invalid skill request."));
      }
    });
  });
}

class SkillGatewayError extends Error {
  constructor(readonly status: number, readonly code: string, readonly publicMessage: string) {
    super(publicMessage);
  }
}

function toSkillGatewayFailure(error: unknown): SkillGatewayError {
  if (error instanceof SkillGatewayError) return error;
  return new SkillGatewayError(400, "SKILL_REQUEST_INVALID", "Invalid skill request.");
}

function sendFailure(response: ServerResponse, status: number, code: string, message: string): void {
  sendJson(response, status, { error: { code, message } });
}

function sendJson(response: ServerResponse, status: number, value: unknown): void {
  if (response.destroyed || response.writableEnded) return;
  response.statusCode = status;
  response.end(JSON.stringify(value));
}
