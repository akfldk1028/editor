import { spawn } from "node:child_process";
import { isAbsolute, normalize, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const repositoryRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const workspaceRoot = resolve(repositoryRoot, "apps/workspace");
const playwrightCli = resolve(repositoryRoot, "node_modules/@playwright/test/cli.js");

const DRAWING_FLAG = "--drawing";

export function parseE2eArgs(argv) {
  const playwrightArgs = [];
  let drawingPath = null;
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    if (argument !== DRAWING_FLAG && !argument.startsWith(`${DRAWING_FLAG}=`)) {
      playwrightArgs.push(argument);
      continue;
    }
    const value = argument === DRAWING_FLAG ? argv[index + 1] : argument.slice(DRAWING_FLAG.length + 1);
    if (argument === DRAWING_FLAG) index += 1;
    if (drawingPath !== null) {
      throw new Error(`${DRAWING_FLAG} was provided more than once.`);
    }
    drawingPath = assertRepositoryRelative(value);
  }
  return { drawingPath, playwrightArgs };
}

function assertRepositoryRelative(value) {
  if (
    typeof value !== "string"
    || value.length === 0
    || value.startsWith("-")
    || isAbsolute(value)
    || /^[A-Za-z]:/u.test(value)
    || normalize(value).startsWith("..")
  ) {
    throw new Error(`${DRAWING_FLAG} requires a repository-relative path inside the repository.`);
  }
  return value;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const { drawingPath, playwrightArgs } = parseE2eArgs(process.argv.slice(2));
  const child = spawn(
    process.execPath,
    [playwrightCli, "test", ...playwrightArgs],
    {
      cwd: workspaceRoot,
      stdio: "inherit",
      env: drawingPath === null
        ? process.env
        : { ...process.env, DWG_DRAWING_PATH: drawingPath }
    }
  );
  child.on("exit", (code, signal) => {
    process.exit(signal ? 1 : code ?? 1);
  });
}
