'use client';

import { TimingData } from '@/types/report';

interface Props {
  timing: TimingData;
}

const STAGES: { key: keyof Omit<TimingData, 'llm_total_ms' | 'total_ms'>; label: string }[] = [
  { key: 'retrieve_context_ms', label: 'Retrieve Context' },
  { key: 'generate_sql_ms',     label: 'Generate SQL' },
  { key: 'validate_sql_ms',     label: 'Validate SQL' },
  { key: 'execute_sql_ms',      label: 'Execute SQL' },
  { key: 'generate_report_ms',  label: 'Generate Report' },
];

function fmtMs(ms: number | null): string {
  if (ms === null || ms === undefined) return '—';
  if (ms >= 1000) return `${(ms / 1000).toFixed(1)} s`;
  return `${Math.round(ms)} ms`;
}

export default function PipelineTimings({ timing }: Props) {
  return (
    <div id="pipeline-timings" className="mt-3 pt-3 border-t border-chat-border">
      <p className="text-xs font-semibold text-chat-accent uppercase tracking-widest mb-2">
        Pipeline Timings
      </p>
      <div className="rounded-xl border border-chat-border overflow-hidden text-xs">
        <table className="w-full">
          <tbody>
            {STAGES.map(({ key, label }) => (
              <tr
                key={key}
                className="border-b border-chat-border last:border-0 even:bg-[#1a1a1a] hover:bg-[#232323] transition-colors"
              >
                <td className="px-4 py-2 text-[#888]">{label}</td>
                <td className="px-4 py-2 text-right font-mono text-chat-text tabular-nums">
                  {fmtMs(timing[key])}
                </td>
              </tr>
            ))}
            {/* Separator */}
            <tr className="border-t border-chat-border bg-[#1e1e1e]">
              <td className="px-4 py-2 font-semibold text-chat-text">Total</td>
              <td className="px-4 py-2 text-right font-mono font-semibold text-chat-accent tabular-nums">
                {fmtMs(timing.total_ms)}
              </td>
            </tr>
            {timing.llm_total_ms !== null && timing.llm_total_ms !== undefined && (
              <tr className="bg-[#1a1a1a]">
                <td className="px-4 py-1.5 text-[#555] pl-6">↳ LLM inference</td>
                <td className="px-4 py-1.5 text-right font-mono text-[#666] tabular-nums">
                  {fmtMs(timing.llm_total_ms)}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
