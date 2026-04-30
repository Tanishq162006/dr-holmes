/**
 * WebSocket client with auto-reconnect + sequence-based replay.
 *
 * On every (re)connect we send `?from_sequence=N` so we resume exactly
 * where we left off. Phase 4 backend already implements this via Redis
 * Stream + Postgres audit_log.
 */
import { useCaseStore } from "@/lib/stores/caseStore";
import { useSettingsStore } from "@/lib/stores/settingsStore";
import { WSEventSchema, WSCommandSchema, type WSCommand } from "@/lib/types/wire";

let activeClient: CaseStreamClient | null = null;

export class CaseStreamClient {
  private ws: WebSocket | null = null;
  private retries = 0;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private closedByUs = false;
  private readonly maxBackoffMs = 30_000;

  constructor(public readonly caseId: string, public readonly replay = false) {}

  connect() {
    const fromSeq = useCaseStore.getState().lastSequence;
    const apiBase = useSettingsStore.getState().apiBaseUrl;
    const wsBase = apiBase.replace(/^http/, "ws");

    const url = new URL(`${wsBase}/ws/cases/${this.caseId}`);
    url.searchParams.set("from_sequence", String(fromSeq));
    if (this.replay) url.searchParams.set("replay", "true");

    useCaseStore.getState().setWSState(this.retries === 0 ? "connecting" : "reconnecting");
    this.ws = new WebSocket(url.toString());

    this.ws.onopen = () => {
      this.retries = 0;
      useCaseStore.getState().setWSState("connected");
      // Heartbeat ack so backend keeps the stream alive on idle servers
      this.heartbeat = setInterval(() => {
        this.send({ command: "ack", case_id: this.caseId, payload: {} });
      }, 30_000);
    };

    this.ws.onmessage = (msg) => {
      let parsed: unknown;
      try { parsed = JSON.parse(msg.data as string); }
      catch { return; }

      // Server sends initial handshake/replay_complete frames that aren't WSEvents
      if (parsed && typeof parsed === "object" && "type" in parsed) return;

      const result = WSEventSchema.safeParse(parsed);
      if (!result.success) {
        // Loud fail on schema drift — visible in dev console
        console.warn("WS event schema mismatch:", result.error, parsed);
        return;
      }
      useCaseStore.getState().ingestEvent(result.data);
    };

    this.ws.onclose = () => {
      this.cleanup();
      if (this.closedByUs) return;
      this.scheduleReconnect();
    };

    this.ws.onerror = () => {
      // onclose will follow
    };
  }

  send(cmd: WSCommand) {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    const validated = WSCommandSchema.parse(cmd);
    this.ws.send(JSON.stringify(validated));
  }

  close() {
    this.closedByUs = true;
    this.cleanup();
    this.ws?.close();
    this.ws = null;
    useCaseStore.getState().setWSState("disconnected");
  }

  private cleanup() {
    if (this.heartbeat) {
      clearInterval(this.heartbeat);
      this.heartbeat = null;
    }
  }

  private scheduleReconnect() {
    if (this.replay) {
      // Replay mode is one-shot — no reconnect
      useCaseStore.getState().setWSState("disconnected");
      return;
    }
    const delay = Math.min(1000 * 2 ** this.retries, this.maxBackoffMs);
    this.retries++;
    useCaseStore.getState().bumpRetry();
    setTimeout(() => this.connect(), delay);
  }
}

export function startCaseStream(caseId: string, replay = false): CaseStreamClient {
  if (activeClient) activeClient.close();
  activeClient = new CaseStreamClient(caseId, replay);
  activeClient.connect();
  return activeClient;
}

export function stopCaseStream() {
  activeClient?.close();
  activeClient = null;
}

export function sendCommand(cmd: WSCommand) {
  activeClient?.send(cmd);
}
