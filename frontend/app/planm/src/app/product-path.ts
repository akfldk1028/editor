declare const process: { env: { NEXT_PUBLIC_BASE_PATH?: string } } | undefined;

export function productPath(path: string): string {
  const base = typeof process === 'undefined' ? '' : process.env.NEXT_PUBLIC_BASE_PATH || '';
  return base + path;
}
