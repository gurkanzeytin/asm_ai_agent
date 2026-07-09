'use client';

import ReactMarkdown from 'react-markdown';

interface Props {
  title: string;
  markdown: string;
}

export default function ReportCard({ title, markdown }: Props) {
  return (
    <div className="mb-5">
      <p className="text-xs font-semibold text-chat-accent uppercase tracking-widest mb-2">
        AI Report
      </p>
      <div
        id="report-viewer"
        className="bg-chat-card border border-chat-border rounded-xl p-5"
      >
        <h3 className="text-base font-semibold text-chat-text mb-3">{title}</h3>
        <div className="prose prose-invert prose-sm max-w-none text-chat-text">
          <ReactMarkdown>{markdown}</ReactMarkdown>
        </div>
      </div>
    </div>
  );
}
