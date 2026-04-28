/** Extract content between a named anchor pair. */
export function getAnchorBlock(doc: string, name: string): string {
  const match = findAnchor(doc, name);
  if (!match.start) return "";
  if (!match.end) throw new Error(`Anchor ${match.canonical} has START tag but missing END tag`);
  return doc.slice(match.start.contentStart, match.end.tagStart);
}

/** Replace content between a named anchor pair, preserving the tags. */
export function setAnchorBlock(doc: string, name: string, newContent: string): string {
  const match = findAnchor(doc, name);
  if (!match.start) return doc;
  if (!match.end) throw new Error(`Anchor ${match.canonical} has START tag but missing END tag`);
  return `${doc.slice(0, match.start.contentStart)}${normalizeBlockContent(newContent, match.start.lineEnding)}${doc.slice(match.end.tagStart)}`;
}

/** List all anchor names present in a document. */
export function listAnchors(doc: string): string[] {
  const seen = new Set<string>();
  const re = /<!--\s*([A-Z0-9_]+)_START\s*-->/gi;
  for (let m = re.exec(doc); m; m = re.exec(doc)) seen.add(m[1].toUpperCase());
  return [...seen];
}

interface AnchorStart { tagStart:number; tagEnd:number; contentStart:number; lineEnding:string; }
interface AnchorEnd { tagStart:number; tagEnd:number; }

function escapeRegExp(s:string): string { return s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }

function findAnchor(doc:string, name:string): { canonical:string; start?:AnchorStart; end?:AnchorEnd } {
  const canonical = name.replace(/_(START|END)$/i, "").toUpperCase();
  const startRe = new RegExp(`<!--\\s*${escapeRegExp(canonical)}_START\\s*-->`, "i");
  const startMatch = startRe.exec(doc);
  if (!startMatch) return { canonical };
  const tagStart = startMatch.index;
  const tagEnd = tagStart + startMatch[0].length;
  const afterTag = doc.slice(tagEnd, tagEnd + 2) === "\r\n" ? "\r\n" : doc[tagEnd] === "\n" ? "\n" : "";
  const contentStart = tagEnd + afterTag.length;
  const endRe = new RegExp(`<!--\\s*${escapeRegExp(canonical)}_END\\s*-->`, "i");
  const endMatch = endRe.exec(doc.slice(contentStart));
  const start = { tagStart, tagEnd, contentStart, lineEnding:afterTag || (doc.includes("\r\n") ? "\r\n" : "\n") };
  if (!endMatch) return { canonical, start };
  const endTagStart = contentStart + endMatch.index;
  return { canonical, start, end:{ tagStart:endTagStart, tagEnd:endTagStart + endMatch[0].length } };
}

function normalizeBlockContent(content:string, lineEnding:string): string {
  const normalized = content.replace(/\r?\n/g, lineEnding);
  const suffix = normalized.endsWith(lineEnding) ? "" : lineEnding;
  return `${normalized}${suffix}`;
}
