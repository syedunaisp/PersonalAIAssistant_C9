# PLAN.md

Status: **in progress** — M0–M3 done and verified live (real Gmail draft created after Approve, 2026-10-10); M4 next. Product source of truth: `Personal_AI_Assistant_Projects.md`.

## Milestones

| ID | Milestone | Status |
|---|---|---|
| M0 | Keys, Zapier server, `.env`, `/api/health` green | done |
| M1 | Streaming chat (UI + `/api/chat`) | done |
| M2 | Zapier read path | code done; one live read pending (2 tasks) |
| M3 | Policy + approval card (write pauses, runs only after Approve) | done (live draft, user-confirmed) |
| M4 | Usage, audit, quota guards (blocks at 90%) | not started |
| M5 | `web_research` with sources | not started |
| M6 | Memory and profile | not started |
| M7 | Hardening (all §16 tests pass) | not started |

## Decisions (all resolved 2026-10-10)

- Apps: Gmail + Calendar. Models: `gemini-3.8-flash` / `gemini-3.5-flash-lite` (2.5 was retired mid-build).
- Fixed Zapier list (`gmail_*`, `google_calendar_*` in `tools.yaml`); unlisted = write; meta-tools filtered from the model.
- Local-only v1 (API 127.0.0.1:8000, web localhost:3000). Python FastAPI. No "approve all" — one approval per call, enforced in code.
- `LOCAL_API_TOKEN` is HMAC-integrity-only (ephemeral fallback); browser traffic = Host allowlist + CORS + JSON-only.
- `DEFAULT_CALENDAR_ID` in `.env`, injected into the prompt at runtime (model can't guess opaque IDs).
- Approval-card actions built directly by OpenAgent at user request (exception to the UI rule).
- Tests mock everything (zero real calls); only budgeted live calls spend tasks (used so far: 1 write = 2 tasks).

## Commands (repo root)

```text
api\.venv\Scripts\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000
api\.venv\Scripts\python.exe -m pytest api\tests -q   # 33 passing
npm run dev --prefix web                              # http://localhost:3000
npm run build --prefix web
npm run lint --prefix web
```

## Next

1. Create GitHub repo + first commit.
2. M3.9 milestone check, then M4 (auto-read audit + read-budget carry folded in from M3.7).
3. Open verifications: M2.6 live calendar read + calendar quick-add retry (2 tasks each on success).

Full task history: `git log`. Archived detail from the planning-era PLAN (task tables, risks, proposals): available in git history after the first commit.
