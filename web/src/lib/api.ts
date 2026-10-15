export const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000").replace(/\/$/, "");

export type Source = {
  index: number;
  title: string;
  section: string;
  page: number;
  url: string;
  doc_type: "master_circular" | "circular";
  issued_on: string;
  relevance: number;
};

export type AskEvent =
  | { type: "sources"; sources: Source[] }
  | { type: "text"; block: number; text: string }
  | { type: "citation"; block: number; source: number; cited_text: string }
  | {
      type: "done";
      answered: boolean;
      truncated?: boolean;
      model?: string;
      timings_ms: Record<string, number>;
      usage?: { input_tokens: number; output_tokens: number };
    }
  | { type: "error"; message: string };

export type Stats = {
  documents: Record<string, number>;
  pages: number;
  chunks: number;
};

/** POST /ask and call `onEvent` for each Server-Sent Event as it arrives. */
export async function askStream(
  question: string,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const res = await fetch(`${API_URL}/ask`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ question }),
    signal,
  });
  if (!res.ok || !res.body) {
    let message = `Request failed (${res.status})`;
    try {
      const body = await res.json();
      if (typeof body.detail === "string") message = body.detail;
    } catch {
      // Not JSON; keep the status message.
    }
    onEvent({ type: "error", message });
    return;
  }

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += value;
    // SSE frames end with a blank line.
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      for (const line of frame.split("\n")) {
        if (line.startsWith("data: ")) onEvent(JSON.parse(line.slice(6)) as AskEvent);
      }
    }
  }
}

export async function fetchStats(): Promise<Stats | null> {
  try {
    const res = await fetch(`${API_URL}/stats`, { cache: "no-store" });
    return res.ok ? ((await res.json()) as Stats) : null;
  } catch {
    return null;
  }
}
