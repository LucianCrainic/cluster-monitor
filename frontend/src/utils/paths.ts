export function quotePosixPath(path: string): string {
  if (/^[A-Za-z0-9_@%+=:,./-]+$/.test(path)) return path;
  return `'${path.replaceAll("'", `'"'"'`)}'`;
}
