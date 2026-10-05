import { lstatSync, readdirSync, readFileSync, realpathSync } from 'node:fs';
import { isAbsolute, join, relative, resolve, sep } from 'node:path';
import { fileURLToPath } from 'node:url';

export function checkWorkspaceLinks(repositoryRoot) {
  const root = realpathSync(repositoryRoot);
  const modules = join(root, 'node_modules');
  if (lstatSync(modules).isSymbolicLink()) {
    throw new Error('node_modules points outside its own checkout; restore local dependencies before starting Editor.');
  }
  const manifest = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8'));
  const checked = [];
  for (const pattern of manifest.workspaces) {
    const directories = pattern.endsWith('/*')
      ? readdirSync(join(root, pattern.slice(0, -2)), { withFileTypes: true })
        .filter(entry => entry.isDirectory())
        .map(entry => join(root, pattern.slice(0, -2), entry.name))
      : [join(root, pattern)];
    for (const directory of directories) {
      let contents;
      try { contents = readFileSync(join(directory, 'package.json'), 'utf8'); }
      catch (error) { if (error.code === 'ENOENT') continue; throw error; }
      const pkg = JSON.parse(contents);
      const { name } = pkg;
      const expected = realpathSync(directory);
      let actual;
      try { actual = realpathSync(join(modules, name)); }
      catch { throw new Error(`Missing workspace package ${name}; install workspace dependencies.`); }
      if (actual !== expected) {
        throw new Error(`${name} resolves to a different checkout: ${actual}. Expected ${expected}.`);
      }
      for (const dependency of Object.keys({ ...pkg.dependencies, ...pkg.devDependencies, ...pkg.peerDependencies })) {
        const nested = join(directory, 'node_modules', dependency);
        let installed;
        try { installed = realpathSync(nested); }
        catch (error) { if (error.code === 'ENOENT') continue; throw error; }
        const localPath = relative(root, installed);
        if (localPath === '..' || localPath.startsWith(`..${sep}`) || isAbsolute(localPath)) {
          throw new Error(`${name} dependency ${dependency} resolves outside this checkout: ${installed}.`);
        }
      }
      checked.push({ name, path: actual });
    }
  }
  return checked;
}

if (process.argv[1] && resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const checked = checkWorkspaceLinks(fileURLToPath(new URL('../..', import.meta.url)));
  console.log(`Verified ${checked.length} local workspace packages.`);
}
