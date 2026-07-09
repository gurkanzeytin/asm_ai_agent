'use client';

import { useState } from 'react';

interface Props {
  columns: string[];
  rows: Record<string, unknown>[];
  rowCount: number;
}

export default function ResultTable({ columns, rows, rowCount }: Props) {
  const [copied, setCopied] = useState(false);

  const handleCopy = async () => {
    try {
      // Build tab-separated values string
      const headerRow = columns.join('\t');
      const dataRows = rows.map(row =>
        columns.map(col => String(row[col] ?? '')).join('\t')
      );
      const tsvContent = [headerRow, ...dataRows].join('\n');

      await navigator.clipboard.writeText(tsvContent);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (err) {
      console.error('Failed to copy table data:', err);
    }
  };

  return (
    <div className="mb-5">
      <div className="flex justify-between items-center mb-2">
        <p className="text-xs font-semibold text-chat-accent uppercase tracking-widest">
          Query Result{' '}
          <span className="text-[#555] font-normal normal-case">({rowCount} rows)</span>
        </p>
        {rowCount > 0 && (
          <div className="relative">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 px-2.5 py-1 rounded bg-[#222] border border-chat-border hover:bg-chat-card hover:border-chat-accent text-xs text-[#888] hover:text-white transition-all cursor-pointer font-medium"
              aria-label="Copy table data to clipboard"
            >
              <svg xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24" strokeWidth={1.5} stroke="currentColor" className="w-3.5 h-3.5">
                <path strokeLinecap="round" strokeLinejoin="round" d="M15.75 17.25v3.375c0 .621-.504 1.125-1.125 1.125h-9.75a1.125 1.125 0 0 1-1.125-1.125V7.875c0-.621.504-1.125 1.125-1.125H5.25m11.9-3.664A2.251 2.251 0 0 0 15 2.25h-3a2.251 2.251 0 0 0-2.15 1.586m5.8 0c.065.21.1.433.1.664v.75h-6V4.5c0-.231.035-.454.1-.664M6.75 7.375c0-.621.504-1.125 1.125-1.125h9.75c.621 0 1.125.504 1.125 1.125v3.375c0 .621-.504 1.125-1.125 1.125H7.875a1.125 1.125 0 0 1-1.125-1.125V7.375Z" />
              </svg>
              {copied ? 'Copied!' : 'Copy'}
            </button>
            {copied && (
              <span className="absolute -top-8 left-1/2 -translate-x-1/2 px-2 py-1 rounded bg-chat-accent text-[10px] text-white font-semibold shadow-md pointer-events-none transition-opacity duration-200">
                Copied TSV!
              </span>
            )}
          </div>
        )}
      </div>
      <div className="border border-chat-border rounded-xl overflow-hidden">
        {/* Set max-height and overflow-y-auto so the sticky header remains visible during scrolling */}
        <div className="overflow-x-auto overflow-y-auto max-h-[350px]">
          <table id="result-table" className="w-full text-sm text-chat-text border-collapse">
            <thead>
              <tr className="bg-[#1e1e1e] border-b border-chat-border sticky top-0 z-1">
                {columns.map(col => (
                  <th
                    key={col}
                    className="px-4 py-2.5 text-left text-xs font-semibold text-[#888] uppercase tracking-wide bg-[#1e1e1e]"
                  >
                    {col}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-chat-border last:border-0 hover:bg-[#2a2a2a] transition-colors even:bg-[#151515]"
                >
                  {columns.map(col => (
                    <td key={col} className="px-4 py-2.5">
                      {String(row[col] ?? '')}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
