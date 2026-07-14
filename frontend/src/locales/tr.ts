/**
 * Merkezî Türkçe arayüz sözlüğü.
 *
 * Tüm kullanıcıya görünen metinler bu dosyadan tüketilir; bileşenlerin içine
 * sabit metin yazılmaz. İkinci bir dil eklenene kadar hafif bir sözlük yeterlidir
 * (i18n kütüphanesi bilinçli olarak eklenmedi).
 */
export const tr = {
  common: {
    settings: "Ayarlar",
    details: "Detaylar",
    send: "gönder",
    newLine: "yeni satır",
    copy: "Kopyala",
    copied: "Kopyalandı",
    copyFailed: "Kopyalama başarısız",
    stop: "Durdur",
    clear: "Temizle",
  },

  sidebar: {
    appTagline: "Sağlık Zekâsı",
    newChat: "Yeni sohbet",
    searchConversations: "Sohbetlerde ara",
    favorites: "Favoriler",
    recent: "Son sohbetler",
    noConversations: "Henüz sohbet yok",
    toggleSidebar: "Kenar çubuğunu aç/kapat",
    todaysPatientStatistics: "Bugünün hasta istatistikleri",
    q3CenterPerformance: "3. çeyrek merkez performansı",
    busiestDoctorThisWeek: "Bu haftanın en yoğun doktoru",
    favoriteConversation: "Favorilere ekle/çıkar",
    deleteConversation: "Sohbeti sil",
  },

  header: {
    online: "Yapay zekâ · Çevrimiçi",
    newConversation: "Yeni görüşme",
    toggleTheme: "Temayı değiştir",
    clearChat: "Sohbeti temizle",
    detailsPanel: "Detay paneli",
  },

  welcome: {
    titleBefore: "Bugün size nasıl yardımcı",
    titleHighlight: "olabilirim",
    description:
      "Kurumunuz hakkında sorular sorun, veritabanında sorgular çalıştırın, belgeleri analiz edin veya doğal dille raporlar oluşturun.",
  },

  details: {
    title: "Detaylar",
    close: "Paneli kapat",
    conversation: "Görüşme",
    responseTime: "Yanıt süresi",
    agentStatus: "Ajan durumu",
    thinking: "Sorgu üzerinde çalışılıyor…",
    idle: "Hazır — yeni görev bekleniyor",
    sqlQuery: "SQL sorgusu",
    toolCalls: "Araç çağrıları",
    processSummary: "İşlem özeti",
    processSummaryDescription:
      "İstek yorumlandı, ilgili veri kaynakları seçildi, SQL sorgusu oluşturuldu, sonuçlar doğrulandı ve nihai yanıt hazırlandı.",
  },

  suggestions: {
    patientStatistics: {
      title: "Bugünün hasta istatistikleri",
      description: "Bugünkü hasta istatistiklerini tüm aile sağlığı merkezleri için göster.",
    },
    centerPerformance: {
      title: "Merkez performansı",
      description: "Aile sağlığı merkezlerinin performansını analiz et.",
    },
    busiestDoctor: {
      title: "En yoğun doktor",
      description: "Bu haftanın en yoğun doktorunu ve hasta sayılarını bul.",
    },
    monthlyReport: {
      title: "Aylık rapor",
      description: "Aylık performans ve faaliyet raporu oluştur.",
    },
  },

  chat: {
    placeholder: "Bir şey sorun...",
    warning: "ASM AI hata yapabilir. Önemli sağlık bilgilerini doğrulayın.",
    thinking: "Düşünüyor…",
    uploadFile: "Dosya yükle",
    uploadFileDescription: "Belge, görsel veya PDF ekleyin.",
    voiceInput: "Sesli giriş",
    voiceInputDescription: "Mikrofon etkinleştirildiğinde kayıt başlayacak.",
    sendLabel: "Gönder",
    noReport: "İş akışı tamamlandı ancak rapor oluşturulamadı.",
    requestFailedFallback:
      "İstek tamamlanamadı. Lütfen sorunuzu farklı bir şekilde ifade etmeyi deneyin.",
    unexpectedError: "Sunucuya bağlanırken beklenmeyen bir hata oluştu.",
    responseReady: "Yanıt hazır",
    requestFailed: "İstek başarısız",
    generationStopped: "Yanıt durduruldu",
    chatCleared: "Sohbet temizlendi",
    conversationDeleted: "Sohbet silindi",
  },

  sqlTable: {
    title: "SQL Sonucu",
    rows: "satır",
    virtualized: "sanallaştırılmış",
    virtualizedTooltip: "Hızlı kaydırma için satır sanallaştırma etkin",
    searchRows: "Satırlarda ara",
    copyTable: "Tabloyu panoya kopyala",
    tableCopied: "Tablo kopyalandı",
    tableCopiedDescription: "Bir elektronik tabloya veya belgeye yapıştırın.",
    stats: "İstatistik",
    toggleStats: "Özet istatistikleri aç/kapat",
    chart: "Grafik",
    toggleChart: "Grafik panelini aç/kapat",
    exportCsv: "CSV indir",
    exportCsvLabel: "Sonuçları CSV olarak dışa aktar",
    csvExported: "CSV dışa aktarıldı",
    noMatchingRows: "Eşleşen satır yok",
    scrollableResults: "Kaydırılabilir sonuçlar",
    scrollToLoadMore: "satır · daha fazlası için kaydırın",
    virtualizedRendering: "Sanallaştırılmış görünüm",
    pagination: "Tablo sayfalama",
    showing: "Gösterilen",
    of: "/",
    previousPage: "Önceki sayfa",
    nextPage: "Sonraki sayfa",
    page: "Sayfa",
    sortedBy: (col: string, dir: "asc" | "desc") =>
      `${col} sütununa göre ${dir === "asc" ? "artan" : "azalan"} sıralandı`,
    sortCleared: "Sıralama kaldırıldı",
    sortBy: (col: string) => `${col} sütununa göre sırala`,
    viewRowDetails: (n: number) => `${n}. satırın detaylarını görüntüle`,
    exportedRows: (n: number) => `${n} satır CSV olarak dışa aktarıldı`,
    copiedToClipboard: "Tablo panoya kopyalandı",
    pageAnnouncement: (page: number, total: number) => `Sayfa ${page} / ${total}`,
    captionVirtual: (rows: number, cols: number) =>
      `${rows} satır ve ${cols} sütun içeren SQL sonuç tablosu. Sanallaştırılmış. Ok tuşları, PageUp/PageDown, Home/End ile gezinin; Enter detayları açar.`,
    caption: (rows: number, cols: number) =>
      `${rows} satır ve ${cols} sütun içeren SQL sonuç tablosu. Satırlar arasında ok tuşlarıyla gezinin. Enter satır detaylarını açar.`,
  },

  sqlDrawer: {
    rowDetails: (n: number | "") => `Satır ${n} detayları`,
    viewingRow: (n: number, total: number) =>
      `${total} satırdan ${n}. satır görüntüleniyor. Kapatmak için Escape tuşuna basın.`,
    noRowSelected: "Satır seçilmedi.",
    copyRowJson: "Satırı JSON olarak kopyala",
    copyValueOf: (col: string) => `${col} değerini kopyala`,
  },

  sqlStats: {
    title: "Özet istatistikler",
    rowsCols: (rows: string, cols: number) => `${rows} satır · ${cols} sütun`,
    column: "Sütun",
    type: "Tür",
    nulls: "Boş",
    unique: "Benzersiz",
    min: "Min",
    max: "Maks",
    avg: "Ort",
    sum: "Toplam",
    types: {
      numeric: "sayısal",
      text: "metin",
      mixed: "karışık",
      empty: "boş",
    } as Record<string, string>,
  },

  sqlChart: {
    title: "Grafik",
    chartType: "Grafik türü",
    types: { bar: "çubuk", line: "çizgi", pie: "pasta" } as Record<string, string>,
    label: "Etiket",
    value: "Değer",
    xAxis: "X ekseni sütunu",
    yAxis: "Y ekseni sütunu",
    noNumericColumns: "Sayısal sütun yok",
    noNumericToPlot: "Çizilecek sayısal sütun yok",
    selectAxes: "Grafik için eksenleri seçin",
  },

  settingsDialog: {
    title: "Ayarlar",
    description: "ASM AI deneyiminizi özelleştirin.",
    theme: "Tema",
    themeDark: "Koyu (varsayılan)",
    themeLight: "Açık",
    themeSystem: "Sistem",
    language: "Dil",
    temperature: "Yaratıcılık düzeyi",
    displayName: "Görünen ad",
    logOut: "Çıkış yap",
  },

  login: {
    tagline: "Sağlık Zekâsı Platformu",
    email: "E-posta",
    password: "Şifre",
    passwordPlaceholder: "Şifrenizi girin",
    signIn: "Giriş yap",
    protectedBy: "MedAgent kurumsal güvenliği ile korunmaktadır.",
  },

  splash: {
    loading: "MedAgent yükleniyor",
  },

  errors: {
    notFoundTitle: "Sayfa bulunamadı",
    notFoundDescription: "Aradığınız sayfa mevcut değil veya taşınmış olabilir.",
    goHome: "Ana sayfaya dön",
    errorTitle: "Bu sayfa yüklenemedi",
    errorDescription:
      "Bizim tarafımızda bir sorun oluştu. Sayfayı yenileyebilir veya ana sayfaya dönebilirsiniz.",
    tryAgain: "Tekrar dene",
    backendUnreachable:
      "Sunucuya ulaşılamıyor. API sunucusunun çalıştığından emin olun (uvicorn app.main:app).",
  },
} as const;
