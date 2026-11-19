# Yaver

> Self-hosted, chat & voice-first personal AI assistant for students. Tell it what changed — it updates your schedule, attendance, exams, workouts and study notes for you.

**Status:** 🚧 Early development (Phase 0)

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

## Features (planned)

| Area | What it does |
|---|---|
| Schedule | Weekly classes, labs, workouts; one-off events; cancellations & make-up classes |
| Attendance | Counts absences per course, warns before you hit the limit |
| Exams & deadlines | Exam calendar, countdowns, quiz reminders |
| Follow-ups | "Remind me every day until X happens" (applications, emails, replies) |
| Study | Upload syllabus + lecture notes → weekly summaries and study sheets (RAG) |
| Proactive | Morning / evening briefings, Sunday weekly planning session |
| Voice | Speak instead of type (Whisper), iPhone Siri Shortcut support |
| Desktop companion | Floating assistant icon on Windows / macOS, screen-time tracking & app limits |
| Budget guard | Tracks LLM spend per month, auto-downgrades models when near the limit |

## Architecture

```
iPhone (PWA + Siri Shortcut) ─┐
Browser (PWA)                 ├─► Core (Docker): FastAPI + Postgres/pgvector + Scheduler + LLM agent
Desktop companion (Tauri)    ─┘        │
                                       └─► LLM router: Groq (free) → Claude Haiku → Claude Sonnet / Ollama
```

- **Local-first:** runs on your own machine with `docker compose up`.
- **Single-user per instance:** each person runs their own Yaver with their own data and keys.
- **BYOK:** bring your own API keys. A free Groq key is enough to start.
- **Remote access:** reach it from your phone through [Tailscale](https://tailscale.com) (free, HTTPS included).

## Quick start (once Phase 0 lands)

```bash
git clone https://github.com/gorkemergune/yaver.git
cd yaver
cp .env.example .env      # add at least GROQ_API_KEY
docker compose up -d
# open http://localhost:8080
```

## LLM providers

| Tier | Default | Used for |
|---|---|---|
| `fast` | Groq (free tier) | Everyday chat, edits, briefings |
| `fallback` | Claude Haiku 5.5 | When `fast` fails a tool call or hits a rate limit |
| `smart` | Claude Sonnet 5.5 | Weekly planning, study sheets |
| `local` | Ollama | Fully offline, optional |

All providers are configured in `config/providers.yaml`. Any OpenAI-compatible endpoint works.

## Privacy

Your schedule, notes and chat history stay in your own Postgres. Only the text needed for a request is sent to the LLM provider you configure. Choose providers whose data policy you accept, or run fully local with Ollama.

## License

MIT
