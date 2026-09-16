import { useEffect, useState } from "react";

export type SseMessage = {
  event: string;
  data: string;
};

/**
 * SSE helper. In mock mode, emits a short synthetic stream.
 * Does not embed secrets in URLs beyond the session access token used by the API.
 */
export function useProcessRunEvents(runId: string | null, url: string | null) {
  const [messages, setMessages] = useState<SseMessage[]>([]);
  const [status, setStatus] = useState<"idle" | "connecting" | "open" | "error">("idle");

  useEffect(() => {
    if (!runId || !url) return;

    setMessages([]);
    setStatus("connecting");

    if (url.startsWith("mock://")) {
      const timer = window.setTimeout(() => {
        setStatus("open");
        setMessages([
          { event: "process_run", data: JSON.stringify({ type: "run.status_changed", status: "executing" }) },
          { event: "done", data: "{}" },
        ]);
      }, 200);
      return () => window.clearTimeout(timer);
    }

    const source = new EventSource(url);
    source.onopen = () => setStatus("open");
    source.onerror = () => setStatus("error");
    source.addEventListener("process_run", (event) => {
      setMessages((prev) => [...prev, { event: "process_run", data: (event as MessageEvent).data }]);
    });
    source.addEventListener("done", () => {
      setMessages((prev) => [...prev, { event: "done", data: "{}" }]);
      source.close();
    });
    return () => source.close();
  }, [runId, url]);

  return { messages, status };
}
