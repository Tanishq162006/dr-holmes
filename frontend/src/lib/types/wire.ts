/**
 * WebSocket + REST type contracts. Mirrors dr_holmes/api/schemas/events.py
 * and dr_holmes/schemas/responses.py exactly. Validated at the network
 * boundary so type drift fails loudly with a toast.
 */
import { z } from "zod";

// ── Agents ────────────────────────────────────────────────────────────────
export const AGENT_NAMES = ["Hauser", "Forman", "Carmen", "Chen", "Wills", "Caddick"] as const;
export type AgentName = (typeof AGENT_NAMES)[number];
export const AgentNameSchema = z.enum(AGENT_NAMES);

export const AgentProfileSchema = z.object({
  name: z.string(),
  specialty: z.string(),
  bias: z.string(),
  model_provider: z.string(),
  model_id: z.string(),
  description: z.string(),
});
export type AgentProfile = z.infer<typeof AgentProfileSchema>;

// ── Differentials, challenges, tests ──────────────────────────────────────
export const DifferentialSchema = z.object({
  diagnosis: z.string(),
  probability: z.number().min(0).max(1),
  rationale: z.string().optional().default(""),
  supporting_evidence: z.array(z.string()).optional().default([]),
  contradicting_evidence: z.array(z.string()).optional().default([]),
});
export type Differential = z.infer<typeof DifferentialSchema>;

export const TeamDifferentialSchema = z.object({
  disease: z.string(),
  probability: z.number().min(0).max(1),
  proposed_by: z.string().optional().default(""),
  supporting_evidence: z.array(z.string()).optional().default([]),
  against_evidence: z.array(z.string()).optional().default([]),
});
export type TeamDifferential = z.infer<typeof TeamDifferentialSchema>;

export const ChallengeSchema = z.object({
  target_agent: z.string(),
  challenge_type: z.enum([
    "disagree_dx", "disagree_test", "missing_consideration",
    "evidence_mismatch", "personality_call",
  ]),
  content: z.string(),
});
export type Challenge = z.infer<typeof ChallengeSchema>;

export const TestProposalSchema = z.object({
  test_name: z.string(),
  rationale: z.string().optional().default(""),
  expected_information_gain: z.number().optional().default(0),
  rules_in: z.array(z.string()).optional().default([]),
  rules_out: z.array(z.string()).optional().default([]),
});
export type TestProposal = z.infer<typeof TestProposalSchema>;

export const AgentResponseSchema = z.object({
  agent_name: z.string(),
  turn_number: z.number().int().nonnegative(),
  reasoning: z.string().optional().default(""),
  differentials: z.array(DifferentialSchema).optional().default([]),
  proposed_tests: z.array(TestProposalSchema).optional().default([]),
  challenges: z.array(ChallengeSchema).optional().default([]),
  confidence: z.number().min(0).max(1),
  defers_to_team: z.boolean().optional().default(false),
  request_floor: z.boolean().optional().default(false),
  force_speak: z.boolean().optional().default(false),
});
export type AgentResponse = z.infer<typeof AgentResponseSchema>;

// ── Final report ──────────────────────────────────────────────────────────
export const HauserDissentSchema = z.object({
  hauser_dx: z.string(),
  hauser_confidence: z.number(),
  rationale: z.string(),
  recommended_test: TestProposalSchema.nullable().optional(),
});
export type HauserDissent = z.infer<typeof HauserDissentSchema>;

export const FinalReportSchema = z.object({
  case_id: z.string(),
  consensus_dx: z.string(),
  confidence: z.number(),
  rounds_taken: z.number().int(),
  hauser_dissent: HauserDissentSchema.nullable().optional(),
  recommended_workup: z.array(TestProposalSchema).optional().default([]),
  deliberation_summary: z.string().optional().default(""),
  convergence_reason: z.string(),
});
export type FinalReport = z.infer<typeof FinalReportSchema>;

// ── Patient case ──────────────────────────────────────────────────────────
export const PatientPresentationSchema = z.object({
  presenting_complaint: z.string(),
  history: z.string().optional().default(""),
  vitals: z.record(z.string(), z.union([z.string(), z.number()])).optional().default({}),
  labs: z.record(z.string(), z.union([z.string(), z.number()])).optional().default({}),
  imaging: z.record(z.string(), z.unknown()).optional().default({}),
  medications: z.array(z.string()).optional().default([]),
  allergies: z.array(z.string()).optional().default([]),
  additional_findings: z.array(z.string()).optional().default([]),
});
export type PatientPresentation = z.infer<typeof PatientPresentationSchema>;

export const CaseStatusSchema = z.enum([
  "pending", "running", "paused", "concluded", "errored", "interrupted",
]);
export type CaseStatus = z.infer<typeof CaseStatusSchema>;

export const CaseSummarySchema = z.object({
  id: z.string(),
  owner_id: z.string(),
  status: CaseStatusSchema,
  mock_mode: z.boolean(),
  rounds_taken: z.number().int(),
  convergence_reason: z.string().nullable().optional(),
  created_at: z.string(),
  concluded_at: z.string().nullable().optional(),
});
export type CaseSummary = z.infer<typeof CaseSummarySchema>;

export const CaseDetailSchema = CaseSummarySchema.extend({
  patient_presentation: PatientPresentationSchema,
  final_report: FinalReportSchema.nullable().optional(),
});
export type CaseDetail = z.infer<typeof CaseDetailSchema>;

// ── WebSocket events ──────────────────────────────────────────────────────
export const WS_EVENT_TYPES = [
  "case_started", "round_started",
  "agent_thinking", "agent_response",
  "tool_call", "tool_result",
  "bayesian_update",
  "challenge_raised", "challenge_resolved",
  "caddick_routing", "convergence_check",
  "case_paused", "case_resumed", "evidence_injected",
  "case_converged", "final_report",
  "error",
] as const;
export type WSEventType = (typeof WS_EVENT_TYPES)[number];

export const WSEventSchema = z.object({
  protocol_version: z.literal("v1").optional().default("v1"),
  sequence: z.number().int().nonnegative(),
  case_id: z.string(),
  event_type: z.enum(WS_EVENT_TYPES),
  timestamp: z.string(),
  payload: z.record(z.string(), z.unknown()),
});
export type WSEvent = z.infer<typeof WSEventSchema>;

// Per-event-type payload schemas (parsed lazily where needed)
export const RoundStartedPayload = z.object({
  round_number: z.number().int().positive(),
  planned_speakers: z.array(z.string()).optional().default([]),
});
export const AgentResponsePayload = z.object({
  agent_name: z.string(),
  response: AgentResponseSchema,
});
export const BayesianUpdatePayload = z.object({
  top_dx: z.string(),
  top_prob: z.number(),
  deltas: z.array(z.object({
    disease: z.string(),
    prev: z.number().nullable().optional(),
    now: z.number(),
    change: z.number(),
  })).optional().default([]),
});
export const CaddickRoutingPayload = z.object({
  next_speakers: z.array(z.string()),
  routing_reason: z.string(),
  synthesis_text: z.string(),
});
export const FinalReportPayload = z.object({
  report: FinalReportSchema,
});
export const ChallengeRaisedPayload = z.object({
  raiser: z.string(),
  target: z.string(),
  challenge_type: z.string(),
  content: z.string(),
});

// ── Client → server commands ──────────────────────────────────────────────
export const WSCommandSchema = z.object({
  command: z.enum([
    "pause", "resume", "inject_evidence",
    "question_agent", "correct_agent", "conclude_now", "ack",
  ]),
  case_id: z.string(),
  payload: z.record(z.string(), z.unknown()).optional().default({}),
  client_id: z.string().optional(),
});
export type WSCommand = z.infer<typeof WSCommandSchema>;
