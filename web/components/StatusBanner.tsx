import type { StreamError } from "@/lib/chatStream";

const STYLES: Record<StreamError["kind"], string> = {
  offline: "border-warning bg-warning/10",
  server: "border-danger bg-danger/10",
  http: "border-danger bg-danger/10",
  client: "border-danger bg-danger/10",
};

type StatusBannerProps = {
  error: StreamError;
  onDismiss: () => void;
};

export default function StatusBanner({ error, onDismiss }: StatusBannerProps) {
  return (
    <div
      role="alert"
      className={`mx-4 mb-2 flex items-center justify-between gap-3 rounded-input border px-3 py-2 text-text sm:mx-6 ${STYLES[error.kind]}`}
    >
      <p className="text-sm">{error.message}</p>
      <button
        type="button"
        onClick={onDismiss}
        className="shrink-0 text-sm font-medium underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
      >
        Dismiss
      </button>
    </div>
  );
}
