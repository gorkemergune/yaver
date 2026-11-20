# Yaver

> Self-hosted, chat & voice-first personal AI assistant for students. Tell it what changed — it updates your schedule, attendance, exams, workouts and study notes for you.

**Status:** Phase 0 done, Phase 1 (proactive assistant) under way. Single user, self-hosted.

## Why

Planner apps make you click buttons. Yaver doesn't. You just say:

- *"Bugün linear iptal, yarın da quiz var."*
- *"28–29 Kasım hackathon'una başvurdum, kabul gelene kadar her gün sor."*
- *"Bu haftanın notlarından devreler için çalışma kağıdı hazırla."*

…and it writes the changes itself, shows you a diff, and lets you undo. Then it greets you every morning with your day:

> Günaydın Görkem. Bugün cumartesi ama 11–13 ek elektrik dersin, 13–15 linear dersin var.

## Your Yaver team

Yaver isn't one assistant — it's a small team. You always talk to the coordinator; it splits your message and hands each part to the right specialist. You name them.

| Role | Example name | Handles |
|---|---|---|
| Coordinator | Yaver | Talks to you, splits & delegates, merges answers, undo |
| Academic | Friday | Classes, attendance, exams, course notes, study sheets |
| Agenda | Jarvis | Meetings, work, events, applications, follow-ups |
| Discipline | Karen | Workouts, habits, screen time, app limits |

> *"Bugün linear iptal, yarın 14'te toplantı var, akşam spora gidemem."*
> → Friday cancels the class, Jarvis adds the meeting, Karen moves your workout — one message, one undo.

Add your own specialists in `config/agents.yaml`.

## Features

| Area | Status | What it does |
|---|---|---|
| Chat-first editing | ✅ | Say what changed; the team writes it, shows a change card, one "Geri al" undoes the whole message |
| Schedule | ✅ | Weekly classes, labs, workouts; one-off events; cancellations, moves, holidays; Today / Week views with a live "şu an" line |
| Attendance | ✅ | Absences in class hours, per class block ("19 Kasım 09:00-11:00: 2 saat"), limits in hours, absences from before Yaver as a baseline |
| Dates in plain Turkish | ✅ | "geçen salı", "haftaya cuma 14'te", "27 Kasım Cuma", "5 12 17 19 kasım" - resolved in code, never guessed by the model |
| First-run setup | ✅ | A setup chat: term, holidays, schedule pasted or photographed, limits, sport, fixed facts |
| Images | ✅ | Send a timetable photo or an exam poster: Claude reads it, you confirm the table, it's written |
| Voice | ✅ web | Hold the mic and talk (Groq Whisper); iPhone Siri Shortcut later |
| Proactive | ✅ | Morning briefing, evening check-in with quick replies, follow-up questions, Sunday weekly plan draft; in the chat and as Web Push notifications (status page → Bildirimler; iPhone: add to home screen first) |
| Backups | ✅ | Daily automatic `pg_dump`, scripts to take and restore backups |
| Budget guard | ✅ | LLM spend per month, Sonnet -> Haiku at 80%, Claude off at 100% |
| Course materials | ✅ started | Send a syllabus PDF: Sonnet reads the weekly topics, you confirm the table; passages are embedded locally (pgvector) and Friday answers from them with file + page |
| Study sheets | Phase 3 | Notes -> study sheets with sources |
| Desktop companion | Phase 4 | Floating assistant on Windows / macOS, screen time and app limits |

Daily use, example sentences and common problems (Turkish): [docs/tr/KULLANIM.md](docs/tr/KULLANIM.md).

## Architecture

```
iPhone / browser (PWA) ──► web (React, nginx) ──► api (FastAPI) ──► Postgres 16 + pgvector
                                                    │  ├─ coordinator + yavers (tool calling, one change set per message)
                                                    │  ├─ scheduler (APScheduler, jobs in Postgres): briefing, check-in, weekly plan
                                                    │  └─ daily pg_dump backup
                                                    └─► LLM router: Groq ⇄ Claude Haiku → Claude Sonnet (smart) / Ollama
                                                        images: Claude only · voice: Groq Whisper
```

- **Local-first:** runs on your own machine with `docker compose up`.
- **Single-user per instance:** each person runs their own Yaver with their own data and keys.
- **BYOK:** bring your own API keys. A free Groq key is enough to start.
- **Remote access:** reach it from your phone through [Tailscale](https://tailscale.com) (free, HTTPS included).

## Quick start

```bash
git clone https://github.com/gorkemergune/yaver.git
cd yaver
cp .env.example .env      # add at least GROQ_API_KEY (ANTHROPIC_API_KEY for images / smart tier)
docker compose up -d --build
docker compose exec api alembic upgrade head
# open http://localhost:8080 - the first chat walks you through the setup
```

Check a running stack: `.\scripts\smoke.ps1` (health, API, a real chat message and its undo;
`-NoChat` skips the model call). Development: `docker compose exec api pytest` (backend,
~14 s), `cd web && npm run check` (frontend); live model tests are opt-in: `pytest -m live`.

Try the scheduled messages without waiting: `curl -X POST "localhost:8000/api/jobs/briefing/run?force=true"`
(also `checkin`, `followups`, `weekly_plan`). Times: `BRIEFING_TIME`, `CHECKIN_TIME`,
`FOLLOWUP_TIME`, `WEEKLY_PLAN_TIME` in `.env`.

## Login

With `APP_PASSWORD` empty, there is no login: fine while Yaver is only reachable from your
own computer. **Set a password before you open it to your phone** (Tailscale): every `/api`
route except health then needs a session. The browser gets an httpOnly cookie (login screen),
the desktop app a token (⚙ → Parola). Sessions live in Postgres and end after
`SESSION_DAYS` (30) without use; "Oturumu kapat" on the status page ends one. Five wrong
passwords in ten minutes lock the login for a while.

## Backups

> ⚠️ **`docker compose down -v` deletes your data.** `-v` removes the `pgdata` volume, i.e.
> the database with your schedule and history. Use plain `docker compose down` (or `stop`).

- The api takes a backup on startup when the newest one is older than 24 h:
  `backups/yaver-YYYYMMDD-HHMMSS.sql.gz` (UTC), the newest 14 are kept. Folder: `BACKUP_DIR` in `.env`.
- By hand: `.\scripts\backup.ps1` (Windows) or `scripts/backup.sh`.
- Restore into a scratch database first: `.\scripts\backup.ps1 restore backups\yaver-....sql.gz`
  (creates `yaver_restore`). Over the live database: `docker compose stop api`, then
  `.\scripts\backup.ps1 restore <file> yaver -Yes`, then `docker compose start api`.

Details (Turkish): [docs/tr/yedekleme.md](docs/tr/yedekleme.md).

## LLM providers

| Tier | Default | Used for |
|---|---|---|
| `fast` | Groq (free tier) | Everyday chat, edits, briefings |
| `fallback` | Claude Haiku 5.5 | When `fast` fails a tool call or hits a rate limit |
| `smart` | Claude Sonnet 5.5 | Weekly planning, study sheets |
| `local` | Ollama | Fully offline, optional |

All providers are configured in `config/providers.yaml`. Any OpenAI-compatible endpoint works.

### Recommended if you have your own Claude key

Groq's free tier allows about 8k tokens per minute per model, and one Yaver message with
delegation uses 5-10k. With the default layout many calls end up on Haiku anyway, after a
wait. With an Anthropic key, swap the two tiers in your `config/providers.yaml`:

```yaml
tiers:
  fast:                       # Claude Haiku answers first (prompt-cached)
    provider: anthropic
    model: claude-haiku-5-5
    max_prompt_tokens: 90000
    options:
      thinking: {type: disabled}
  fallback:                   # Groq takes over on errors / rate limits
    provider: groq
    model: openai/gpt-oss-120b
  # smart, local: unchanged
budget:
  downgrade:
    smart: fast               # at 80% of CLAUDE_MONTHLY_BUDGET_USD: Sonnet -> Haiku
  allowed_at_limit: [fallback, local]   # at 100%: Groq only
```

Failover, rate-limit waits, per-yaver models (`model: {groq: ...}` in `agents.yaml`) and the
budget guard follow the provider, not the tier name, so nothing else changes. Details and
measured cost (Turkish): [docs/tr/llm-saglayicilari.md](docs/tr/llm-saglayicilari.md).

## Privacy

Your schedule, notes and chat history stay in your own Postgres. Only the text needed for a request is sent to the LLM provider you configure. Choose providers whose data policy you accept, or run fully local with Ollama.

## License

MIT
