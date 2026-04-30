/**
 * REST client for the Dr. Holmes FastAPI backend.
 * Validates every response with zod schemas from lib/types/wire.ts.
 */
import {
  CaseDetailSchema, CaseSummarySchema, AgentProfileSchema,
  type CaseDetail, type CaseSummary, type AgentProfile, type PatientPresentation,
  type WSEvent, WSEventSchema,
} from "./types/wire";
import { z } from "zod";
import { useSettingsStore } from "./stores/settingsStore";

function base(): string {
  return useSettingsStore.getState().apiBaseUrl;
}

async function jsonOrThrow<T>(res: Response, schema: z.ZodSchema<T>): Promise<T> {
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`${res.status} ${res.statusText}: ${text.slice(0, 200)}`);
  }
  const data = await res.json();
  return schema.parse(data);
}

// ── Cases ─────────────────────────────────────────────────────────────────

export async function listCases(opts?: { status?: string; limit?: number }): Promise<CaseSummary[]> {
  const url = new URL(`${base()}/api/cases`);
  if (opts?.status) url.searchParams.set("status", opts.status);
  if (opts?.limit) url.searchParams.set("limit", String(opts.limit));
  const res = await fetch(url.toString());
  return jsonOrThrow(res, z.array(CaseSummarySchema));
}

export async function getCase(caseId: string): Promise<CaseDetail> {
  const res = await fetch(`${base()}/api/cases/${caseId}`);
  return jsonOrThrow(res, CaseDetailSchema);
}

export async function createCase(req: {
  patient_presentation: PatientPresentation;
  mock_mode: boolean;
  fixture_path?: string | null;
  max_rounds?: number;
}): Promise<CaseSummary> {
  const res = await fetch(`${base()}/api/cases`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(req),
  });
  return jsonOrThrow(res, CaseSummarySchema);
}

export async function getTranscript(caseId: string): Promise<WSEvent[]> {
  const res = await fetch(`${base()}/api/cases/${caseId}/transcript`);
  return jsonOrThrow(res, z.array(z.object({
    sequence: z.number(),
    event_type: z.string(),
    payload: z.record(z.string(), z.unknown()),
    timestamp: z.string().nullable().optional(),
  })).transform((rows) => rows.map((r) => WSEventSchema.parse({
    protocol_version: "v1",
    sequence: r.sequence,
    case_id: caseId,
    event_type: r.event_type,
    timestamp: r.timestamp ?? new Date().toISOString(),
    payload: r.payload,
  }))));
}

export async function pauseCase(caseId: string): Promise<void> {
  await fetch(`${base()}/api/cases/${caseId}/pause`, { method: "POST" });
}
export async function resumeCase(caseId: string): Promise<void> {
  await fetch(`${base()}/api/cases/${caseId}/resume`, { method: "POST" });
}
export async function concludeCase(caseId: string): Promise<void> {
  await fetch(`${base()}/api/cases/${caseId}/conclude`, { method: "POST" });
}

export async function injectEvidence(caseId: string, evidence: {
  type: string; name: string; value: string; is_present?: boolean;
}): Promise<void> {
  await fetch(`${base()}/api/cases/${caseId}/evidence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...evidence, is_present: evidence.is_present ?? true }),
  });
}

// ── Agents ────────────────────────────────────────────────────────────────

export async function listAgents(): Promise<AgentProfile[]> {
  const res = await fetch(`${base()}/api/agents`);
  return jsonOrThrow(res, z.array(AgentProfileSchema));
}

// ── Eval ──────────────────────────────────────────────────────────────────

export async function listEvalRuns(): Promise<Array<{
  run_id: string;
  is_multi_condition: boolean;
  timestamp?: string;
  n_cases_completed: number;
  top_1_accuracy?: number;
  top_3_accuracy?: number;
  total_cost_usd?: number;
}>> {
  const res = await fetch(`${base()}/api/eval/runs`);
  if (!res.ok) return [];
  return res.json();
}

export async function getEvalRun(runId: string): Promise<Record<string, unknown>> {
  const res = await fetch(`${base()}/api/eval/runs/${runId}`);
  if (!res.ok) throw new Error(`Failed to load run ${runId}`);
  return res.json();
}

export async function getEvalRunCases(runId: string, condition?: string): Promise<Array<Record<string, string>>> {
  const url = new URL(`${base()}/api/eval/runs/${runId}/cases`);
  if (condition) url.searchParams.set("condition", condition);
  const res = await fetch(url.toString());
  if (!res.ok) return [];
  return res.json();
}

export async function getEvalCaseEvents(runId: string, caseId: string): Promise<WSEvent[]> {
  const res = await fetch(`${base()}/api/eval/runs/${runId}/case/${caseId}/events`);
  if (!res.ok) throw new Error(`No events for ${caseId}`);
  const data = await res.json();
  return z.array(WSEventSchema).parse(data);
}
