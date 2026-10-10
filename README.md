# Personal AI Assistant

A free, single-user AI assistant that acts in your apps. You type a request in plain language; a Gemini model answers directly or acts through Zapier MCP (Gmail, Google Calendar). **Anything with a real-world effect pauses for your approval first** — nothing consequential runs without you clicking Approve. Runs entirely on localhost at **$0/month**.

## Features

- **Streaming chat** — replies stream token-by-token into a Next.js + Tailwind UI (light/dark).
- **Approval gate** — every write/destructive tool call stops the turn and shows a card with the exact arguments, the app, and the task cost. Approve, edit the arguments, or reject.
- **Read tools run automatically** — calendar lookups and email searches execute immediately and feed back to the model.
- **Tool activity timeline** — every proposal, result, and approval is visible inline with pending/running/done/failed states.
- **Audit log + task budget** — every execution is logged (SQLite) with honest success/failure and task cost. Failed calls cost 0 tasks.
- **Fail-closed security** — unlisted tools default to write; HMAC-verified, single-use, expiring approvals; Host allowlist + CORS on browser traffic; secrets only in `.env`.

## How it works

```text
Browser (Next.js :3000) ──SSE──▶ FastAPI (:8000) ──▶ Gemini (tool choice)
                                        │                    │
                                        │◀── function call ─┘
                                        │
                          ┌─────────────┴──────────────┐
                          │ read → Zapier MCP → model  │  (auto, 2 tasks on success)
                          │ write → pending_action     │  (STOP, wait for you)
                          │   └─▶ Approve ▶ execute    │  (2 tasks on success)
                          └────────────────────────────┘
```

Reads cost 2 of your 100 free monthly Zapier tasks on success; writes cost 2 on success; failures and tool-listing cost 0.

## Installation

Prerequisites: Python 3.11+, Node.js 20.9+, and a Zapier MCP server (create one at mcp.zapier.com, connect Gmail/Calendar, enable only the actions you need — copy its token).

```powershell
# 1. Backend deps (Windows)
python -m venv api\.venv
api\.venv\Scripts\python.exe -m pip install -r api\requirements.txt -r api\requirements-dev.txt

# 2. Frontend deps
npm install --prefix web

# 3. Secrets — copy the template and fill in real values (never commit .env)
Copy-Item .env.example .env
```

`.env` keys: `GEMINI_API_KEY` (aistudio.google.com/apikey), `ZAPIER_MCP_TOKEN` (your Zapier MCP token), `LOCAL_API_TOKEN` (any random string — HMAC integrity secret; generate with `python -c "import secrets; print(secrets.token_urlsafe(32))"`), `GEMINI_MODEL` (default `gemini-3.8-flash`), `GEMINI_MODEL_FALLBACK` (default `gemini-3.5-flash-lite`), `DEFAULT_CALENDAR_ID` (your primary calendar — resolve via Zapier's `list_dynamic_enum_values` for any `google_calendar_*` tool + `calendarid`; needed because the model cannot guess opaque IDs).

## Quick start

```powershell
# Terminal 1 — API (binds 127.0.0.1:8000 only)
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000

# Terminal 2 — web UI
npm run dev --prefix web
```

Open http://localhost:3000 and check `/api/health` shows both services reachable. Try:

- *"What's on my calendar tomorrow?"* → read runs automatically (2 tasks on success).
- *"Draft an email to …"* → proposal pauses, approval card appears → **Approve** (streams the result), **Edit** (change arguments, then approve), or **Reject** (nothing runs, 0 tasks).

Notes: a draft never sends, so it's safe to test with. Sends, replies, and event creation are real the moment you approve. Failed calls cost 0 tasks, and success is never claimed without a real tool result.

## API reference

| Method & path | Purpose |
|---|---|
| `POST /api/chat` | Send `{message}`; returns an SSE stream |
| `POST /api/approvals/{id}` | Body `{action: "approve" \| "reject" \| "edit", args?}` — approve streams SSE, reject/edit return JSON |
| `GET /api/health` | Gemini + Zapier connectivity (type-only errors, never secrets) |
| `GET /api/usage`, `GET /api/audit` | Counters and audit log (M4) |

SSE events: `token`, `tool_proposed`, `approval_required`, `tool_result` (`ok: true/false`), `error`, `done`.

## Testing

```powershell
api\.venv\Scripts\python.exe -m pytest api\tests -q   # backend (mocked Gemini + Zapier, zero real calls)
npm run lint --prefix web                              # frontend lint
npm run build --prefix web                             # frontend build
```

Backend tests use `FakeMcpClient` + scripted Gemini clients — no network, no task spend. Real end-to-end runs are budgeted explicitly in `PLAN.md` (§5).

## Project structure

```text
api/            FastAPI backend (chat, orchestrator, policy, approvals, store, health)
web/            Next.js 16 + Tailwind v4 frontend (chat page, approval card, activity timeline)
prompts/        core.md — system prompt (editable without code changes)
tools.yaml      Tool name → read/write/destructive (unlisted = write)
.env.example    Secret template (copy to .env; .env is gitignored)
Personal_AI_Assistant_Projects.md   Product spec (source of truth)
PLAN.md         Milestones, decisions, session log
AGENTS.md       Working rules for AI agents
```

## Contributing

One milestone per session; update `PLAN.md` when a task finishes and record decision changes there. Read `AGENTS.md` first. Keep replies short, never auto-run real-world actions, and never claim a result without running it.

## License

Not yet chosen — pick one before publishing (MIT is the usual default for a project like this).
