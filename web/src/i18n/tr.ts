// User-facing strings (Turkish). Code stays in English; every UI text lives here.
export const tr = {
  appName: "Yaver",
  connection: {
    checking: "Bağlanıyor…",
    online: "Bağlı",
    offline: "Sunucuya ulaşılamıyor",
  },
  chat: {
    emptyTitle: "Bugün ne değişti?",
    emptyHint: "Ders iptali, yeni sınav, toplantı, spor… Söylemen yeterli; gerisini ekip halleder.",
    examples: [
      "Bugün linear iptal",
      "Yarın 14'te toplantı var",
      "Bugün EE211'e gitmedim",
      "Yarın ne var?",
    ],
    inputPlaceholder: "Yaver'e yaz…",
    send: "Gönder",
    agentNotConnected: "Ajan henüz bağlı değil — mesajlar şimdilik sadece burada görünüyor.",
  },
} as const;
