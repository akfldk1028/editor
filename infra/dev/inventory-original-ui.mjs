import { createHash } from 'node:crypto';
import { readdirSync, readFileSync, writeFileSync } from 'node:fs';
import { basename, dirname, join, relative, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import ts from 'typescript';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '../..');
const sourceRoot = resolve(process.argv[2] || join(root, '..'));
const output = resolve(process.argv[3] || join(root, 'docs/integrations/original-ui-elements.json'));
const slash = (path) => path.replaceAll('\\', '/');

function files(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    if (entry.isSymbolicLink() || ['node_modules', '.git', '.next', 'dist'].includes(entry.name)) return [];
    return entry.isDirectory() ? files(path) : [path];
  }).sort();
}

const nativeFiles = files(join(root, 'frontend/app/editor')).filter((path) => /\.(tsx|css)$/.test(path));
const records = [];
for (const [name, directory] of [
  ['ARR', join(sourceRoot, 'ARR/frontend/src')],
  ['AG-frontend', join(sourceRoot, 'AG-frontend/src')],
]) {
  for (const path of files(directory).filter((path) => /\.(tsx|css)$/.test(path) && !/\.(test|spec)\.tsx$/.test(path))) {
    const text = readFileSync(path, 'utf8');
    const record = {
      source: `${name}/${slash(relative(join(sourceRoot, name), path))}`,
      sha256: createHash('sha256').update(text).digest('hex'),
      nativeCandidates: nativeFiles.filter((native) => basename(native) === basename(path))
        .map((native) => slash(relative(root, native))),
      verification: 'unverified',
      imports: [],
      elements: [],
    };
    if (path.endsWith('.tsx')) {
      const ast = ts.createSourceFile(path, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
      function visit(node) {
        if (ts.isImportDeclaration(node) && ts.isStringLiteral(node.moduleSpecifier)) {
          record.imports.push(node.moduleSpecifier.text);
        }
        if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
          record.elements.push({
            line: ast.getLineAndCharacterOfPosition(node.getStart(ast)).line + 1,
            tag: node.tagName.getText(ast),
            attributes: node.attributes.properties.map((attribute) =>
              ts.isJsxAttribute(attribute) ? attribute.name.getText(ast) : '...spread'),
          });
        }
        ts.forEachChild(node, visit);
      }
      visit(ast);
    }
    records.push(record);
  }
}

writeFileSync(output, JSON.stringify({
  scope: 'Source JSX occurrences and CSS files, including nested view elements. Static inventory only; not browser or migration evidence.',
  matching: 'Same-basename native candidates require manual inspection. Missing candidates do not prove absence under a renamed file. Present candidates do not prove visual or behavioral parity.',
  omitted: 'Non-TSX generated elements, third-party internals and binary/public assets require separate runtime and asset review.',
  records,
}, null, 2) + '\n');
console.log(JSON.stringify({ files: records.length, elements: records.reduce((count, row) => count + row.elements.length, 0), output }));
