import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ChatMessage, TypingIndicator } from "./ChatMessage";
import { ChatHeader } from "./ChatHeader";
import { InfoPanel } from "./InfoPanel";
import { PromptBox } from "./PromptBox";
import { Sidebar } from "./Sidebar";
import { SqlResultsTable } from "./SqlResultsTable";
import { SqlChartPanel } from "./SqlChartPanel";

describe("sohbet arayüzü düzenlemeleri", () => {
  it("tamamlanan sıfır sonuç yanıtını görünür asistan metni olarak gösterir", () => {
    render(
      <ChatMessage
        message={{
          id: "empty-result",
          role: "assistant",
          content: "Belirtilen kriterlere uygun kayıt bulunamadı.",
          createdAt: Date.now(),
          streaming: false,
          status: "success",
        }}
      />,
    );

    expect(screen.getByText("Belirtilen kriterlere uygun kayıt bulunamadı.")).toBeTruthy();
  });

  it("uzun temel gösterge değerlerini sabit ve dengeli kartlarda sınırlar", () => {
    const { container } = render(
      <ChatMessage
        message={{
          id: "metrics-layout",
          role: "assistant",
          content: "Özet",
          createdAt: 1,
          metricCards: [
            {
              value: "ASM MR ŞIEMENS, MANYETİK REZONANS BİRİMİ",
              label: "En Yüksek Kategori",
              context: "Tekil Hasta Sayısı",
            },
            {
              value: "1",
              label: "Toplam",
              context: "Tekil Hasta Sayısı",
            },
          ],
        }}
      />,
    );

    expect(screen.getAllByText("Tekil Hasta Sayısı")).toHaveLength(1);
    expect(container.querySelector(".lg\\:grid-cols-4")).toBeTruthy();
    expect(container.querySelector(".min-h-\\[104px\\]")).toBeTruthy();
    expect(screen.getByTitle("ASM MR ŞIEMENS, MANYETİK REZONANS BİRİMİ")).toBeTruthy();
  });

  it("backend aşamasını düşünme animasyonunda gösterir", () => {
    render(<TypingIndicator stage="executing_sql" />);
    expect(screen.getByText("Veriler getiriliyor…")).toBeTruthy();
  });

  it("sorgu hatasını uygun aksiyonlarla gösterir", () => {
    render(
      <ChatMessage
        message={{
          id: "query-error",
          role: "assistant",
          content: "",
          createdAt: 1,
          status: "error",
          errorKind: "query",
          prompt: "Soru",
        }}
        onPrompt={() => undefined}
        onEditPrompt={() => undefined}
      />,
    );
    expect(screen.getByText("Sorgu tamamlanamadı")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Yeniden dene" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "Soruyu düzenle" })).toBeTruthy();
  });

  it("üç panelin üst ayraçlarını aynı yükseklikte hizalar", () => {
    const { container } = render(
      <>
        <Sidebar
          conversations={[]}
          activeId={null}
          onSelect={() => undefined}
          onNew={() => undefined}
          onToggleFavorite={() => undefined}
          onDelete={() => undefined}
          collapsed={false}
          onToggleCollapse={() => undefined}
        />
        <ChatHeader title="Yeni görüşme" onToggleInfo={() => undefined} infoOpen />
        <InfoPanel open responseMs={0} isThinking={false} sql={null} />
      </>,
    );

    const topBars = container.querySelectorAll("aside > div:first-child, header");
    expect(topBars).toHaveLength(3);
    topBars.forEach((bar) => {
      expect(bar.className).toContain("h-16");
      expect(bar.className).toContain("border-b");
    });
  });

  it("teknik detayları kontrollü açıp kapatır", async () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-1",
          role: "assistant",
          content: "Yanıt",
          createdAt: 1,
          showSqlTable: true,
          sqlResult: {
            columns: ["ad", "değer"],
            rows: [{ ad: "A", değer: 10 }],
          },
        }}
      />,
    );

    const trigger = screen.getByRole("button", { name: "Teknik detaylar" });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    await waitFor(() => expect(screen.getByText("SQL Sonucu")).toBeTruthy());

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("sohbet girişinin altında sağlık uyarısı göstermez", () => {
    render(
      <PromptBox
        value=""
        onChange={() => undefined}
        onSend={() => undefined}
        onStop={() => undefined}
        isGenerating={false}
      />,
    );

    expect(screen.queryByText(/hata yapabilir/i)).toBeNull();
  });

  it("uygulama adını Med Agent olarak gösterir", () => {
    render(
      <Sidebar
        conversations={[]}
        activeId={null}
        onSelect={() => undefined}
        onNew={() => undefined}
        onToggleFavorite={() => undefined}
        onDelete={() => undefined}
        collapsed={false}
        onToggleCollapse={() => undefined}
      />,
    );

    expect(screen.getByText("Med Agent")).toBeTruthy();
    expect(screen.queryByText("ASM AI Agent")).toBeNull();
    const newChat = screen.getByRole("button", { name: "Yeni sohbet" });
    expect(newChat.className).toContain("h-10");
    expect(newChat.parentElement?.className).toContain("pt-4");
    expect(newChat.parentElement?.className).toContain("gap-3");
    expect(screen.getByRole("textbox").className).toContain("h-10");
  });

  it("düşünme avatarını ve balonunu aynı merkez ve yükseklikte tutar", () => {
    const { container } = render(<TypingIndicator />);
    const root = container.firstElementChild;
    const [avatar, bubble] = Array.from(root?.children ?? []);

    expect(root?.className).toContain("items-center");
    expect(avatar?.className).toContain("h-10");
    expect(bubble?.className).toContain("h-10");
    expect(bubble?.className).not.toContain("glass");
  });

  it("asistan yanıtını sohbet balonu olmadan gösterir", () => {
    const { container } = render(
      <ChatMessage
        message={{
          id: "assistant-plain",
          role: "assistant",
          content: "Çerçevesiz yanıt",
          createdAt: 1,
        }}
      />,
    );

    const prose = screen.getByText("Çerçevesiz yanıt").closest(".prose-chat");
    expect(prose?.parentElement?.className).not.toContain("glass");
    expect(prose?.parentElement?.className).not.toContain("py-1");
    expect(prose?.parentElement?.className).not.toContain("bg-");
    const assistantLogo = container.querySelector('img[alt="Med Agent logosu"]');
    expect(assistantLogo?.closest(".h-9")?.className).not.toContain("rounded-full");
    expect(assistantLogo?.getAttribute("width")).toBe("36");
  });

  it("gönder düğmesini giriş alanının içine alır ve kısayol açıklamalarını kaldırır", () => {
    render(
      <PromptBox
        value="Soru"
        onChange={() => undefined}
        onSend={() => undefined}
        onStop={() => undefined}
        isGenerating={false}
      />,
    );

    const send = screen.getByRole("button", { name: "Gönder" });
    expect(send.className).toContain("absolute");
    expect(send.className).toContain("bottom-2.5");
    expect(send.className).toContain("h-10");
    expect(screen.queryByText("Yeni satır")).toBeNull();
  });

  it("marka ve sohbet başlıklarını ölçülü biçimde büyütür", () => {
    const { rerender } = render(
      <Sidebar
        conversations={[]}
        activeId={null}
        onSelect={() => undefined}
        onNew={() => undefined}
        onToggleFavorite={() => undefined}
        onDelete={() => undefined}
        collapsed={false}
        onToggleCollapse={() => undefined}
      />,
    );

    expect(screen.getByText("Med Agent").className).toContain("text-[15px]");
    expect(screen.getByText("Sağlık Zekâsı").className).toContain("text-xs");

    rerender(<ChatHeader title="Yeni görüşme" onToggleInfo={() => undefined} infoOpen={false} />);
    expect(screen.getByText("Yeni görüşme").className).toContain("text-[15px]");
    expect(screen.queryByRole("button", { name: "Sohbeti temizle" })).toBeNull();
  });

  it("ilk asistan başlığını avatarın üst çizgisine yaklaştırır", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-heading",
          role: "assistant",
          content: "# Sonuç Bulunamadı\n\nAçıklama",
          createdAt: 1,
        }}
      />,
    );

    expect(screen.getByRole("heading", { name: "Sonuç Bulunamadı" }).className).toContain(
      "first:mt-0",
    );
  });

  it("SQL seçim kutularını aynı sol eksene hizalar", () => {
    render(
      <SqlResultsTable
        data={{ columns: ["ad"], rows: [{ ad: "ASM" }] }}
        virtualizeThreshold={100}
      />,
    );

    const selectAll = screen.getByRole("checkbox", { name: "Görünen tüm satırları seç" });
    const selectRow = screen.getByRole("checkbox", { name: "1. satırı seç" });
    expect(selectAll.parentElement?.className).toContain("justify-start");
    expect(selectAll.closest("th")?.className).toContain("px-2");
    expect(selectRow.closest("td")?.className).toContain("px-2");

    const dataCell = screen.getByText("ASM").closest("td");
    expect(dataCell?.className).toContain("py-2");
    fireEvent.click(screen.getByRole("button", { name: "Satır yoğunluğunu değiştir" }));
    expect(dataCell?.className).toContain("py-3");
  });

  it("başarılı yanıt altında gereksiz devam aksiyonlarını göstermez", () => {
    render(
      <ChatMessage
        message={{
          id: "assistant-actions",
          role: "assistant",
          content: "Yanıt",
          createdAt: 1,
          status: "success",
          prompt: "İlk soru",
        }}
      />,
    );

    expect(screen.queryByRole("button", { name: "Geçen dönemle karşılaştır" })).toBeNull();
    expect(screen.queryByRole("button", { name: /Yeniden oluştur/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /Kısalt/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Kopyala" })).toBeTruthy();
  });

  it("hatalı yanıtta yeniden deneme ve soru düzenlemeyi görünür tutar", () => {
    const onPrompt = vi.fn();
    const onEditPrompt = vi.fn();
    const { container } = render(
      <ChatMessage
        message={{
          id: "assistant-error",
          role: "assistant",
          content: "İstek başarısız",
          createdAt: 1,
          status: "error",
          errorKind: "query",
          prompt: "Başarısız soru",
        }}
        onPrompt={onPrompt}
        onEditPrompt={onEditPrompt}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /Yeniden dene/ }));
    fireEvent.click(screen.getByRole("button", { name: /Soruyu düzenle/ }));
    expect(onPrompt).toHaveBeenCalledWith("Başarısız soru");
    expect(onEditPrompt).toHaveBeenCalledWith("Başarısız soru");
    expect(container.querySelector(".opacity-100")).toBeTruthy();
  });

  it("backend önerisi varsa grafik panelini başlangıçta açar", async () => {
    render(
      <SqlResultsTable
        data={{
          columns: ["ay", "değer"],
          rows: [
            { ay: "Ocak", değer: 1 },
            { ay: "Şubat", değer: 2 },
          ],
          visualization: "BAR_CHART",
        }}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Grafik panelini aç/kapat" }).getAttribute("aria-pressed"),
    ).toBe("true");
  });

  it("grafik kategorisini klavyeyle tablo filtresine iletir", () => {
    const onCategorySelect = vi.fn();
    render(
      <SqlChartPanel
        columns={["ay", "değer"]}
        rows={[
          { ay: "Ocak", değer: 1 },
          { ay: "Şubat", değer: 2 },
        ]}
        initialType="bar"
        onCategorySelect={onCategorySelect}
      />,
    );

    fireEvent.keyDown(screen.getByRole("img"), { key: "Enter" });
    expect(onCategorySelect).toHaveBeenCalledWith("ay", "Şubat");
  });
});
