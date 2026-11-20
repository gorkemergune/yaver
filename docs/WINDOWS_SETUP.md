# Windows'ta başlangıç

1. **Docker Desktop** kur → Settings → General: "Use WSL 2 based engine" açık, "Start Docker Desktop when you sign in" açık.
2. **Git** + **Node 20+** + **Python 3.12** (sadece editör/lint için; çalıştırma Docker'da).
3. GitHub'da `gorkemergune/yaver` repo'sunu oluştur (aşağıdaki bilgilerle), klonla, bu dosyaları içine koy, ilk commit.
4. `copy .env.example .env` → `GROQ_API_KEY` ve `ANTHROPIC_API_KEY` doldur.
5. Claude Code'u repo klasöründe aç, ilk mesaj:

   > CLAUDE.md, ROADMAP.md ve TASKS.md'yi oku. TASKS.md'deki 0.1 İskelet bölümünden başla, her maddeyi ayrı commit olarak yap ve bitince işaretle.

6. Günlük kullanım (prod modu), **Tailscale** ile HTTPS, iPhone'da ana ekran uygulaması, bildirimler ve takvim aboneliği: [tr/KURULUM_WINDOWS.md](tr/KURULUM_WINDOWS.md).

## Performans notu
Docker'da dosya izleme (hot reload) Windows klasörlerinde yavaş olabilir. Yavaşlık olursa repo'yu WSL içine (`\\wsl$\Ubuntu\home\...`) klonla.

## GitHub repo bilgileri
- **Ad:** `yaver`
- **Açıklama:** Self-hosted, chat & voice-first personal AI assistant for students — manages your schedule, attendance, exams, workouts and study notes. Docker, local-first, BYOK (Groq / Claude / Ollama).
- **Topics:** `ai-assistant`, `personal-assistant`, `llm`, `tool-calling`, `fastapi`, `react`, `pwa`, `self-hosted`, `docker`, `student`, `productivity`, `groq`, `claude`
- **License:** MIT
- **Visibility:** Faz 0 boyunca private, Faz 5'te public.
