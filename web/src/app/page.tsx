import { Chat } from "@/components/Chat";
import { ServerWakeGate } from "@/components/ServerWakeGate";
import { API_URL } from "@/lib/api";

export default function Home() {
  return (
    <main className="flex flex-1 flex-col">
      <ServerWakeGate apiUrl={API_URL}>
        <Chat />
      </ServerWakeGate>
    </main>
  );
}
