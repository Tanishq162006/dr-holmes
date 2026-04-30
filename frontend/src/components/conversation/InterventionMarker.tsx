"use client";

import { motion } from "framer-motion";

export type InterventionMarkerKind =
  | "evidence_injected"
  | "evidence_conflict"
  | "intervention_failed";

export interface InterventionMarkerProps {
  kind: InterventionMarkerKind;
  text: string;
}

const kindMeta: Record<InterventionMarkerKind, { icon: string; cls: string }> = {
  evidence_injected: {
    icon: "📋",
    cls: "text-emerald-500 border-emerald-500/30",
  },
  evidence_conflict: {
    icon: "⚠",
    cls: "text-amber-500 border-amber-500/40",
  },
  intervention_failed: {
    icon: "❌",
    cls: "text-rose-500 border-rose-500/40",
  },
};

export function InterventionMarker({ kind, text }: InterventionMarkerProps) {
  const meta = kindMeta[kind];
  return (
    <motion.div
      initial={{ opacity: 0 }}
      animate={{ opacity: 1 }}
      transition={{ duration: 0.2 }}
      className="my-2 flex items-center gap-2"
    >
      <span className={`flex-1 border-t border-dashed ${meta.cls.split(" ").find((c) => c.startsWith("border-")) ?? ""}`} />
      <span className={`text-[11px] smallcaps inline-flex items-center gap-1.5 px-2 py-0.5 ${meta.cls}`}>
        <span aria-hidden>{meta.icon}</span>
        <span>{text}</span>
      </span>
      <span className={`flex-1 border-t border-dashed ${meta.cls.split(" ").find((c) => c.startsWith("border-")) ?? ""}`} />
    </motion.div>
  );
}
