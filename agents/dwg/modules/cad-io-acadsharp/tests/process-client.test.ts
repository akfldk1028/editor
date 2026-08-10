import assert from "node:assert/strict";
import { randomUUID } from "node:crypto";
import test from "node:test";

import type { CadCommittedTransaction } from "@dwg/cad-edit";
import {
  CadIoError,
  createAcadSharpCadIoClient,
  mapCadSaveLineage,
  type CadIoWriteRequest,
  type CadIoWriteCommand,
  type CadIoWriteTransaction,
  type CadProcessRunner
} from "../src/index.js";

const MAX_OUTPUT_BYTES = 1_048_576;
const transactionId = "11111111-1111-4111-8111-111111111111";
const copyCommandId = "33333333-3333-4333-8333-333333333333";
const temporaryId = `copy:${transactionId}:${copyCommandId}:0`;

test("maps save lineage to the exact strict wire DTO without snapshots or unknown data", async () => {
  const runner = new RecordingRunner(successResponse({
    copiedHandleMap: { [temporaryId]: "ABC" }
  }));
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });
  const lineage = mapCadSaveLineage([committedTransaction()]);

  const result = await client.writeCopy(writeRequest(lineage));

  assert.deepEqual(result, {
    format: "dxf",
    version: "AC1032",
    entityCount: 5,
    copiedHandleMap: { [temporaryId]: "ABC" },
    warnings: []
  });
  assert.equal(runner.calls.length, 1);
  const call = runner.calls[0]!;
  assert.equal(call.command, "dotnet");
  assert.deepEqual(call.args, [
    "run",
    "--project",
    "C:\\repo\\CadIo.Host.csproj",
    "--no-build",
    "--no-launch-profile",
    "--"
  ]);
  assert.equal(call.cwd, "C:\\repo");
  assert.equal(call.maxOutputBytes, MAX_OUTPUT_BYTES);
  assert.deepEqual(JSON.parse(call.stdin), {
    schemaVersion: "cad-io/v1",
    operation: "write-copy",
    sourcePath: "C:\\work\\source.dxf",
    temporaryOutputPath: "C:\\work\\output.dxf",
    format: "dxf",
    version: "AC1032",
    lineage: [{
      transactionId,
      beforeRevision: 0,
      afterRevision: 1,
      commands: [
        {
          kind: "layer.create",
          layerId: "layer:created:review",
          name: "Review",
          color: 4
        },
        {
          kind: "layer.update",
          layerId: "layer:imported:MA",
          name: "Base",
          visible: false,
          locked: true
        },
        {
          kind: "text.replace",
          handle: "30",
          value: "updated"
        },
        {
          kind: "entity.move",
          handles: ["10"],
          delta: [1, 2, 3]
        },
        {
          kind: "entity.copy",
          sourceHandles: ["11"],
          temporaryIds: [temporaryId],
          delta: [4, 5, 6]
        },
        {
          kind: "entity.delete",
          handles: ["12"]
        }
      ]
    }]
  });
  assert.doesNotMatch(
    call.stdin,
    /"before":|"after":|resolvedCommands|changes|unknown/u
  );
});

test("denies DWG before process launch when no policy manifest is configured", async () => {
  const runner = new RecordingRunner(successResponse());
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });

  await assert.rejects(
    () => client.writeCopy({ ...writeRequest([]), format: "dwg" }),
    (error: unknown) => cadIoCode(error) === "DWG_POLICY_NOT_CONFIGURED"
  );
  assert.equal(runner.calls.length, 0);
});

test("passes the configured DWG manifest as a host-only policy argument", async () => {
  const runner = new RecordingRunner(successResponse({
    format: "dwg",
    copiedHandleMap: {}
  }));
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner,
    dwgVersionManifestPath: "C:\\repo\\roundtrip-manifest.json"
  });

  await client.writeCopy({ ...writeRequest([]), format: "dwg" });

  assert.deepEqual(runner.calls[0]!.args.slice(-2), [
    "--dwg-policy-manifest",
    "C:\\repo\\roundtrip-manifest.json"
  ]);
});

test("keeps DXF writes independent from a configured DWG policy", async () => {
  const runner = new RecordingRunner(successResponse({
    copiedHandleMap: {}
  }));
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner,
    dwgVersionManifestPath: "C:\\repo\\roundtrip-manifest.json"
  });

  await client.writeCopy(writeRequest([]));

  assert.deepEqual(runner.calls[0]!.args.slice(-1), ["--"]);
});

test("rejects unknown fields non-finite points duplicates copy mismatches and command overflow", async () => {
  const invalidRequests: unknown[] = [
    { ...writeRequest([]), unknown: true },
    writeRequest([transaction([{
      kind: "entity.move",
      handles: ["10"],
      delta: [Number.NaN, 0, 0]
    }])]),
    writeRequest([transaction([{
      kind: "entity.delete",
      handles: ["10", "10"]
    }])]),
    writeRequest([transaction([{
      kind: "entity.copy",
      sourceHandles: ["10", "11"],
      temporaryIds: [temporaryId],
      delta: [0, 0, 0]
    }])]),
    writeRequest([transaction(Array.from({ length: 10_001 }, () => ({
      kind: "entity.delete",
      handles: ["10"]
    })))])
  ];

  for (const request of invalidRequests) {
    const runner = new RecordingRunner(successResponse());
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });
    await assert.rejects(
      () => client.writeCopy(request as CadIoWriteRequest),
      (error: unknown) => cadIoCode(error) === "CAD_REQUEST_INVALID"
        || cadIoCode(error) === "CAD_REQUEST_LIMIT"
    );
    assert.equal(runner.calls.length, 0);
  }
});

test("accepts only canonical nonzero unsigned 64-bit uppercase hex handles", async () => {
  for (const handle of ["1", "FFFFFFFFFFFFFFFF"]) {
    const runner = new RecordingRunner(successResponse({
      copiedHandleMap: {}
    }));
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });

    await client.writeCopy(writeRequest([transaction([{
      kind: "entity.delete",
      handles: [handle]
    }])]));

    assert.equal(runner.calls.length, 1);
  }

  for (const handle of [
    "0",
    "0000000000000001",
    "10000000000000000",
    "abcdef",
    "+1",
    " 1",
    "1 "
  ]) {
    const runner = new RecordingRunner(successResponse());
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });

    await assert.rejects(
      () => client.writeCopy(writeRequest([transaction([{
        kind: "entity.delete",
        handles: [handle]
      }])])),
      (error: unknown) => cadIoCode(error) === "CAD_REQUEST_INVALID"
    );
    assert.equal(runner.calls.length, 0);
  }
});

test("rejects a zero copy source handle before process launch", async () => {
  const runner = new RecordingRunner(successResponse());
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });

  await assert.rejects(
    () => client.writeCopy(writeRequest([transaction([{
      kind: "entity.copy",
      sourceHandles: ["0"],
      temporaryIds: [temporaryId],
      delta: [0, 0, 0]
    }])])),
    (error: unknown) => cadIoCode(error) === "CAD_REQUEST_INVALID"
  );
  assert.equal(runner.calls.length, 0);
});

test("accepts only canonical bounded temporary copy indexes", async () => {
  for (const index of ["0", "2147483647"]) {
    const id = `copy:${transactionId}:${copyCommandId}:${index}`;
    const runner = new RecordingRunner(successResponse({
      copiedHandleMap: { [id]: "ABC" }
    }));
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });

    await client.writeCopy(writeRequest([transaction([{
      kind: "entity.copy",
      sourceHandles: ["10"],
      temporaryIds: [id],
      delta: [0, 0, 0]
    }])]));

    assert.equal(runner.calls.length, 1);
  }

  for (const index of ["01", "+1", " 1", "1 ", "2147483648"]) {
    const id = `copy:${transactionId}:${copyCommandId}:${index}`;
    const runner = new RecordingRunner(successResponse());
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });

    await assert.rejects(
      () => client.writeCopy(writeRequest([transaction([{
        kind: "entity.copy",
        sourceHandles: ["10"],
        temporaryIds: [id],
        delta: [0, 0, 0]
      }])])),
      (error: unknown) => cadIoCode(error) === "CAD_REQUEST_INVALID"
    );
    assert.equal(runner.calls.length, 0);
  }
});

test("rejects request JSON above one MiB before process launch", async () => {
  const runner = new RecordingRunner(successResponse());
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });

  await assert.rejects(
    () => client.writeCopy({
      ...writeRequest([]),
      lineage: [transaction(Array.from({ length: 100 }, () => ({
        kind: "text.replace",
        handle: "30",
        value: "x".repeat(16_384)
      })))]
    }),
    (error: unknown) => cadIoCode(error) === "CAD_REQUEST_LIMIT"
  );
  assert.equal(runner.calls.length, 0);
});

test("enforces one MiB combined output and never leaks stderr content", async () => {
  const runner: CadProcessRunner = {
    async run() {
      return {
        exitCode: 1,
        stdout: "x".repeat(700_000),
        stderr: `SECRET:${"y".repeat(400_000)}`
      };
    }
  };
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });

  await assert.rejects(
    () => client.writeCopy(writeRequest([])),
    (error: unknown) => {
      assert.equal(cadIoCode(error), "CAD_PROCESS_OUTPUT_LIMIT");
      assert.doesNotMatch(String(error), /SECRET/u);
      return true;
    }
  );
});

test("forwards cancellation and does not launch a pre-aborted process", async () => {
  let receivedSignal: AbortSignal | undefined;
  const runner: CadProcessRunner = {
    async run(_spec, signal) {
      receivedSignal = signal;
      await new Promise<void>((_resolve, reject) => {
        signal?.addEventListener(
          "abort",
          () => reject(new DOMException("cancelled", "AbortError")),
          { once: true }
        );
      });
      throw new Error("unreachable");
    }
  };
  const client = createAcadSharpCadIoClient({
    projectPath: "C:\\repo\\CadIo.Host.csproj",
    processRunner: runner
  });
  const controller = new AbortController();
  const running = client.writeCopy(writeRequest([]), controller.signal);
  controller.abort();

  await assert.rejects(
    () => running,
    (error: unknown) => error instanceof DOMException && error.name === "AbortError"
  );
  assert.equal(receivedSignal, controller.signal);

  const preAborted = new AbortController();
  preAborted.abort();
  receivedSignal = undefined;
  await assert.rejects(
    () => client.writeCopy(writeRequest([]), preAborted.signal),
    (error: unknown) => error instanceof DOMException && error.name === "AbortError"
  );
  assert.equal(receivedSignal, undefined);
});

test("rejects strict response violations duplicate keys and invalid copy mappings", async () => {
  const invalidResponses = [
    successResponse({ unknown: true }),
    `{"status":"ok","format":"dxf","format":"dxf","version":"AC1032","entityCount":5,"copiedHandleMap":{},"warnings":[]}`,
    successResponse({
      copiedHandleMap: { [temporaryId]: "abc" }
    }),
    successResponse({
      copiedHandleMap: { [temporaryId]: "0" }
    }),
    successResponse({
      copiedHandleMap: { [temporaryId]: "ABC", other: "ABC" }
    }),
    successResponse({
      copiedHandleMap: {}
    })
  ];

  for (const stdout of invalidResponses) {
    const runner = new RecordingRunner(stdout);
    const client = createAcadSharpCadIoClient({
      projectPath: "C:\\repo\\CadIo.Host.csproj",
      processRunner: runner
    });
    await assert.rejects(
      () => client.writeCopy(writeRequest([transaction([{
        kind: "entity.copy",
        sourceHandles: ["11"],
        temporaryIds: [temporaryId],
        delta: [0, 0, 0]
      }])])),
      (error: unknown) => cadIoCode(error) === "CAD_RESPONSE_INVALID"
    );
  }
});

function committedTransaction(): CadCommittedTransaction {
  const commandIds = Array.from({ length: 6 }, () => randomUUID());
  commandIds[4] = copyCommandId;
  const batch = {
    schemaVersion: "cad-edit/v1" as const,
    transactionId,
    documentId: "drawing:test",
    expectedRevision: 0,
    commands: [
      proposal(commandIds[0]!, {
        kind: "layer.create" as const,
        layerId: "layer:created:review",
        name: "Review",
        color: 4
      }),
      proposal(commandIds[1]!, {
        kind: "layer.update" as const,
        layerId: "layer:imported:MA",
        name: "Base",
        visible: false,
        locked: true
      }),
      proposal(commandIds[2]!, {
        kind: "text.replace" as const,
        handle: "30",
        text: "updated"
      }),
      proposal(commandIds[3]!, {
        kind: "entity.move" as const,
        handles: ["10"],
        delta: [1, 2, 3]
      }),
      proposal(commandIds[4]!, {
        kind: "entity.copy" as const,
        handles: ["11"],
        delta: [4, 5, 6]
      }),
      proposal(commandIds[5]!, {
        kind: "entity.delete" as const,
        handles: ["12"]
      })
    ]
  };
  return {
    status: "applied",
    batch,
    before: snapshot(0),
    after: snapshot(1),
    resolvedCommands: [],
    changes: [],
    unknown: "must never cross process boundary"
  } as unknown as CadCommittedTransaction;
}

function proposal<T>(
  commandId: string,
  operation: T
) {
  return {
    commandId,
    expectedRevision: 0,
    origin: { kind: "user" as const, id: "test" },
    preconditions: [{
      target: operation && typeof operation === "object" && "handle" in operation
        ? String(operation.handle)
        : "target",
      field: "exists" as const,
      equals: true
    }],
    operation
  };
}

function snapshot(revision: number) {
  return {
    documentId: "drawing:test",
    revision,
    sourceSha256: "A".repeat(64),
    drawingVersion: "AC1032",
    units: null,
    index: {
      schemaVersion: "cad-index/v0.2" as const,
      drawingId: "drawing:test",
      source: {
        kind: "dxf" as const,
        displayName: "source.dxf",
        parser: "test"
      },
      drawing: { fileVersion: "AC1032", units: null },
      summary: {
        entityCount: 0,
        layerCount: 0,
        unsupportedCount: 0,
        modelSpaceCount: 0,
        paperSpaceCount: 0
      },
      layers: [],
      entities: [],
      unsupported: []
    },
    layers: []
  };
}

function transaction(commands: unknown[]): CadIoWriteTransaction {
  return {
    transactionId,
    beforeRevision: 0,
    afterRevision: 1,
    commands: commands as CadIoWriteCommand[]
  };
}

function writeRequest(
  lineage: CadIoWriteRequest["lineage"]
): CadIoWriteRequest {
  return {
    sourcePath: "C:\\work\\source.dxf",
    temporaryOutputPath: "C:\\work\\output.dxf",
    format: "dxf",
    version: "AC1032",
    lineage
  };
}

function successResponse(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    status: "ok",
    format: "dxf",
    version: "AC1032",
    entityCount: 5,
    copiedHandleMap: { [temporaryId]: "ABC" },
    warnings: [],
    ...overrides
  });
}

function cadIoCode(error: unknown): string | undefined {
  return error instanceof CadIoError ? error.code : undefined;
}

class RecordingRunner implements CadProcessRunner {
  readonly calls: Parameters<CadProcessRunner["run"]>[0][] = [];

  constructor(private readonly stdout: string) {}

  async run(
    spec: Parameters<CadProcessRunner["run"]>[0],
    _signal?: AbortSignal
  ) {
    this.calls.push(structuredClone(spec));
    return { exitCode: 0, stdout: this.stdout, stderr: "" };
  }
}
