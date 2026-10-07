export type AnswerInline = { kind: "text" | "strong" | "code"; text: string };
export type AnswerBlock =
  | { kind: "heading"; level: 2 | 3 | 4; content: AnswerInline[] }
  | { kind: "paragraph"; content: AnswerInline[] }
  | { kind: "list"; ordered: boolean; items: AnswerInline[][] }
  | { kind: "key-values"; rows: Array<{ key: string; value: AnswerInline[] }> }
  | { kind: "table"; headers: string[]; rows: string[][] }
  | { kind: "overflow"; remaining: string; truncated: boolean };

const MAX_ANSWER_CHARS = 65_536;
const MAX_BLOCKS = 80;
const MAX_TABLE_ROWS = 20;
const MAX_TABLE_COLUMNS = 4;

function inline(value: string): AnswerInline[] {
  const output: AnswerInline[] = [];
  const pattern = /\*\*([^*\n]{1,240})\*\*|`([^`\n]{1,240})`/g;
  let cursor = 0;
  for (const match of value.matchAll(pattern)) {
    const start = match.index ?? 0;
    if (start > cursor) output.push({ kind: "text", text: value.slice(cursor, start) });
    output.push(match[1] !== undefined
      ? { kind: "strong", text: match[1] }
      : { kind: "code", text: match[2] });
    cursor = start + match[0].length;
  }
  if (cursor < value.length) output.push({ kind: "text", text: value.slice(cursor) });
  return output.length ? output : [{ kind: "text", text: "" }];
}

function cells(line: string): string[] {
  const content = line.trim().replace(/^\|/, "").replace(/\|$/, "");
  return content.split("|").map((cell) => cell.trim());
}

function displayCells(line: string): string[] {
  const values = cells(line);
  if (values.length <= MAX_TABLE_COLUMNS) return values;
  const visible = values.slice(0, MAX_TABLE_COLUMNS);
  visible[MAX_TABLE_COLUMNS - 1] = `${visible[MAX_TABLE_COLUMNS - 1]} · Additional columns: ${values.slice(MAX_TABLE_COLUMNS).join(" | ")}`;
  return visible;
}

function isTableSeparator(line: string): boolean {
  const values = cells(line);
  return values.length > 0 && values.every((value) => /^:?-{3,}:?$/.test(value));
}

function keyValue(line: string): { key: string; value: string } | null {
  const match = line.match(/^([^:\n]{1,60}):\s+(.{1,240})$/);
  return match ? { key: match[1].trim(), value: match[2].trim() } : null;
}

/** Parse a deliberately small Markdown subset into text-only semantic blocks. */
export function parseAssistantAnswer(value: string): AnswerBlock[] {
  const text = value.slice(0, MAX_ANSWER_CHARS).replace(/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/g, "");
  const inputTruncated = value.length > MAX_ANSWER_CHARS;
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: AnswerBlock[] = [];
  let index = 0;
  const push = (block: AnswerBlock) => { if (blocks.length < MAX_BLOCKS) blocks.push(block); };

  // Reserve the final slot for an explicit overflow disclosure when more content remains.
  while (index < lines.length && blocks.length < MAX_BLOCKS - 1) {
    const line = lines[index].trim();
    if (!line) { index += 1; continue; }

    const heading = line.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      push({ kind: "heading", level: (heading[1].length + 1) as 2 | 3 | 4, content: inline(heading[2]) });
      index += 1;
      continue;
    }

    if (index + 1 < lines.length && line.includes("|") && isTableSeparator(lines[index + 1].trim())) {
      const headers = displayCells(line);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lines[index].trim().includes("|") && rows.length < MAX_TABLE_ROWS) {
        rows.push(displayCells(lines[index]).slice(0, headers.length));
        index += 1;
      }
      push({ kind: "table", headers, rows });
      continue;
    }

    const unordered = line.match(/^[-*+]\s+(.+)$/);
    const ordered = line.match(/^\d{1,3}[.)]\s+(.+)$/);
    if (unordered || ordered) {
      const isOrdered = Boolean(ordered);
      const items: AnswerInline[][] = [];
      while (index < lines.length && items.length < MAX_TABLE_ROWS) {
        const candidate = lines[index].trim();
        const match = candidate.match(isOrdered ? /^\d{1,3}[.)]\s+(.+)$/ : /^[-*+]\s+(.+)$/);
        if (!match) break;
        items.push(inline(match[1]));
        index += 1;
      }
      push({ kind: "list", ordered: isOrdered, items });
      continue;
    }

    const firstPair = keyValue(line);
    if (firstPair) {
      const rows = [firstPair];
      let next = index + 1;
      while (next < lines.length && rows.length < MAX_TABLE_ROWS) {
        const pair = keyValue(lines[next].trim());
        if (!pair) break;
        rows.push(pair);
        next += 1;
      }
      if (rows.length >= 2) {
        push({ kind: "key-values", rows: rows.map((row) => ({ key: row.key, value: inline(row.value) })) });
        index = next;
        continue;
      }
    }

    const paragraph: string[] = [line];
    index += 1;
    while (index < lines.length && lines[index].trim() && !/^(#{1,3})\s+/.test(lines[index].trim())
        && !/^[-*+]\s+/.test(lines[index].trim()) && !/^\d{1,3}[.)]\s+/.test(lines[index].trim())
        && !(lines[index].includes("|") && index + 1 < lines.length && isTableSeparator(lines[index + 1].trim()))) {
      paragraph.push(lines[index].trim());
      index += 1;
    }
      push({ kind: "paragraph", content: inline(paragraph.join(" ")) });
  }
  if (index < lines.length || inputTruncated) {
    const remaining = lines.slice(index).join("\n");
    const extra = `${remaining}${inputTruncated && remaining ? "\n" : ""}${inputTruncated ? value.slice(MAX_ANSWER_CHARS) : ""}`;
    const suffix = extra.slice(0, MAX_ANSWER_CHARS);
    push({ kind: "overflow", remaining: suffix, truncated: extra.length > suffix.length });
  }
  return blocks;
}
