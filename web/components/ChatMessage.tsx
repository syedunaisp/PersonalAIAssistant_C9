type ChatMessageProps = {
  role: "user" | "assistant";
  text: string;
  isStreaming?: boolean;
};

const BUBBLE: Record<ChatMessageProps["role"], string> = {
  user: "self-end rounded-br-sm bg-primary text-primary-foreground",
  assistant:
    "self-start rounded-bl-sm border border-border-subtle bg-surface-raised text-text",
};

export default function ChatMessage({ role, text, isStreaming = false }: ChatMessageProps) {
  const waiting = isStreaming && text.length === 0;

  return (
    <div
      className={`message-in max-w-[85%] rounded-bubble px-4 py-2.5 shadow-sm sm:max-w-[75%] ${BUBBLE[role]}`}
    >
      <span className="sr-only">{role === "user" ? "You said:" : "Assistant:"}</span>
      {waiting ? (
        <span className="flex items-center gap-1 py-1" aria-hidden="true">
          {[0, 1, 2].map((index) => (
            <span
              key={index}
              className="typing-dot h-1.5 w-1.5 rounded-full bg-current"
              style={{ animationDelay: `${index * 150}ms` }}
            />
          ))}
        </span>
      ) : (
        <p className="whitespace-pre-wrap break-words text-sm leading-relaxed">
          {text}
          {isStreaming && <span className="streaming-caret" aria-hidden="true" />}
        </p>
      )}
    </div>
  );
}
