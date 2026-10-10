import { useCallback, useRef, useState, type FormEvent } from "react";
import { decideOnApproval, streamChat, type StreamError } from "@/lib/chatStream";
import {
  approvalEntry,
  markAwaitingApproval,
  toolEntry,
  updateToolResult,
  type ApprovalDecisionAction,
  type ApprovalEntry,
  type TurnActivity,
} from "@/lib/toolActivity";

export type ChatStatus = "idle" | "loading" | "streaming";

export type ChatMessageData = {
  id: string;
  role: "user" | "assistant";
  text: string;
  activity: TurnActivity[];
  stoppedForApproval: boolean;
};

export function useChat() {
  const [messages, setMessages] = useState<ChatMessageData[]>([]);
  const [draft, setDraft] = useState("");
  const [status, setStatus] = useState<ChatStatus>("idle");
  const [error, setError] = useState<StreamError | null>(null);
  const [decidingId, setDecidingId] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const decidedRef = useRef<Set<string>>(new Set());

  const stop = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    setStatus("idle");
  }, []);

  const dismissError = useCallback(() => setError(null), []);

  const send = useCallback(
    async (event: FormEvent<HTMLFormElement>) => {
      event.preventDefault();
      const text = draft.trim();
      if (!text || status !== "idle") return;
      setDraft("");
      setError(null);
      const replyId = crypto.randomUUID();
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "user",
          text,
          activity: [],
          stoppedForApproval: false,
        },
        { id: replyId, role: "assistant", text: "", activity: [], stoppedForApproval: false },
      ]);
      setStatus("loading");
      const controller = new AbortController();
      abortRef.current = controller;
      let streaming = false;
      const updateReply = (update: (message: ChatMessageData) => ChatMessageData) => {
        setMessages((prev) => prev.map((m) => (m.id === replyId ? update(m) : m)));
      };
      try {
        await streamChat(text, controller.signal, {
          onToken: (chunk) => {
            if (!streaming) {
              streaming = true;
              setStatus("streaming");
            }
            updateReply((message) => ({ ...message, text: message.text + chunk }));
          },
          onToolProposed: (proposal) => {
            updateReply((message) => ({
              ...message,
              activity: [...message.activity, toolEntry(proposal, crypto.randomUUID())],
            }));
          },
          onToolResult: (result) => {
            updateReply((message) => ({
              ...message,
              activity: updateToolResult(message.activity, result),
            }));
          },
          onApprovalRequired: (request) => {
            updateReply((message) => ({
              ...message,
              activity: [
                ...markAwaitingApproval(message.activity, request.tool),
                approvalEntry(request, crypto.randomUUID()),
              ],
            }));
          },
          onDone: ({ stoppedForApproval }) => {
            if (stoppedForApproval) {
              updateReply((message) => ({ ...message, stoppedForApproval: true }));
            }
            setStatus("idle");
          },
          onError: (streamError) => {
            setError(streamError);
            setStatus("idle");
          },
        });
      } catch {
        setError({ kind: "client", message: "Unexpected client error." });
        setStatus("idle");
      } finally {
        abortRef.current = null;
      }
    },
    [draft, status],
  );

  /**
   * Act on an approval card: approve (streams the continuation into the same
   * message), reject, or edit (updates the card args, stays pending).
   * Single-use: each pending action id can only be decided once.
   */
  const decide = useCallback(
    async (pendingActionId: string, action: ApprovalDecisionAction, editedArgs?: Record<string, unknown>) => {
      if (decidedRef.current.has(pendingActionId)) return;
      if (action !== "edit") decidedRef.current.add(pendingActionId);
      setDecidingId(pendingActionId);

      const replyId = messages
        .slice()
        .reverse()
        .find(
          (m) =>
            m.role === "assistant" &&
            m.activity.some((a) => a.kind === "approval" && a.pendingActionId === pendingActionId),
        )?.id;
      if (!replyId) return;

      const updateReply = (update: (message: ChatMessageData) => ChatMessageData) => {
        setMessages((prev) => prev.map((m) => (m.id === replyId ? update(m) : m)));
      };
      const updateApproval = (update: (entry: ApprovalEntry) => ApprovalEntry) => {
        updateReply((message) => ({
          ...message,
          activity: message.activity.map((a) =>
            a.kind === "approval" && a.pendingActionId === pendingActionId ? update(a) : a,
          ),
        }));
      };

      if (action === "edit" && editedArgs) {
        updateApproval((entry) => ({ ...entry, args: editedArgs }));
      }
      if (action === "approve") {
        updateApproval((entry) => ({ ...entry, decision: "approved" }));
        setStatus("streaming");
      }
      if (action === "reject") {
        updateApproval((entry) => ({ ...entry, decision: "rejected" }));
      }

      let streaming = false;
      const outcome = await decideOnApproval(
        pendingActionId,
        action,
        action === "edit" ? (editedArgs ?? {}) : null,
        new AbortController().signal,
        {
          onToken: (chunk) => {
            if (!streaming) {
              streaming = true;
              setStatus("streaming");
            }
            updateReply((message) => ({ ...message, text: message.text + chunk }));
          },
          onToolProposed: (proposal) => {
            updateReply((message) => ({
              ...message,
              activity: [...message.activity, toolEntry(proposal, crypto.randomUUID())],
            }));
          },
          onToolResult: (result) => {
            updateReply((message) => ({
              ...message,
              activity: updateToolResult(message.activity, result),
            }));
          },
          onApprovalRequired: (request) => {
            updateReply((message) => ({
              ...message,
              activity: [
                ...markAwaitingApproval(message.activity, request.tool),
                approvalEntry(request, crypto.randomUUID()),
              ],
            }));
          },
          onDone: ({ stoppedForApproval }) => {
            if (stoppedForApproval) {
              updateReply((message) => ({ ...message, stoppedForApproval: true }));
            }
            updateApproval((entry) => ({ ...entry, decisionOutcome: "done" }));
            setStatus("idle");
          },
          onError: (streamError) => {
            setError(streamError);
            updateApproval((entry) => ({ ...entry, decisionOutcome: "error" }));
            setStatus("idle");
          },
        },
      );

      if (outcome?.kind === "pending") {
        // Edit accepted: the card stays pending with the new args.
        decidedRef.current.delete(pendingActionId);
        updateApproval((entry) => ({ ...entry, args: outcome.args }));
      }
      setDecidingId(null);
    },
    [messages],
  );

  return {
    messages,
    draft,
    setDraft,
    status,
    error,
    send,
    stop,
    dismissError,
    decide,
    decidingId,
  };
}
