# Yaver e2e (Playwright)

Uçtan uca testler, ana stack'ten tamamen ayrı bir docker compose projesinde (`yaver-e2e`) koşar:
web **8090**, api **8001**, db **5433**, kendi volume'leri, test parolası `e2e-test-password`.
Ana stack (`yaver`, 8080/8000/5432) ve gerçek veritabanı hiç kullanılmaz.

```bash
# 1. izole stack: build, başlat, migration, /api/health/ready bekle
./e2e/stack.sh up            # Windows: .\e2e\stack.ps1 up

# 2. testler
cd e2e
npm ci
npx playwright install chromium
npm test                     # LLM'siz testler (mock'lu hata yolları + seed'li veri)
npm run test:live            # @live: gerçek LLM (Groq önce; Claude e2e stack'te $0.30 ile sınırlı)
npm run typecheck

# 3. kapat
./e2e/stack.sh down          # sadece yaver-e2e projesi; volume kalır
./e2e/stack.sh reset         # volume'lerle birlikte sil (taze DB)
```

- Sadece `GROQ_API_KEY`, `ANTHROPIC_API_KEY`, `OPENROUTER_API_KEY` kök `.env`'den okunur (compose
  interpolation); geri kalan her şey `docker-compose.e2e.yml`'de sabit. Anahtar yoksa `@live`
  testleri hata verir, diğerleri çalışır.
- `@live` harcama sınırı iki katmanlı: e2e api'de `CLAUDE_MONTHLY_BUDGET_USD=0.30`,
  `DEEP_MONTHLY_BUDGET_USD=0` (bütçe dolunca yalnız Groq) ve `tests/live.spec.ts` e2e DB'sindeki
  `llm_usage` toplamı $0.28'i geçince testleri atlar, sonda > $0.30 ise suite'i düşürür.
- Seed verisi `helpers/seed.ts` ile doğrudan e2e DB'sine (`docker exec yaver-e2e-db-1 psql`) yazılır;
  başlıklar her koşuda benzersizdir, tekrar koşmak için reset gerekmez.
- `tools/shadow_scan.py`: modül / import adını gölgeleyen sınıf alanlarını bulan salt-okur AST
  taraması (`python -I e2e/tools/shadow_scan.py backend/app`).

`tests/chat-errors.spec.ts`'deki iki test (sonu gelmeyen ya da `done`/`error` olmadan kapanan
sohbet akışı) QA bulgusu Y3'ü yakalamıştı; düzeltmeden sonra yeşil. `tests/streams.spec.ts` Y1'i
(18 açık ofis akışında pano ve `/api/health/ready` hemen cevap verir) korur. Ayrıntı: `docs/QA_REPORT.md`.
