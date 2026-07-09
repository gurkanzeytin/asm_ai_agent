'use client';

import { ReportResponse } from '@/types/report';
import SqlCard from './SqlCard';
import ResultTable from './ResultTable';
import ReportCard from './ReportCard';
import MetadataFooter from './MetadataFooter';
import PipelineTimings from './PipelineTimings';

/* ── Message type shared with page.tsx ── */
export type Message =
  | { role: 'user'; content: string }
  | { role: 'assistant'; data: ReportResponse };

/* ── Small reusable assistant avatar ── */
function AssistantAvatar() {
  return (
    <div className="w-7 h-7 rounded-full bg-chat-accent flex items-center justify-center flex-shrink-0">
      {/* Minimalist robot/AI icon */}
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 24 24"
        fill="currentColor"
        className="w-4 h-4 text-white"
      >
        <path
          fillRule="evenodd"
          d="M9 4.5a.75.75 0 01.721.544l.813 2.846a3.75 3.75 0 002.576 2.576l2.846.813a.75.75 0 010 1.442l-2.846.813a3.75 3.75 0 00-2.576 2.576l-.813 2.846a.75.75 0 01-1.442 0l-.813-2.846a3.75 3.75 0 00-2.576-2.576l-2.846-.813a.75.75 0 010-1.442l2.846-.813A3.75 3.75 0 007.466 7.89l.813-2.846A.75.75 0 019 4.5zM18 1.5a.75.75 0 01.728.568l.258 1.036c.236.94.97 1.674 1.91 1.91l1.036.258a.75.75 0 010 1.456l-1.036.258c-.94.236-1.674.97-1.91 1.91l-.258 1.036a.75.75 0 01-1.456 0l-.258-1.036a2.625 2.625 0 00-1.91-1.91l-1.036-.258a.75.75 0 010-1.456l1.036-.258a2.625 2.625 0 001.91-1.91l.258-1.036A.75.75 0 0118 1.5zM16.5 15a.75.75 0 01.712.513l.394 1.183c.15.447.5.799.948.948l1.183.395a.75.75 0 010 1.422l-1.183.395c-.447.15-.799.5-.948.948l-.395 1.183a.75.75 0 01-1.422 0l-.395-1.183a1.5 1.5 0 00-.948-.948l-1.183-.395a.75.75 0 010-1.422l1.183-.395c.447-.15.799-.5.948-.948l.395-1.183A.75.75 0 0116.5 15z"
          clipRule="evenodd"
        />
      </svg>
    </div>
  );
}

/* ── Main component ── */
interface Props {
  message: Message;
}

export default function ChatMessage({ message }: Props) {
  /* User bubble — right-aligned */
  if (message.role === 'user') {
    return (
      <div className="flex justify-end mb-6 px-1">
        <div className="max-w-xl bg-chat-card border border-chat-border rounded-2xl
                        px-4 py-3 text-sm text-chat-text leading-relaxed">
          {message.content}
        </div>
      </div>
    );
  }

  /* Assistant bubble — left-aligned with avatar */
  const { data } = message;

  return (
    <div className="mb-8">
      {/* Header row */}
      <div className="flex items-center gap-2 mb-3">
        <AssistantAvatar />
        <span className="text-sm font-semibold text-chat-text">Assistant</span>
      </div>

      {/* Content indented under the avatar */}
      <div className="ml-9 space-y-1">
        {data.generated_sql && <SqlCard sql={data.generated_sql} />}

        {data.query_result && (
          <ResultTable
            columns={data.query_result.columns}
            rows={data.query_result.rows}
            rowCount={data.query_result.row_count}
          />
        )}

        {data.report && (
          <ReportCard title={data.report.title} markdown={data.report.markdown} />
        )}

        {data.metadata && (
          <MetadataFooter
            provider={data.metadata.provider}
            model={data.metadata.model}
            latencyMs={data.metadata.latency_ms}
            workflowId={data.workflow_id ?? '—'}
          />
        )}

        {process.env.NODE_ENV === 'development' && data.timing && (
          <PipelineTimings timing={data.timing} />
        )}
      </div>
    </div>
  );
}
