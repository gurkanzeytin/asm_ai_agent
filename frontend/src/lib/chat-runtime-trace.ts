const TRACE_FLAG = "__ASM_CHAT_RUNTIME_TRACE__";

type TraceGlobal = typeof globalThis & {
  __ASM_CHAT_RUNTIME_TRACE__?: boolean;
};

function isTraceEnabled(): boolean {
  if (!import.meta.env.DEV) return false;
  return (globalThis as TraceGlobal)[TRACE_FLAG] === true;
}

export function traceChatRuntime(boundary: string, details: Record<string, unknown>): void {
  if (!isTraceEnabled()) return;
  console.debug(`[chat-runtime:${boundary}]`, details);
}
