export interface FileRefSuggestion { path:string; label:string; }

export function rejectPathEscape(ref:string): string {
  const cleaned = ref.replace(/^@/, "");
  if (cleaned.startsWith("/") || cleaned.split(/[\\/]+/).includes("..")) throw new Error("file reference escapes project root");
  return cleaned;
}

export function fileReferenceQuery(text:string): string | null {
  const match = text.match(/(?:^|\s)@([^\s]*)$/);
  return match ? match[1] : null;
}

export function fileReferenceSuggestions(query:string, files:string[]): FileRefSuggestion[] {
  const safe = rejectPathEscape(query);
  return files.filter(path => path.startsWith(safe) && !path.startsWith("../") && !path.startsWith("/")).slice(0, 8).map(path => ({ path, label:`@${path}` }));
}

export function insertFileReference(text:string, filePath:string): string {
  const safe = rejectPathEscape(filePath);
  if (fileReferenceQuery(text) === null) return `${text}@${safe}`;
  return text.replace(/@([^\s]*)$/, `@${safe}`);
}
