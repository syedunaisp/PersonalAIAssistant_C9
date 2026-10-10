/# AGENTS.md

Project: a free personal AI assistant. Next.js + Tailwind CSS frontend (`web/`), Python FastAPI backend (`api/`), Gemini API as the LLM, Zapier MCP as the action layer. Single user, localhost only in v1.

## Read first, every session
1. `Personal_AI_Assistant_Projects.md`: product, constraints, security, agent routing guide (section 14.1).
2. `PLAN.md`: milestones, tasks, status, assigned agents and skills.

If they disagree with a prompt, say so. Do not silently pick one.

## Hard rules
- **All UI code (everything under `web/`) is written by OpenFrontendSpecialist** — unless the user explicitly asks for direct work, which is then recorded in `PLAN.md` (one exception so far: the M3.4 approval-card actions, decision 9).
- **Never auto-run a real-world action.** Every write or destructive tool call needs user approval, enforced in code (spec sections 6 and 11).
- **Zapier calls cost money-equivalent.** Each successful call spends 2 of 100 free monthly tasks. Do not call Zapier tools unless PLAN.md marks that call as budgeted. Use mocked or recorded responses otherwise.
- **Stay at $0.** Do not add paid services, paid APIs or paid libraries without asking.
- **No secrets in code, logs or the frontend.** Secrets live in `.env` only; it is never committed.
- Ignore get-shit-done and any GSD skills or agents. They are not part of this setup.
- Never claim an action or test passed without a real result to show.

## Key decisions (full list in PLAN.md)
- One approval per call, enforced in code — no "approve all", approvals expire in 10 min.
- `LOCAL_API_TOKEN` is the HMAC integrity secret, not transport auth; browser traffic relies on Host allowlist + CORS + JSON-only bodies.
- `DEFAULT_CALENDAR_ID` comes from `.env` at runtime — the model cannot guess opaque Zapier IDs.
- UI exception (2026-10-10): approval-card actions built directly at the user's explicit request.

## Current stack facts (volatile — re-verify against PLAN.md §2, don't trust training data)
- Gemini: `gemini-3.8-flash` primary, `gemini-3.5-flash-lite` fallback (in `.env`; `gemini-2.5-flash` was retired for new users).
- Zapier tools are fixed per-action names (`gmail_*`, `google_calendar_*` — exact list in `tools.yaml`); management meta-tools are filtered from the model.
- `LOCAL_API_TOKEN` is the server-side HMAC integrity secret, not transport auth; browser traffic relies on Host allowlist + CORS + JSON-only bodies.
- Ports: API `127.0.0.1:8000`, web `localhost:3000`. Backend tests: `api\.venv\Scripts\python.exe -m pytest api\tests -q` (33 passing). Frontend: `npm run lint --prefix web`, `npm run build --prefix web`.

## How to work
- One milestone per session. Do only the milestone you were asked to do.
- Plan with OpenAgent. Build with OpenCoder. Use the subagent that matches the task (see spec 14.1): ContextScout before coding, ExternalScout or context7 for library docs, TestEngineer for tests, CodeReviewer for security review, BuildAgent after each milestone.
- You run on a rate-limited free model. Keep replies short, delegate only when it helps, and use the context-management skills if the session grows long.
- When a task finishes, mark it done in `PLAN.md` and note anything the next session must know.
- If you change a decision, update `PLAN.md` (and the spec if it is a project-level decision) in the same session.
- At the end of a session, stop and report: what was done, how it was checked, and what to try by hand.

## Commands
Run, test and build commands are recorded in `PLAN.md` once milestone M0 sets them up. Do not guess them.
