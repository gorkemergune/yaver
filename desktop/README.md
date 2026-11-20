# Yaver desktop companion

A small Tauri v2 app for Windows (Phase 4). It shows a round Yaver logo that stays on top of other windows. Click the logo to open a mini chat with your Yaver team. The app also keeps track of screen time on this PC.

- **Logo:** a transparent, always-on-top, draggable round window. Press and move to drag it; a click opens or closes the chat. Its position is remembered.
- **Mini chat:** talks to the existing backend through `POST /api/chat`. Replies get an agent label and color from `/api/team`, and replies with changes get a **Geri al** link (`POST /api/changes/{id}/undo`).
- **Screen time (Windows):** samples the foreground app every 5 s into a **local** SQLite file. The panel's clock tab shows today's total, per-app time and limits. A daily summary per app (no window titles, no sessions) goes to the backend (`POST /api/screen-time`) every 10 minutes and on exit; while the backend is unreachable the days wait in the SQLite file and go out with the next successful sync. Karen answers "bugün ne kadar oynadım?" from it, and the evening check-in has a screen-time line.
- **App limits:** set in `config.json`. You get a warning at 80 % and at 100 % of the daily limit, shown as a balloon next to the logo and as a Windows notification. **Apps are never closed** (that comes later, together with the "bargaining" flow).
- **Tray icon:** opens the chat, brings the logo back, turns *Start at Windows login* on or off, and quits the app. The windows have no taskbar entry, so the tray is the only way to quit.

## Requirements

- Windows 10/11 with WebView2 (built into Windows 11)
- Node.js 20+ and npm
- Rust (stable, 1.82+) with the MSVC toolchain: `rustup default stable-msvc`
- Visual Studio Build Tools with "Desktop development with C++" (Tauri's [Windows prerequisites](https://v2.tauri.app/start/prerequisites/))
- The Yaver backend running (`docker compose up -d` in the repo root). Without it the chat shows "Sunucuya ulaşılamadı", but screen time keeps working.

## Run (development)

```bash
cd desktop
npm install
npm run tauri dev
```

`tauri dev` starts Vite on `http://localhost:1420` and opens the app with hot reload. Rust changes trigger a rebuild. The logo appears in the bottom-right corner of the main screen.

## Build an installer

```bash
cd desktop
npm run tauri build
```

This produces an NSIS installer in `src-tauri/target/release/bundle/nsis/Yaver_0.1.0_x64-setup.exe`. The installed app shows up in Windows notifications as "Yaver". Builds started with `tauri dev` show up as "Windows PowerShell" instead.

## Configuration

Settings are stored in `%APPDATA%\com.yaver.desktop\config.json`. The file is created on first run. You can open it from the panel: clock tab → *Ayar dosyasını göster*.

```json
{
  "api_url": "http://localhost:8080",
  "track_screen_time": true,
  "idle_minutes": 5,
  "app_limits": [
    { "name": "VALORANT", "processes": ["VALORANT-Win64-Shipping.exe", "VALORANT.exe"], "daily_minutes": 90 }
  ]
}
```

(See also [`config.example.json`](config.example.json).)

| Field | Default | Meaning |
|---|---|---|
| `api_url` | `http://localhost:8080` | Yaver web address (nginx proxies `/api`). Can also be changed in the panel: ⚙ → *Sunucu adresi*. The `YAVER_API_URL` environment variable overrides it. |
| `track_screen_time` | `true` | Sample the foreground app. |
| `idle_minutes` | `5` | With no keyboard or mouse input for this long, time is not counted. Apps that have a limit count anyway, because controller input is invisible to Windows. |
| `app_limits` | `[]` | `name` is shown in warnings. `processes` are exe names (case-insensitive, `.exe` optional). `daily_minutes` is the limit per local calendar day. |
| `bubble_position` | – | Written by the app when you drag the logo. |

Edits to the file are picked up within a minute, with no restart. A broken (invalid JSON) file is never overwritten. The app keeps using the last good settings and shows the error in the clock tab.

To find an app's exe name, open Task Manager → *Details*, or hover over the app's row in the clock tab.

## Where data lives

| What | Where |
|---|---|
| Settings | `%APPDATA%\com.yaver.desktop\config.json` |
| Screen time | `%LOCALAPPDATA%\com.yaver.desktop\screen_time.sqlite3` (`screen_sessions`, `limit_alerts`, `sync_state`) |
| Logs | `%LOCALAPPDATA%\com.yaver.desktop\logs\Yaver.log` |
| Autostart | `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` → `Yaver` (only when turned on) |

To look at the screen-time data:

```bash
sqlite3 "%LOCALAPPDATA%\com.yaver.desktop\screen_time.sqlite3" \
  "SELECT app_name, sum(ended_at-started_at)/60 AS dk FROM screen_sessions WHERE idle=0 GROUP BY lower(exe) ORDER BY dk DESC"
```

## Start at Windows login

The option is off by default. Turn it on from the tray menu (*Oturum açılışında başlat*) or from the panel (⚙ → *Windows oturumu açılınca başlat*). It registers the exe that is currently running. Turn it on from the **installed** app: in dev mode it would point at `target\debug\yaver-desktop.exe`.

## Checks

```bash
cd desktop
npm run check                         # tsc + eslint + vitest
cd src-tauri
cargo fmt --check && cargo clippy --all-targets -- -D warnings && cargo test
```

## Layout

```
desktop/
  index.html, chat.html, notice.html   one page per window: logo, chat panel, warning balloon
  src/                                 vanilla TS (no framework: three tiny windows)
    bubble.ts, drag.ts                 click vs. drag on the logo
    chat.ts, chat/model.ts             chat panel + pure helpers (tested)
    screen/                            screen-time view + pure helpers (tested)
    notice.ts                          warning balloon
    i18n/tr.ts                         every user-facing string
  src-tauri/src/
    lib.rs                             app setup, state, commands
    api.rs                             HTTP to the backend (from Rust: the API has no CORS for the webview)
    windows.rs, layout.rs              window placement (pure math, tested)
    tray.rs, autostart.rs, notice.rs
    config.rs                          config.json, read-modify-write
    screentime/                        foreground.rs (Win32), store.rs (SQLite), limits.rs, mod.rs (sampler)
```
