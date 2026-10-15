"use client";

/**
 * Drop into any Next.js app (e.g. components/ServerWakeGate.tsx) and wrap the part of the page
 * that needs the backend:
 *
 *   <ServerWakeGate apiUrl={process.env.NEXT_PUBLIC_API_URL!}>
 *     <Chat />
 *   </ServerWakeGate>
 *
 * Free-tier backends (Render/Koyeb) sleep when idle. This pings `${apiUrl}/health` on mount and
 * shows a friendly message until the server answers, so visitors never hit a dead request.
 */
import { useEffect, useState, type ReactNode } from "react";

type Status = "checking" | "waking" | "ready" | "down";

const RETRY_EVERY_MS = 3_000;
const GIVE_UP_AFTER_MS = 90_000;
const SHOW_WAKING_AFTER_MS = 1_500;

export function ServerWakeGate({ apiUrl, children }: { apiUrl: string; children: ReactNode }) {
  const [status, setStatus] = useState<Status>("checking");
  const [elapsed, setElapsed] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const started = Date.now();
    const wakingTimer = setTimeout(() => {
      if (!cancelled) setStatus((s) => (s === "checking" ? "waking" : s));
    }, SHOW_WAKING_AFTER_MS);
    const tick = setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);

    async function poll() {
      while (!cancelled && Date.now() - started < GIVE_UP_AFTER_MS) {
        try {
          const res = await fetch(`${apiUrl}/health`, { cache: "no-store" });
          if (res.ok) {
            if (!cancelled) setStatus("ready");
            return;
          }
        } catch {
          // Server still asleep or booting; keep trying.
        }
        await new Promise((r) => setTimeout(r, RETRY_EVERY_MS));
      }
      if (!cancelled) setStatus("down");
    }
    poll();

    return () => {
      cancelled = true;
      clearTimeout(wakingTimer);
      clearInterval(tick);
    };
  }, [apiUrl]);

  if (status === "ready") return <>{children}</>;
  if (status === "checking") return null;

  return (
    <div role="status" aria-live="polite" className="mx-auto max-w-md px-4 py-24 text-center">
      {status === "waking" ? (
        <>
          <p className="font-medium">Waking up the server… {elapsed}s</p>
          <p className="mt-2 text-sm text-muted">
            This demo runs on free hosting that sleeps when idle. First load takes up to a minute.
          </p>
        </>
      ) : (
        <>
          <p className="font-medium">The server didn&apos;t respond.</p>
          <p className="mt-2 text-sm text-muted">Please refresh in a minute, or watch the demo video.</p>
        </>
      )}
    </div>
  );
}
