import { spawn } from "node:child_process";

import type {
  ProcessResult,
  ProcessRunner,
  ProcessRunSpec
} from "../contracts.js";

const defaultTimeoutMs = 120_000;
const maxProcessOutputChars = 1_048_576;

export const defaultProcessRunner: ProcessRunner = {
  run(spec) {
    return runProcess(spec);
  }
};

export function runProcess(spec: ProcessRunSpec): Promise<ProcessResult> {
  return new Promise((resolve) => {
    if (spec.signal?.aborted) {
      resolve(cancelledResult());
      return;
    }

    let stdout = "";
    let stderr = "";
    let settled = false;
    let timer: NodeJS.Timeout | undefined;
    const child = spawn(spec.command, spec.args, {
      cwd: spec.cwd,
      env: spec.env,
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
      shell: false
    });

    const finish = (result: ProcessResult) => {
      if (settled) return;
      settled = true;
      if (timer) clearTimeout(timer);
      spec.signal?.removeEventListener("abort", abort);
      resolve(result);
    };
    const abort = () => {
      child.kill();
      finish(cancelledResult(stdout));
    };
    const exceedOutputLimit = () => {
      child.kill();
      finish({
        exitCode: null,
        stdout,
        stderr: `${stderr}${stderr ? "\n" : ""}Provider process output limit exceeded`,
        errorCode: "EOUTPUTLIMIT"
      });
    };
    const appendOutput = (stream: "stdout" | "stderr", chunk: string) => {
      if (settled) return;
      const remaining = maxProcessOutputChars - stdout.length - stderr.length;
      if (remaining > 0) {
        if (stream === "stdout") {
          stdout += chunk.slice(0, remaining);
        } else {
          stderr += chunk.slice(0, remaining);
        }
      }
      if (chunk.length > remaining) {
        exceedOutputLimit();
      }
    };

    child.stdout.setEncoding("utf8");
    child.stderr.setEncoding("utf8");
    child.stdout.on("data", (chunk: string) => {
      appendOutput("stdout", chunk);
    });
    child.stderr.on("data", (chunk: string) => {
      appendOutput("stderr", chunk);
    });
    child.on("error", (error: NodeJS.ErrnoException) => {
      finish({
        exitCode: null,
        stdout,
        stderr: error.message,
        errorCode: error.code
      });
    });
    child.on("close", (exitCode) => {
      finish({ exitCode, stdout, stderr });
    });

    if (spec.stdin !== undefined) {
      child.stdin.end(spec.stdin, "utf8");
    } else {
      child.stdin.end();
    }

    spec.signal?.addEventListener("abort", abort, { once: true });
    timer = setTimeout(() => {
      child.kill();
      finish({
        exitCode: null,
        stdout,
        stderr: "Provider process timed out",
        errorCode: "ETIMEDOUT"
      });
    }, spec.timeoutMs ?? defaultTimeoutMs);
  });
}

function cancelledResult(stdout = ""): ProcessResult {
  return {
    exitCode: null,
    stdout,
    stderr: "Provider process cancelled",
    errorCode: "ABORT_ERR"
  };
}
