# Ofis prototipi (referans)

- `Main.dc.html` — onaylanan tasarım kanvası dosyası. Normal bir web sayfası değil (`<x-dc>`, `{{hole}}`, `<sc-for>` şablon sözdizimi kullanır); doğrudan çalıştırılmaz. **Kaynak olarak oku ve React'e taşı.**
  - `<script type="text/x-dc">` bloğu: çalışan verisi (META), masa düzeni (DESK_X, ROW_A/ROW_B), engeller (OBST), ızgara + A* yol bulma, oturma/yaklaşma noktaları (SPOTS), z-sırası kuralı, hareket döngüsü.
  - Gömülü `<svg>` blokları: statik sahne katmanları ve z-index'leri (1, 420, 450, 500, 550, 560, 640). Figürler: 400 (arka), 520 (toplantı), 600 (orta), 700 (ön); gece katmanı 900, liste 950.
- `../../scripts/office_scene.py` — statik katmanları üreten script (izometrik çizim yardımcıları: `box`, `flat`, `wallL/R`, `monitor`, `office_chair`, tabelalar). `python scripts/office_scene.py` katman başına SVG'yi ve `layout.json`'u `web/src/office/scene/` altına yazar (pencere gökyüzü `var(--office-sky)`); çıktı prototipteki katmanlarla birebir aynıdır. Engel listesi (OBST) ve masa koordinatları bu scriptle aynı kalmalı.

Değişmemesi gereken kararlar: masalar arkadan öne çizilir (arka sıra: klavye/kahve önce, monitör sonra; ön sıra: monitör önce); ön sıra sandalye sırtlıkları figürlerin üstünde ayrı katmanda; yürüyen figürler hiçbir engel karesine girmez (O2 testinde tüm nokta çiftleri için doğrula).
