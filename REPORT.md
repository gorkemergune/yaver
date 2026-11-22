# Rapor — ek kuyruk (22 Kasım 2026)

(Çalışırken doldurulan taslak; sonda baştan yazılacak.) Önceki rapor: `git show bd40f80:REPORT.md`.

## 1. Venture gerçek repo kontrolü

- karar: `.env`'e dokunmadım (okuyamıyorum da). Kontrolü dev'de, `.env`'deki GITHUB_TOKEN ile, salt okunur yaptım.
- **Senin cümlen (depo adı yok):** Venture `github_week_summary`'yi çağırdı, cevap:
  > Venture: week3 özetini çekemedi, çünkü GitHub deposu ayarı hatalı. `GITHUB_STARTUP_REPO` değeri "gorkemergune/<startup>" olarak girilmiş, oysa "owner/name" biçiminde (ör. acme/startup) olmalı. …
- **Önceki cümlen (`github/gorkemergune/startup` ile):**
  > Venture: … "gorkemergune/startup" deposuna GitHub erişemiyor; depo adı yanlış olabilir ya da GITHUB_TOKEN bu depoya yetkili değil. …
- **Token'ın gördüğü depolar:** 55 depo. Hiçbirinde üye bazlı weekN klasörü yok.
  - Nexa ile ilgili olanlar: `nexa-lab-ai/nexa-bench` ve `nexa-tr/website`; ikisinde de week klasörü yok.
  - weekN klasörü olanlar yalnız ders depoları (`cpp-foundations/doc/week01-12`, `c-foundations/lecture/week01-12`).
  - Sonuç: NEXA startup deposu ya başka bir adda, ya da token'ın kapsamı dışında (ör. bir organizasyon deposu, fine-grained token'a eklenmemiş).
