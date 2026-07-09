'use client';

interface Props {
  provider: string;
  model: string;
  latencyMs: number;
  workflowId: string;
}

export default function MetadataFooter({ provider, model, latencyMs, workflowId }: Props) {
  return (
    <div
      id="metadata-panel"
      className="mt-1 pt-3 border-t border-chat-border"
    >
      <div className="flex flex-wrap gap-x-5 gap-y-1 text-xs text-[#666]">
        <span>
          Provider <span className="text-[#999] ml-1">{provider}</span>
        </span>
        <span>
          Model <span className="text-[#999] ml-1">{model}</span>
        </span>
        <span>
          Latency <span className="text-[#999] ml-1">{latencyMs} ms</span>
        </span>
        <span className="font-mono">
          ID <span className="text-[#777] ml-1 text-[10px]">{workflowId}</span>
        </span>
      </div>
    </div>
  );
}
