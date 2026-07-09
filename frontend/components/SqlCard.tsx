'use client';

import { useState } from 'react';

interface Props {
  sql: string;
}

export default function SqlCard({ sql }: Props) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="mb-5">
      {/* Clickable Header */}
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-2 text-xs font-semibold text-chat-accent uppercase tracking-widest mb-2 select-none hover:text-white transition-colors focus:outline-none"
        aria-expanded={expanded}
        aria-controls="sql-collapse-container"
      >
        <span className="inline-block transition-transform duration-200" style={{ transform: expanded ? 'rotate(90deg)' : 'rotate(0deg)' }}>
          ▶
        </span>
        Generated SQL
        <span className="text-[#555] normal-case font-normal">({expanded ? 'click to collapse' : 'click to expand'})</span>
      </button>

      <div
        id="sql-collapse-container"
        className="bg-chat-code border border-chat-border rounded-xl overflow-hidden transition-all duration-300 ease-in-out"
        style={{
          maxHeight: expanded ? '1000px' : '0px',
          opacity: expanded ? 1 : 0,
          borderWidth: expanded ? '1px' : '0px',
        }}
      >
        {/* Fake editor toolbar */}
        <div className="flex items-center gap-1.5 px-4 py-2 border-b border-chat-border bg-[#222]">
          <span className="w-3 h-3 rounded-full bg-[#FF5F57]" />
          <span className="w-3 h-3 rounded-full bg-[#FFBD2E]" />
          <span className="w-3 h-3 rounded-full bg-[#28C840]" />
          <span className="ml-3 text-xs text-[#555]">sql</span>
        </div>
        <pre
          id="sql-viewer"
          className="p-4 text-sm text-green-400 font-mono leading-relaxed
                     whitespace-pre-wrap break-words overflow-x-auto"
        >
          {sql}
        </pre>
      </div>
    </div>
  );
}
