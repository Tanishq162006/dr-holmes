"use client";

import { motion } from "framer-motion";
import { metaFor } from "@/lib/agents";
import type { AgentResponse } from "@/lib/types/wire";
import { formatProb, probColor } from "@/lib/utils";
import { Megaphone, AlertCircle } from "lucide-react";

export function AgentMessage({
  agent,
  response,
}: {
  agent: string;
  response: AgentResponse;
}) {
  const meta = metaFor(agent);
  const top = response.differentials[0];

  return (
    <motion.article
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.25, ease: "easeOut" }}
      className="relative pl-5 py-4 pr-1"
    >
      <div className={`absolute left-0 top-4 bottom-2 w-[3px] rounded-full ${meta.bgClass} opacity-90`} />

      <header className="flex items-baseline gap-2">
        <div className={`w-7 h-7 rounded-full ${meta.bgClass} text-white grid place-items-center text-[11px] font-bold shrink-0`}>
          {meta.initial}
        </div>
        <div className="flex items-baseline gap-2 flex-wrap">
          <span className={`font-semibold text-sm ${meta.textClass}`}>Dr. {agent}</span>
          <span className="text-[11px] text-[hsl(var(--muted-foreground))]">{meta.specialty}</span>
          {response.request_floor && (
            <span className="text-[10px] smallcaps text-amber-500 inline-flex items-center gap-1">
              <Megaphone size={10} /> requests floor
            </span>
          )}
          {response.force_speak && (
            <span className="text-[10px] smallcaps text-rose-500 inline-flex items-center gap-1">
              <AlertCircle size={10} /> force speak
            </span>
          )}
          <span className="ml-auto text-[10px] smallcaps text-[hsl(var(--muted-foreground))]">
            turn {response.turn_number}
          </span>
        </div>
      </header>

      <div className="ml-9 mt-2 space-y-2.5 text-sm">
        {response.reasoning && (
          <p className="text-[hsl(var(--muted-foreground))] italic leading-relaxed">
            {response.reasoning}
          </p>
        )}

        {response.differentials.length > 0 && (
          <div className="space-y-1.5">
            <div className="text-[11px] smallcaps text-[hsl(var(--muted-foreground))]">
              Differential
            </div>
            <ul className="space-y-1">
              {response.differentials.slice(0, 5).map((d, i) => (
                <li key={i} className="flex items-baseline gap-2 text-xs">
                  <span className={`tabular ${probColor(d.probability)}`}>
                    {formatProb(d.probability)}
                  </span>
                  <span className="font-medium">{d.diagnosis}</span>
                  {d.rationale && (
                    <span className="text-[hsl(var(--muted-foreground))] truncate">
                      — {d.rationale}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {response.proposed_tests.length > 0 && (
          <div className="space-y-1">
            <div className="text-[11px] smallcaps text-[hsl(var(--muted-foreground))]">
              Proposed tests
            </div>
            <ul className="space-y-0.5 text-xs">
              {response.proposed_tests.slice(0, 3).map((t, i) => (
                <li key={i} className="flex items-baseline gap-2">
                  <span className={meta.textClass}>→</span>
                  <span className="font-medium">{t.test_name}</span>
                  {t.rules_in.length > 0 && (
                    <span className="text-[10px] text-[hsl(var(--muted-foreground))]">
                      rules in: {t.rules_in.slice(0, 2).join(", ")}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}

        {response.challenges.length > 0 && (
          <div className="space-y-1">
            {response.challenges.map((c, i) => (
              <div
                key={i}
                className="text-xs flex items-start gap-1.5 px-2 py-1 rounded bg-amber-500/10 border border-amber-500/30"
              >
                <span className="text-amber-500">⚡</span>
                <span>
                  <span className="font-medium">→ {c.target_agent}:</span>{" "}
                  <span className="italic">&quot;{c.content}&quot;</span>
                </span>
              </div>
            ))}
          </div>
        )}

        <div className="flex items-center gap-3 text-[10px] tabular text-[hsl(var(--muted-foreground))] pt-1">
          <span>conf {formatProb(response.confidence)}</span>
          {top && (
            <span className="opacity-70">top: {top.diagnosis}</span>
          )}
          {response.defers_to_team && (
            <span className="text-slate-500 smallcaps">defers</span>
          )}
        </div>
      </div>
    </motion.article>
  );
}
