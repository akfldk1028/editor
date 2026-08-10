export interface HostDialogProcessRunner {
  run(spec: {
    command: string;
    args: string[];
    cwd: string;
    env: NodeJS.ProcessEnv;
    signal?: AbortSignal;
  }): Promise<{ exitCode: number | null; stdout: string; stderr: string }>;
}

export interface HostDirectorySelection {
  canonicalDirectory: string;
  displayDirectory: string;
}

export interface HostDrawingSelection {
  canonicalPath: string;
  displayName: string;
}

export interface HostDialogProvider {
  openDrawingFile(signal?: AbortSignal): Promise<HostDrawingSelection | null>;
  chooseDirectory(signal?: AbortSignal): Promise<HostDirectorySelection | null>;
}

export class HostDialogError extends Error {
  readonly code = "HOST_DIALOG_FAILED";

  constructor() {
    // The host dialog reports the operator's filesystem in stderr; it is never
    // carried into a message that crosses a process or network boundary.
    super("The host file dialog did not complete.");
    this.name = "HostDialogError";
  }
}
