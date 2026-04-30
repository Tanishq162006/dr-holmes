import { AlertTriangle } from "lucide-react";
import type { HauserDissent } from "@/lib/types/wire";
import { formatProb } from "@/lib/utils";

export function DissentPanel({ dissent }: { dissent: HauserDissent }) {
  return (
    <aside className="my-6 rounded-lg border-2 border-amber-500 bg-amber-500/10 p-4">
      <header className="flex items-center gap-2">
        <AlertTriangle size={16} className="text-amber-500" />
        <h3 className="font-bold smallcaps text-amber-700 dark:text-amber-400">
          Dissent from Dr. Hauser
        </h3>
      </header>
      <div className="mt-3 space-y-2 text-sm">
        <p>
          <span className="font-bold text-rose-600 dark:text-rose-400">
            {dissent.hauser_dx}
          </span>{" "}
          <span className="text-[hsl(var(--muted-foreground))] tabular">
            ({formatProb(dissent.hauser_confidence)})
          </span>
        </p>
        <p className="leading-relaxed">{dissent.rationale}</p>
        {dissent.recommended_test && (
          <p className="text-xs text-[hsl(var(--muted-foreground))]">
            Recommended additional test:{" "}
            <span className="font-medium text-[hsl(var(--foreground))]">
              {dissent.recommended_test.test_name}
            </span>
          </p>
        )}
      </div>
    </aside>
  );
}
