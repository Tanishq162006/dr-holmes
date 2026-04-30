"use client";

import { motion } from "framer-motion";
import { probBgColor } from "@/lib/utils";

export function ProbabilityBar({ value }: { value: number }) {
  const pct = Math.max(0, Math.min(1, value));
  return (
    <div className="relative h-1.5 w-full bg-[hsl(var(--muted))] rounded-full overflow-hidden">
      <motion.div
        className={`absolute inset-y-0 left-0 ${probBgColor(value)} rounded-full`}
        initial={{ width: 0 }}
        animate={{ width: `${pct * 100}%` }}
        transition={{ type: "spring", stiffness: 100, damping: 20, mass: 0.8 }}
      />
    </div>
  );
}
