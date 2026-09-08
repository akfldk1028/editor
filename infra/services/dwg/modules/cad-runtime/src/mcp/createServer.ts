import {
  McpServer,
  ResourceTemplate
} from "@modelcontextprotocol/sdk/server/mcp.js";

import type { CadCapabilityRuntime } from "@dwg/cad-capabilities";
import {
  parseCadDrawingExportResponse,
  parseCadOutputVerification,
  parseCadReportExportResponse,
  type CadReportExportResponse
} from "@dwg/contracts";

import { executeCadTool } from "../application/cad-tools/runtime.js";
import { CAD_TOOL_DEFINITIONS } from "./toolDefinitions.js";

type ToolArguments = Record<string, unknown>;
type ReportToolContent =
  | { type: "text"; text: string }
  | {
      type: "resource_link";
      uri: string;
      name: string;
      mimeType: string;
    };
type ReportResource = {
  format: "json" | "csv" | "pdf" | "svg";
  mediaType: string;
  filename: string;
  bytes: Uint8Array;
  sha256: string;
};
type McpExportServices = {
  requestDestinationGrant?(signal?: AbortSignal): Promise<unknown>;
  createReportDownload?(input: unknown, signal?: AbortSignal): Promise<CadReportExportResponse>;
  consumeReportDownload?(downloadId: string): ReportResource | null;
  displayDirectory?: string;
};
const reportResourceIdPattern =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;

export function createCadMcpServer(
  runtime: CadCapabilityRuntime,
  services: McpExportServices = {}
): McpServer {
  const server = new McpServer({
    name: "dwg-intelligence",
    version: "0.1.0"
  });

  registerReportResource(server, services);

  for (const definition of CAD_TOOL_DEFINITIONS) {
    server.registerTool(
      definition.name,
      {
        description: definition.description,
        inputSchema: definition.inputSchema,
        annotations: {
          readOnlyHint: !definition.name.includes("export_drawing")
            && definition.name !== "cad_request_export_destination",
          destructiveHint: false,
          idempotentHint: !definition.name.includes("export_drawing")
            && definition.name !== "cad_request_export_destination",
          openWorldHint: false
        }
      },
      async (args, extra) => {
        try {
          const result = definition.name === "cad_request_export_destination"
            ? await requestExportDestination(server, services, extra.signal)
            : definition.name === "cad_export_report"
              ? await requestReportDownload(services, args, extra.signal)
              : definition.name === "cad_export_drawing"
                ? publicDrawingResponse(await executeCadTool(
                    runtime,
                    definition.name,
                    args as ToolArguments,
                    extra.signal
                  ))
                : await executeCadTool(
                runtime,
                definition.name,
                args as ToolArguments,
                extra.signal
              );
          const structuredContent = asStructuredContent(result);

          const content: ReportToolContent[] = [{
            type: "text" as const,
            text: JSON.stringify(structuredContent)
          }];
          if (definition.name === "cad_export_report") {
            const report = parseCadReportExportResponse(structuredContent);
            content.push({
              type: "resource_link" as const,
              uri: reportResourceUri(report.downloadId),
              name: report.filename,
              mimeType: report.mediaType
            });
          }
          return {
            content,
            structuredContent
          };
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          const structuredContent = {
            error: {
              code: "CAD_TOOL_ERROR",
              message
            }
          };
          return {
            content: [
              {
                type: "text" as const,
                text: message
              }
            ],
            structuredContent,
            isError: true
          };
        }
      }
    );
  }

  return server;
}

async function requestExportDestination(
  server: McpServer,
  services: McpExportServices,
  signal?: AbortSignal
): Promise<unknown> {
  if (
    !services.requestDestinationGrant ||
    !server.server.getClientCapabilities()?.elicitation?.form
  ) {
    throw new Error("MCP_ELICITATION_UNSUPPORTED");
  }
  const elicitation = await server.server.elicitInput({
    mode: "form",
    message: `Create a one-use export grant for ${services.displayDirectory ?? "the host export directory"}?`,
    requestedSchema: {
      type: "object",
      properties: {
        confirm: {
          type: "boolean",
          title: "Confirm export destination"
        }
      },
      required: ["confirm"],
      additionalProperties: false
    }
  } as Parameters<typeof server.server.elicitInput>[0], { signal });
  if (
    elicitation.action !== "accept" ||
    !elicitation.content ||
    !isExactConfirmation(elicitation.content)
  ) {
    throw new Error("DESTINATION_SELECTION_CANCELLED");
  }
  const grant = await services.requestDestinationGrant(signal);
  if (!grant) throw new Error("DESTINATION_SELECTION_CANCELLED");
  return grant;
}

function reportResourceUri(downloadId: string): string {
  return `cad-report://reports/${downloadId}`;
}

async function requestReportDownload(
  services: {
    createReportDownload?(input: unknown, signal?: AbortSignal): Promise<CadReportExportResponse>;
  },
  input: unknown,
  signal?: AbortSignal
): Promise<CadReportExportResponse> {
  if (!services.createReportDownload) throw new Error("MCP_REPORT_DOWNLOAD_UNSUPPORTED");
  return parseCadReportExportResponse(await services.createReportDownload(input, signal));
}

function publicDrawingResponse(value: unknown) {
  const verification = parseCadOutputVerification(value);
  return parseCadDrawingExportResponse({
    verificationId: verification.id,
    status: verification.status
  });
}

function registerReportResource(
  server: McpServer,
  services: McpExportServices
): void {
  server.registerResource(
    "cad-export-report",
    new ResourceTemplate("cad-report://reports/{downloadId}", {
      list: undefined
    }),
    {
      title: "CAD export report",
      description: "Single-use bounded report generated from the active CAD document."
    },
    async (uri, variables) => {
      const downloadId = variables.downloadId;
      if (
        typeof downloadId !== "string" ||
        !reportResourceIdPattern.test(downloadId) ||
        !services.consumeReportDownload
      ) {
        throw new Error("REPORT_RESOURCE_UNKNOWN");
      }
      const report = services.consumeReportDownload(downloadId);
      if (!report) throw new Error("REPORT_RESOURCE_UNKNOWN");
      const common = {
        uri: uri.href,
        mimeType: report.mediaType
      };
      return {
        contents: [
          report.format === "pdf"
            ? {
                ...common,
                blob: Buffer.from(report.bytes).toString("base64")
              }
            : {
                ...common,
                text: new TextDecoder("utf-8", { fatal: true }).decode(report.bytes)
              }
        ]
      };
    }
  );
}

function isExactConfirmation(value: Record<string, unknown>): boolean {
  const keys = Object.keys(value);
  return keys.length === 1 && keys[0] === "confirm" && value.confirm === true;
}

function asStructuredContent(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return { value };
  }
  return value as Record<string, unknown>;
}
