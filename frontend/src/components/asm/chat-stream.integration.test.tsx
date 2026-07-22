import { useState } from "react";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { useChatController } from "@/hooks/use-chat-controller";
import { tr } from "@/locales/tr";
import { ChatMessage } from "./ChatMessage";

vi.mock("sonner", () => ({
  toast: {
    error: vi.fn(),
    info: vi.fn(),
    success: vi.fn(),
    warning: vi.fn(),
  },
}));

function ChatFlowHarness() {
  const chat = useChatController();
  const [submittedConversationId, setSubmittedConversationId] = useState<string | null>(null);

  return (
    <div>
      <output data-testid="active-conversation">{chat.activeId}</output>
      <output data-testid="submitted-conversation">{submittedConversationId}</output>
      <button type="button" onClick={chat.newChat}>
        Yeni sohbet
      </button>
      <form
        onSubmit={(event) => {
          event.preventDefault();
          setSubmittedConversationId(chat.activeId);
          void chat.send();
        }}
      >
        <label>
          Soru
          <input value={chat.input} onChange={(event) => chat.setInput(event.target.value)} />
        </label>
        <button type="submit">Gönder</button>
      </form>
      <output data-testid="generation-state">{chat.isGenerating ? "loading" : "idle"}</output>
      <div data-testid="conversation-messages">
        {chat.messages.map((message) => (
          <div key={message.id} data-message-id={message.id} data-message-role={message.role}>
            <ChatMessage message={message} />
          </div>
        ))}
      </div>
    </div>
  );
}

describe("streamed chat UI integration", () => {
  afterEach(() => {
    delete (globalThis as typeof globalThis & { __ASM_CHAT_RUNTIME_TRACE__?: boolean })
      .__ASM_CHAT_RUNTIME_TRACE__;
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("keeps a zero-row terminal report visible in the active conversation", async () => {
    (
      globalThis as typeof globalThis & { __ASM_CHAT_RUNTIME_TRACE__?: boolean }
    ).__ASM_CHAT_RUNTIME_TRACE__ = true;
    const traceSpy = vi.spyOn(console, "debug").mockImplementation(() => undefined);
    const encoder = new TextEncoder();
    const terminal = {
      type: "complete",
      data: {
        success: true,
        workflow_id: "workflow-zero-result",
        session_id: "active-test-conversation",
        question: "Sadece gerçekleşenleri göster.",
        outcome: "NO_RESULT_GUIDANCE",
        query_result: { columns: [], rows: [], row_count: 0 },
        report: {
          title: "Sonuç Bulunamadı",
          markdown:
            "# Sonuç Bulunamadı\n\nSorgu başarıyla çalıştı ancak belirtilen kriterlere uygun kayıt bulunamadı.",
        },
        analytics: null,
        visualization: null,
      },
    };
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(
          encoder.encode(
            `${JSON.stringify({ type: "progress", stage: "executing_sql" })}\n${JSON.stringify(terminal)}\n`,
          ),
        );
        controller.close();
      },
    });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(body, {
          status: 200,
          headers: { "Content-Type": "application/x-ndjson" },
        }),
      ),
    );
    const user = userEvent.setup();
    render(<ChatFlowHarness />);

    await user.click(screen.getByRole("button", { name: "Yeni sohbet" }));
    const activeConversationId = screen.getByTestId("active-conversation").textContent;
    expect(activeConversationId).not.toBe("initial-conversation");

    await user.type(screen.getByLabelText("Soru"), "Sadece gerçekleşenleri göster.");
    await user.click(screen.getByRole("button", { name: "Gönder" }));

    await waitFor(() => expect(screen.getByTestId("generation-state").textContent).toBe("idle"));
    expect(screen.getByRole("heading", { name: "Sonuç Bulunamadı" })).not.toBeNull();
    expect(screen.getByText(/belirtilen kriterlere uygun kayıt bulunamadı/)).not.toBeNull();
    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.queryByText(tr.chat.workflowStages.executing_sql)).toBeNull();
    expect(screen.getByTestId("submitted-conversation").textContent).toBe(activeConversationId);
    expect(
      screen
        .getByTestId("conversation-messages")
        .querySelectorAll('[data-message-role="assistant"]'),
    ).toHaveLength(1);

    await Promise.resolve();
    expect(screen.getByRole("heading", { name: "Sonuç Bulunamadı" })).not.toBeNull();

    const trace = Object.fromEntries(
      traceSpy.mock.calls.map(([boundary, details]) => [boundary, details]),
    ) as Record<string, Record<string, unknown>>;
    expect(trace["[chat-runtime:complete-parsed]"]).toMatchObject({
      eventType: "complete",
      workflowId: "workflow-zero-result",
      reportMarkdownLength: terminal.data.report.markdown.length,
    });
    expect(trace["[chat-runtime:before-completion-update]"]).toMatchObject({
      targetConversationId: activeConversationId,
      activeConversationId,
    });
    expect(trace["[chat-runtime:completion-updater]"]).toMatchObject({
      targetAssistantFound: true,
      oldContent: "",
      newContent: terminal.data.report.markdown,
    });
    expect(trace["[chat-runtime:state-committed]"].visibleAssistantContentLengths).toEqual([
      expect.objectContaining({ contentLength: terminal.data.report.markdown.length }),
    ]);
    expect(trace["[chat-runtime:chat-message-render]"]).toMatchObject({
      role: "assistant",
      streaming: false,
      status: "success",
      contentLength: terminal.data.report.markdown.length,
      outcome: "NO_RESULT_GUIDANCE",
      rowCount: 0,
      returnsNull: false,
      returnsLoadingPlaceholder: false,
    });
  });
});
