'use client';

import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';

interface Props {
  title: string;
  markdown: string;
}

export default function ReportViewer({ title, markdown }: Props) {
  return (
    <section className="mb-6">
      <h2 className="text-sm font-semibold text-gray-400 uppercase tracking-wide mb-2">
        AI Report
      </h2>
      <div
        id="report-viewer"
        className="bg-gray-800 border border-gray-700 rounded-md p-5 text-gray-200 text-sm
                   prose prose-invert prose-sm max-w-none prose-headings:font-semibold prose-a:text-chat-accent prose-pre:bg-chat-code prose-pre:border prose-pre:border-chat-border"
      >
        <h3 className="text-base font-semibold text-white mb-3">{title}</h3>
        <ReactMarkdown remarkPlugins={[remarkGfm]}>{markdown}</ReactMarkdown>
      </div>
    </section>
  );
}
