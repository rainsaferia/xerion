"use client";

import React from "react";

interface MarkdownMessageProps {
  content: string;
}

export function MarkdownMessage({ content }: MarkdownMessageProps) {
  if (!content) return null;

  // Split into blocks by double newlines or table boundaries
  const blocks = splitIntoBlocks(content);

  return (
    <div className="space-y-2.5 text-slate-200 text-sm leading-relaxed">
      {blocks.map((block, idx) => {
        if (block.type === "header") {
          if (block.level === 1) {
            return (
              <h1 key={idx} className="text-lg font-bold text-slate-100 mt-3 mb-1">
                {renderInline(block.content)}
              </h1>
            );
          }
          if (block.level === 2) {
            return (
              <h2 key={idx} className="text-base font-semibold text-blue-400 mt-3 mb-1 pb-1 border-b border-slate-800 flex items-center gap-2">
                {renderInline(block.content)}
              </h2>
            );
          }
          return (
            <h3 key={idx} className="text-sm font-semibold text-slate-200 mt-2 mb-1">
              {renderInline(block.content)}
            </h3>
          );
        }

        if (block.type === "table") {
          return (
            <div key={idx} className="my-3 overflow-x-auto rounded-xl border border-slate-700/80 bg-slate-950/70 shadow-sm">
              <table className="w-full text-left text-xs text-slate-200 border-collapse">
                <thead className="bg-slate-800/90 text-slate-300 uppercase tracking-wider text-[11px] border-b border-slate-700">
                  <tr>
                    {block.headers.map((h, i) => (
                      <th key={i} className="px-4 py-2.5 font-semibold">
                        {renderInline(h)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-800">
                  {block.rows.map((row, rIdx) => (
                    <tr key={rIdx} className="hover:bg-slate-800/40 transition-colors">
                      {row.map((cell, cIdx) => (
                        <td key={cIdx} className="px-4 py-2.5 align-middle">
                          {renderCellContent(cell)}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          );
        }

        if (block.type === "list") {
          return (
            <ul key={idx} className="space-y-1.5 my-2 pl-4 list-disc text-slate-300">
              {block.items.map((item, i) => (
                <li key={i} className="pl-1">
                  {renderInline(item)}
                </li>
              ))}
            </ul>
          );
        }

        if (block.type === "ordered-list") {
          return (
            <ol key={idx} className="space-y-1.5 my-2 pl-5 list-decimal text-slate-300">
              {block.items.map((item, i) => (
                <li key={i} className="pl-1">
                  {renderInline(item)}
                </li>
              ))}
            </ol>
          );
        }

        // Default paragraph
        return (
          <p key={idx} className="text-slate-300">
            {renderInline(block.content)}
          </p>
        );
      })}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Block Parsing
// ---------------------------------------------------------------------------

type Block =
  | { type: "header"; level: number; content: string }
  | { type: "table"; headers: string[]; rows: string[][] }
  | { type: "list"; items: string[] }
  | { type: "ordered-list"; items: string[] }
  | { type: "paragraph"; content: string };

function splitIntoBlocks(text: string): Block[] {
  const lines = text.split("\n");
  const blocks: Block[] = [];
  let i = 0;

  while (i < lines.length) {
    const rawLine = lines[i];
    const line = rawLine.trim();

    if (!line) {
      i++;
      continue;
    }

    // Header
    const headerMatch = line.match(/^(#{1,3})\s+(.*)$/);
    if (headerMatch) {
      blocks.push({
        type: "header",
        level: headerMatch[1].length,
        content: headerMatch[2],
      });
      i++;
      continue;
    }

    // Markdown Table: starts with '|' and next line has '|---|'
    if (line.startsWith("|") && line.endsWith("|")) {
      const tableLines: string[] = [line];
      i++;
      while (i < lines.length && lines[i].trim().startsWith("|") && lines[i].trim().endsWith("|")) {
        tableLines.push(lines[i].trim());
        i++;
      }

      if (tableLines.length >= 2) {
        const headers = parseTableRow(tableLines[0]);
        // If second line is divider (e.g. |---|---|)
        const isDivider = tableLines[1].replace(/[\s|:-]/g, "").length === 0;
        const rowStartIdx = isDivider ? 2 : 1;
        const rows = tableLines.slice(rowStartIdx).map(parseTableRow);
        blocks.push({
          type: "table",
          headers,
          rows,
        });
        continue;
      }
    }

    // Unordered List (- or *)
    if (/^[-*]\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^[-*]\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^[-*]\s+/, ""));
        i++;
      }
      blocks.push({ type: "list", items });
      continue;
    }

    // Ordered List (1. 2.)
    if (/^\d+\.\s+/.test(line)) {
      const items: string[] = [];
      while (i < lines.length && /^\d+\.\s+/.test(lines[i].trim())) {
        items.push(lines[i].trim().replace(/^\d+\.\s+/, ""));
        i++;
      }
      blocks.push({ type: "ordered-list", items });
      continue;
    }

    // Paragraph: collect lines until empty line or special block
    const pLines: string[] = [rawLine];
    i++;
    while (
      i < lines.length &&
      lines[i].trim() &&
      !lines[i].trim().startsWith("#") &&
      !lines[i].trim().startsWith("|") &&
      !/^[-*]\s+/.test(lines[i].trim()) &&
      !/^\d+\.\s+/.test(lines[i].trim())
    ) {
      pLines.push(lines[i]);
      i++;
    }
    blocks.push({ type: "paragraph", content: pLines.join("\n") });
  }

  return blocks;
}

function parseTableRow(rowStr: string): string[] {
  // e.g. "| col1 | col2 |" -> ["col1", "col2"]
  const trimmed = rowStr.trim();
  const inner = trimmed.startsWith("|") && trimmed.endsWith("|") ? trimmed.slice(1, -1) : trimmed;
  return inner.split("|").map((c) => c.trim());
}

// ---------------------------------------------------------------------------
// Inline Formatter
// ---------------------------------------------------------------------------

function renderInline(text: string): React.ReactNode {
  // Parses **bold** and `code`
  const parts: React.ReactNode[] = [];
  // Tokenize regex: (`[^`]+`|\*\*[^*]+\*\*)
  const regex = /(`[^`]+`|\*\*[^*]+\*\*)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.substring(lastIndex, match.index));
    }
    const token = match[0];
    if (token.startsWith("`") && token.endsWith("`")) {
      parts.push(
        <code
          key={match.index}
          className="px-1.5 py-0.5 rounded bg-slate-800 text-blue-300 font-mono text-xs border border-slate-700 mx-0.5"
        >
          {token.slice(1, -1)}
        </code>
      );
    } else if (token.startsWith("**") && token.endsWith("**")) {
      parts.push(
        <strong key={match.index} className="font-semibold text-slate-100">
          {token.slice(2, -2)}
        </strong>
      );
    }
    lastIndex = regex.lastIndex;
  }

  if (lastIndex < text.length) {
    parts.push(text.substring(lastIndex));
  }

  return parts.length > 0 ? parts : text;
}

function renderCellContent(cell: string): React.ReactNode {
  const trimmed = cell.trim();

  // If cell is a status indicator like "Complete" or "Not Started"
  if (/complete|selesai/i.test(trimmed) && trimmed.length < 25) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-950/80 text-emerald-300 border border-emerald-800">
        <span className="h-1.5 w-1.5 rounded-full bg-emerald-400" />
        {trimmed}
      </span>
    );
  }

  if (/in progress|berjalan/i.test(trimmed) && trimmed.length < 25) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-amber-950/80 text-amber-300 border border-amber-800">
        <span className="h-1.5 w-1.5 rounded-full bg-amber-400" />
        {trimmed}
      </span>
    );
  }

  if (/not started|belum mulai/i.test(trimmed) && trimmed.length < 25) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-slate-800 text-slate-300 border border-slate-700">
        <span className="h-1.5 w-1.5 rounded-full bg-slate-400" />
        {trimmed}
      </span>
    );
  }

  if (/kritis|critical/i.test(trimmed) && trimmed.length < 25) {
    return (
      <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[11px] font-medium bg-rose-950/80 text-rose-300 border border-rose-800">
        <span className="h-1.5 w-1.5 rounded-full bg-rose-400" />
        {trimmed}
      </span>
    );
  }

  return renderInline(trimmed);
}

