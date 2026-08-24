"use client";

import { useMemo } from "react";
import { PanelBody, PanelHint, PanelToolbar } from "@/components/panels/shared/PanelShell";
import type { PanelProps } from "@/components/runtime/types";
import { Badge } from "@/components/ui/Badge";
import { useLastRun } from "@/lib/practice";
import { workspaceKey } from "@/lib/store";
import { cfgString, recordEntry } from "@/lib/utils";

const TABULAR_RE = /\.(csv|tsv|json)$/i;
const MAX_ROWS = 500;

type Table = { columns: string[]; rows: string[][] };
type Parsed = Table | { raw: string };

/** A small, quote-aware delimited parser, enough for run-emitted CSV/TSV artifacts. */
function parseDelimited(text: string, delimiter: string): Table {
  const rows: string[][] = [];
  let field = "";
  let row: string[] = [];
  let inQuotes = false;
  for (let i = 0; i < text.length; i++) {
    const char = text[i];
    if (inQuotes) {
      if (char === '"') {
        if (text[i + 1] === '"') {
          field += '"';
          i++;
        } else inQuotes = false;
      } else field += char;
    } else if (char === '"') inQuotes = true;
    else if (char === delimiter) {
      row.push(field);
      field = "";
    } else if (char === "\n") {
      row.push(field);
      rows.push(row);
      row = [];
      field = "";
    } else if (char !== "\r") field += char;
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  const columns = rows.shift() ?? [];
  return { columns, rows };
}

function cellText(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

/** Array-of-objects JSON becomes a table; anything else is shown as pretty JSON. */
function parseJson(text: string): Parsed {
  try {
    const data: unknown = JSON.parse(text);
    if (Array.isArray(data) && data.every((item) => item !== null && typeof item === "object" && !Array.isArray(item))) {
      const columns: string[] = [];
      for (const item of data) {
        for (const key of Object.keys(item as Record<string, unknown>)) if (!columns.includes(key)) columns.push(key);
      }
      const rows = (data as Array<Record<string, unknown>>).map((item) => columns.map((column) => cellText(item[column])));
      return { columns, rows };
    }
    return { raw: JSON.stringify(data, null, 2) };
  } catch {
    return { raw: text };
  }
}

function parseDataset(name: string, content: string): Parsed {
  if (/\.json$/i.test(name)) return parseJson(content);
  if (/\.tsv$/i.test(name)) return parseDelimited(content, "\t");
  return parseDelimited(content, ",");
}

function pickDataset(artifacts: Record<string, string>, entry: string | null): { name: string; content: string } | null {
  return (
    recordEntry(artifacts, entry) ??
    recordEntry(
      artifacts,
      Object.keys(artifacts).find((name) => TABULAR_RE.test(name)),
    )
  );
}

/**
 * Browses a tabular artifact emitted by the workspace's last run: the same
 * artifact channel the browser-preview panel reads, viewed as a grid instead of a
 * page. CSV, TSV and array-of-objects JSON are understood; other JSON is shown
 * pretty-printed. The parser is generic: it never assumes a schema, so any subject
 * that produces a data file gets a viewer for free.
 */
export function DatasetViewerPanel({ runtime, mode, panel }: PanelProps) {
  const entry = cfgString(panel.config, "entry") ?? cfgString(panel.config, "source");
  const { result } = useLastRun(workspaceKey(runtime.id, mode));
  const dataset = useMemo(() => (result ? pickDataset(result.artifacts, entry) : null), [result, entry]);
  const parsed = useMemo(() => (dataset ? parseDataset(dataset.name, dataset.content) : null), [dataset]);

  if (!dataset || !parsed) {
    return <PanelHint title="No dataset" description="Run a task that emits a .csv, .tsv or .json artifact to browse it here." />;
  }

  if ("raw" in parsed) {
    return (
      <>
        <PanelToolbar>
          <span className="truncate font-mono text-2xs text-muted">{dataset.name}</span>
        </PanelToolbar>
        <PanelBody className="p-pad">
          <pre className="overflow-auto rounded border border-line bg-canvas p-2 font-mono text-2xs text-ink">{parsed.raw}</pre>
        </PanelBody>
      </>
    );
  }

  const shown = parsed.rows.slice(0, MAX_ROWS);
  return (
    <>
      <PanelToolbar>
        <span className="min-w-0 flex-1 truncate font-mono text-2xs text-muted">{dataset.name}</span>
        <Badge tone="neutral">
          {parsed.rows.length} rows · {parsed.columns.length} cols
        </Badge>
      </PanelToolbar>
      <PanelBody className="p-0">
        <table className="w-full border-collapse text-2xs">
          <thead className="sticky top-0 bg-raised">
            <tr>
              {parsed.columns.map((column, index) => (
                <th key={index} className="whitespace-nowrap border-b border-line px-2 py-1 text-left font-semibold text-ink">
                  {column || <span className="text-faint">col {index + 1}</span>}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {shown.map((row, rowIndex) => (
              <tr key={rowIndex} className="odd:bg-surface/40">
                {parsed.columns.map((_, columnIndex) => (
                  <td key={columnIndex} className="whitespace-pre-wrap border-b border-line/60 px-2 py-1 align-top font-mono text-muted">
                    {row[columnIndex] ?? ""}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
        {parsed.rows.length > MAX_ROWS ? (
          <div className="px-2 py-1 text-2xs text-faint">
            Showing first {MAX_ROWS} of {parsed.rows.length} rows.
          </div>
        ) : null}
      </PanelBody>
    </>
  );
}
