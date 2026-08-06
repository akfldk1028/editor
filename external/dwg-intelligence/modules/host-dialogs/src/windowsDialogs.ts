import { realpath, stat } from "node:fs/promises";
import { basename, extname } from "node:path";

import {
  HostDialogError,
  type HostDialogProcessRunner,
  type HostDialogProvider,
  type HostDirectorySelection,
  type HostDrawingSelection
} from "./contracts.js";

const FOLDER_SCRIPT = [
  "Add-Type -AssemblyName System.Windows.Forms;",
  "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog;",
  "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)",
  "{ [Console]::Out.Write($dialog.SelectedPath) }"
].join(" ");

const FILE_SCRIPT = [
  "Add-Type -AssemblyName System.Windows.Forms;",
  "$dialog = New-Object System.Windows.Forms.OpenFileDialog;",
  "$dialog.Filter = 'CAD drawings|*.dwg;*.dxf';",
  "$dialog.Multiselect = $false;",
  "if ($dialog.ShowDialog() -eq [System.Windows.Forms.DialogResult]::OK)",
  "{ [Console]::Out.Write($dialog.FileName) }"
].join(" ");

export function createWindowsHostDialogProvider(options: {
  runner: HostDialogProcessRunner;
  cwd?: string;
}): HostDialogProvider {
  const cwd = options.cwd ?? process.cwd();

  async function selectPath(script: string, signal?: AbortSignal): Promise<string | null> {
    if (signal?.aborted) throw signal.reason;
    const result = await options.runner.run({
      command: "powershell",
      args: ["-NoProfile", "-NonInteractive", "-STA", "-Command", script],
      cwd,
      env: process.env,
      signal
    });
    if (result.exitCode !== 0) throw new HostDialogError();
    const selected = result.stdout.trim();
    return selected.length === 0 ? null : selected;
  }

  return {
    async openDrawingFile(signal): Promise<HostDrawingSelection | null> {
      const selected = await selectPath(FILE_SCRIPT, signal);
      if (selected === null) return null;
      const canonicalPath = await canonicalize(selected, "file");
      if (canonicalPath === null) return null;
      const extension = extname(canonicalPath).toLowerCase();
      if (extension !== ".dwg" && extension !== ".dxf") return null;
      return { canonicalPath, displayName: basename(canonicalPath) };
    },
    async chooseDirectory(signal): Promise<HostDirectorySelection | null> {
      const selected = await selectPath(FOLDER_SCRIPT, signal);
      if (selected === null) return null;
      const canonicalDirectory = await canonicalize(selected, "directory");
      if (canonicalDirectory === null) return null;
      return {
        canonicalDirectory,
        displayDirectory: basename(canonicalDirectory)
      };
    }
  };
}

async function canonicalize(
  selected: string,
  kind: "file" | "directory"
): Promise<string | null> {
  try {
    const canonical = await realpath(selected);
    const entry = await stat(canonical);
    const matches = kind === "directory" ? entry.isDirectory() : entry.isFile();
    return matches ? canonical : null;
  } catch {
    return null;
  }
}
