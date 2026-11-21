# LLM sağlayıcıları ve tier düzeni

Yaver her LLM çağrısını bir **tier** üzerinden yapar. Hangi tier'ın hangi sağlayıcı ve
modele gittiği `config/providers.yaml`'da yazar; kodda model adı yoktur.

| Tier | Varsayılan | Ne için |
|---|---|---|
| `fast` | Groq `gpt-oss-120b` (ücretsiz katman) | Günlük sohbet, ekleme/iptal, sorular |
| `fallback` | Claude Haiku 5.5 | `fast` hata verirse, rate limit'e takılırsa ya da 2 kez geçersiz araç çağrısı yaparsa |
| `smart` | Claude Sonnet 5.5 | Haftalık plan, çalışma kâğıdı, uzun yapıştırılmış ders programı |
| `deep` | Claude Opus 5.5 | Yalnızca işaretli haftalık işler: haftalık reklam raporu (Metrics), haftalık startup değerlendirmesi (Venture) |
| `local` | Ollama (opsiyonel) | Tamamen yerel çalışma |

`deep` başka hiçbir şeye açılmaz: `routing.explicit_only: [deep]`, yani yalnızca
`routing.purposes`'ta `deep`'e bağlanan amaçlar kullanabilir, kod başka bir çağrıyı reddeder
(varsayılan, failover ya da bütçe adımı `deep`'e çıkamaz). Kendi aylık sınırı var:
`DEEP_MONTHLY_BUDGET_USD` (varsayılan 2). Dolunca o işler `smart`'la (Sonnet) yapılır.
Opus harcaması `CLAUDE_MONTHLY_BUDGET_USD`'nin içinde de sayılır: Claude toplamı %80'i geçince
haftalık işler Haiku'ya iner, %100'de Claude hiç kullanılmaz. Opus 5.5'te thinking
kapatılamaz; derinliği `effort` belirler (`high`). Durum ekranında ayrı bir çubukla görünür.

`providers.example.yaml` varsayılan olarak Groq'la başlar: yalnızca ücretsiz bir Groq
key'iyle Yaver çalışır.

## Kendi Claude key'in varsa önerilen ayar

Groq'un ücretsiz katmanı model başına dakikada yaklaşık 8.000 token veriyor. Delegasyonlu
tek bir Yaver mesajı 5-10 bin token harcıyor. Bu yüzden varsayılan düzende çağrıların büyük
kısmı zaten Haiku'ya düşüyor, üstüne bir de bekleme ekleniyor. Anthropic key'in varsa
`config/providers.yaml`'da `fast` ile `fallback`'in yerini değiştir:

```yaml
tiers:
  fast:                       # önce Claude Haiku cevaplar (prompt cache açık)
    provider: anthropic
    model: claude-haiku-5-5
    max_prompt_tokens: 90000  # Haiku 100K token üstünü 5 kat fiyatlar; router geçmişi kırpar
    options:
      thinking: {type: disabled}
  fallback:                   # hata / rate limit olursa Groq devralır
    provider: groq
    model: openai/gpt-oss-120b
  # smart ve local aynı kalır
budget:
  downgrade:
    smart: fast               # CLAUDE_MONTHLY_BUDGET_USD'nin %80'i: Sonnet -> Haiku
  allowed_at_limit: [fallback, local]   # %100: yalnız Groq
```

Başka bir şeyi değiştirmen gerekmez. Aşağıdakiler tier adına değil sağlayıcıya bakar:

- **Failover:** `routing.failover_chain: [fast, fallback]` aynen kalır; artık Haiku → Groq.
- **Rate limit beklemesi:** Groq için `GROQ_MAX_RETRY_WAIT_SEC` (8 sn) Groq hangi tier'da
  olursa olsun geçerli. Claude için varsayılan 3 sn.
- **Yaver başına model:** `agents.yaml`'da `model: {groq: openai/gpt-oss-20b}`. Groq fallback
  olduğunda da yaverler küçük modeli kullanır; Haiku'ya Groq model adı hiç gitmez.
- **Bütçe:** %100'de Claude kullanan tier'lar zincirden çıkar. Bu düzende geriye Groq kalır.
- **Prompt cache:** Anthropic isteklerinde her zaman açık. System prompt + araç şemaları
  cache'lenir (Haiku 5.5'te en az 512 token; yaver prompt'ları 1,4-2,7 bin token).

### Ölçüm: aynı 5 canlı senaryo (`pytest -m live -k scenarios`)

| Düzen | Failover | 429 | Toplam süre | Maliyet |
|---|---|---|---|---|
| fast = Groq (varsayılan, 8 sn bekleme) | %56 (27 çağrının 15'i Haiku'ya) | 22 | 70 sn | $0,0089 |
| fast = Haiku (önerilen), 1. tur | %0 (20 çağrı) | 0 | 23,1 sn | $0,0047 |
| fast = Haiku (önerilen), 2. tur | %0 (21 çağrı) | 0 | 25,1 sn | $0,0034 |

Haiku turlarında girdi token'larının %76'sı (1. tur) ve %92'si (2. tur, cache hâlâ sıcakken)
cache'ten okundu; cache okuma fiyatı normal girdinin onda biri. Çağrı başına medyan gecikme
~1 sn; en uzun mesaj (üç yavere bölünen karışık mesaj) 9-11 sn.

Kabaca: mesaj başına $0,0007-0,0009; günde 30 mesaj ≈ ayda $0,6-0,9. Bu bir tahmin;
gerçek harcamayı `/api/usage/month` ve arayüzdeki harcama kartı gösterir.
