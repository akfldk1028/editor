import { z } from "zod";

import { MAX_CAD_SEARCH_QUERY_CHARS } from "@dwg/contracts";

export const CAD_TOOL_NAMES = [
  "cad.open_drawing",
  "cad.build_index",
  "cad.get_layers",
  "cad.find_entities_by_layer",
  "cad.find_entities_by_type",
  "cad.find_text",
  "cad.get_entity",
  "cad.list_unsupported",
  "cad_request_export_destination",
  "cad_export_report",
  "cad_export_drawing",
  "cad_get_export_verification"
] as const;

export type CadToolName = (typeof CAD_TOOL_NAMES)[number];

interface CadToolDefinition {
  name: CadToolName;
  description: string;
  inputSchema: z.ZodRawShape;
}

const drawingId = z.string().min(1).describe("Drawing session ID returned by cad.open_drawing");

export const CAD_TOOL_DEFINITIONS: readonly CadToolDefinition[] = [
  {
    name: "cad.open_drawing",
    description: "Open a local DWG or DXF drawing in read-only mode and return its drawing session ID.",
    inputSchema: {
      path: z.string().min(1).describe("Local path to a DWG or DXF drawing")
    }
  },
  {
    name: "cad.build_index",
    description: "Build or retrieve the normalized versioned CAD index for an opened drawing.",
    inputSchema: { drawingId }
  },
  {
    name: "cad.get_layers",
    description: "List indexed layers and entity counts for a drawing.",
    inputSchema: { drawingId }
  },
  {
    name: "cad.find_entities_by_layer",
    description: "Find indexed CAD entities whose layer exactly matches the query.",
    inputSchema: {
      drawingId,
      layer: z.string().min(1).describe("Exact CAD layer name")
    }
  },
  {
    name: "cad.find_entities_by_type",
    description: "Find indexed CAD entities by case-insensitive entity type.",
    inputSchema: {
      drawingId,
      type: z.string().min(1).describe("CAD entity type such as LINE or TEXT")
    }
  },
  {
    name: "cad.find_text",
    description: "Find indexed TEXT or MTEXT content using substring or regular-expression matching.",
    inputSchema: {
      drawingId,
      query: z.string().min(1).max(MAX_CAD_SEARCH_QUERY_CHARS)
        .describe("Text or a grouping-free regular expression to search for"),
      regex: z.boolean().optional().default(false)
    }
  },
  {
    name: "cad.get_entity",
    description: "Return one indexed entity by stable entity ID or CAD handle.",
    inputSchema: {
      drawingId,
      entityIdOrHandle: z.string().min(1).describe("Stable index ID or CAD handle")
    }
  },
  {
    name: "cad.list_unsupported",
    description: "List unsupported or partially parsed CAD entity types and reasons.",
    inputSchema: { drawingId }
  },
  {
    name: "cad_request_export_destination",
    description: "Confirm the host-configured export destination and issue a one-use grant.",
    inputSchema: {}
  },
  {
    name: "cad_export_report",
    description: "Export a bounded report for the current document revision.",
    inputSchema: {
      documentId: drawingId,
      revision: z.number().int().nonnegative(),
      format: z.enum(["json", "csv", "pdf", "svg"])
    }
  },
  {
    name: "cad_export_drawing",
    description: "Save a verified drawing copy to a granted destination.",
    inputSchema: {
      documentId: drawingId,
      expectedRevision: z.number().int().nonnegative(),
      destinationGrantId: z.string().uuid(),
      baseFilename: z.string().min(1).max(255),
      format: z.enum(["dxf", "dwg"]),
      version: z.string().regex(/^AC[0-9]{4}$/u)
    }
  },
  {
    name: "cad_get_export_verification",
    description: "Read independent verification evidence for a saved drawing.",
    inputSchema: { id: z.string().min(1).max(256) }
  }
];
