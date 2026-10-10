import type {
  ApprovalDecisionAction,
  ApprovalRequest,
  DoneMeta,
  ToolCallBase,
  ToolClassification,
  ToolResultData,
} from "./toolActivity";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

export type StreamErrorKind = "offline" | "http" | "server" | "client";

export type StreamError = { kind: StreamErrorKind; message: string };

export type StreamHandlers = {
  onToken: (text: string) => void;
  onToolProposed: (proposal: ToolCallBase) => void;
  onToolResult: (result: ToolResultData) => void;
  onApprovalRequired: (request: ApprovalRequest) => void;
  onDone: (meta: DoneMeta) => void;
  onError: (error: StreamError) => void;
};

/** Result of a non-streaming decision; approve streams through handlers instead. */
export type ApprovalDecisionOutcome =
  | { kind: "streamed" }
  | { kind: "rejected" }
  | { kind: "pending"; args: Record<string, unknown> };

type SseFrame = { event: string; data: string };

const HTTP_ERROR_MESSAGES: Record<number, string> = {
  403: "Request rejected by the backend (invalid host).",
  409: "This action was already decided.",
  410: "This approval expired — ask the assistant to try again.",
  415: "Backend rejected the request (expected JSON).",
  422: "Backend rejected the edited arguments.",
  503: "Backend is not configured yet, see /api/health",
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

function parseJson(raw: string): unknown {
  try {
    return JSON.parse(raw);
  } catch {
    return null;
  }
}

function httpError(status: number): StreamError {
  return {
    kind: status === 503 ? "server" : "http",
    message: HTTP_ERROR_MESSAGES[status] ?? `Backend error (HTTP ${status}).`,
  };
}

function parseClassification(value: unknown): ToolClassification | "unknown" {
  return value === "read" || value === "write" || value === "destructive" ? value : "unknown";
}

function parseToolCall(payload: unknown): ToolCallBase | null {
  if (!isRecord(payload) || typeof payload.tool !== "string") return null;
  return {
    tool: payload.tool,
    classification: parseClassification(payload.classification),
    listed: payload.listed === true,
    args: isRecord(payload.args) ? payload.args : {},
  };
}

function parseToolResult(payload: unknown): ToolResultData | null {
  if (!isRecord(payload) || typeof payload.tool !== "string" || typeof payload.result !== "string") {
    return null;
  }
  return {
    tool: payload.tool,
    result: payload.result,
    ok: typeof payload.ok === "boolean" ? payload.ok : true,
  };
}

function parseApprovalRequest(payload: unknown): ApprovalRequest | null {
  const base = parseToolCall(payload);
  if (!base || !isRecord(payload)) return null;
  const cost = payload.estimated_cost_tasks;
  return {
    ...base,
    estimatedCostTasks: typeof cost === "number" && Number.isFinite(cost) ? cost : 0,
    pendingActionId: typeof payload.pending_action_id === "string" ? payload.pending_action_id : "",
  };
}

function parseFrame(frame: string): SseFrame | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const line of frame.split("\n")) {
    if (line.startsWith("event:")) event = line.slice("event:".length).trim();
    else if (line.startsWith("data:")) dataLines.push(line.slice("data:".length).trim());
  }
  if (event === "message" && dataLines.length === 0) return null;
  return { event, data: dataLines.join("\n") };
}

function handleFrame(frame: SseFrame, handlers: StreamHandlers): void {
  const payload = parseJson(frame.data);
  if (frame.event === "done") {
    handlers.onDone({
      stoppedForApproval: isRecord(payload) && payload.stopped_for_approval === true,
    });
    return;
  }
  if (frame.event === "token" && isRecord(payload) && typeof payload.text === "string") {
    handlers.onToken(payload.text);
    return;
  }
  if (frame.event === "error") {
    handlers.onError({
      kind: "server",
      message:
        isRecord(payload) && typeof payload.message === "string"
          ? payload.message
          : "Backend reported an error.",
    });
    return;
  }
  if (frame.event === "tool_proposed") {
    const proposal = parseToolCall(payload);
    if (proposal) handlers.onToolProposed(proposal);
    return;
  }
  if (frame.event === "tool_result") {
    const result = parseToolResult(payload);
    if (result) handlers.onToolResult(result);
    return;
  }
  if (frame.event === "approval_required") {
    const request = parseApprovalRequest(payload);
    if (request) handlers.onApprovalRequired(request);
  }
}

async function postJson(
  url: string,
  body: unknown,
  signal: AbortSignal,
  handlers: StreamHandlers,
): Promise<Response | null> {
  try {
    const response = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
      signal,
    });
    if (!response.ok) {
      handlers.onError(httpError(response.status));
      return null;
    }
    return response;
  } catch {
    if (!signal.aborted) {
      handlers.onError({
        kind: "offline",
        message: "Backend unreachable — is the API running on localhost:8000?",
      });
    }
    return null;
  }
}

async function readEventStream(
  response: Response,
  signal: AbortSignal,
  handlers: StreamHandlers,
): Promise<void> {
  if (!response.body) {
    handlers.onError({ kind: "http", message: "Backend returned an empty stream." });
    return;
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let settled = false;
  const wrapped: StreamHandlers = {
    onToken: handlers.onToken,
    onToolProposed: handlers.onToolProposed,
    onToolResult: handlers.onToolResult,
    onApprovalRequired: handlers.onApprovalRequired,
    onDone: (meta) => {
      settled = true;
      handlers.onDone(meta);
    },
    onError: (streamError) => {
      settled = true;
      handlers.onError(streamError);
    },
  };

  const emitFrame = (raw: string) => {
    const frame = parseFrame(raw);
    if (frame) handleFrame(frame, wrapped);
  };

  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const frames = buffer.split("\n\n");
      buffer = frames.pop() ?? "";
      for (const raw of frames) emitFrame(raw);
    }
    buffer += decoder.decode();
    if (buffer.trim().length > 0) emitFrame(buffer);
    if (!settled && !signal.aborted) handlers.onDone({ stoppedForApproval: false });
  } catch {
    if (!signal.aborted) {
      handlers.onError({ kind: "client", message: "Stream interrupted while reading the reply." });
    }
  }
}

export async function streamChat(
  message: string,
  signal: AbortSignal,
  handlers: StreamHandlers,
): Promise<void> {
  const response = await postJson(`${API_BASE}/api/chat`, { message }, signal, handlers);
  if (!response) return;
  await readEventStream(response, signal, handlers);
}

/**
 * POST /api/approvals/{id} — approve, reject, or edit a pending action.
 * Approve answers with an SSE continuation that is fed to `handlers` so it
 * streams into the same assistant message; reject/edit answer with plain JSON.
 * Returns null when the request failed (the error was already reported).
 */
export async function decideOnApproval(
  pendingActionId: string,
  action: ApprovalDecisionAction,
  args: Record<string, unknown> | null,
  signal: AbortSignal,
  handlers: StreamHandlers,
): Promise<ApprovalDecisionOutcome | null> {
  const body: Record<string, unknown> = { action };
  if (action === "edit") body.args = args ?? {};

  const response = await postJson(
    `${API_BASE}/api/approvals/${encodeURIComponent(pendingActionId)}`,
    body,
    signal,
    handlers,
  );
  if (!response) return null;

  const contentType = response.headers.get("content-type") ?? "";
  if (contentType.includes("text/event-stream")) {
    await readEventStream(response, signal, handlers);
    return { kind: "streamed" };
  }

  const payload = parseJson(await response.text());
  if (isRecord(payload) && payload.status === "rejected") return { kind: "rejected" };
  if (isRecord(payload) && payload.status === "pending" && isRecord(payload.args)) {
    return { kind: "pending", args: payload.args };
  }
  handlers.onError({ kind: "http", message: "Backend returned an unexpected approval response." });
  return null;
}
