import { metaFor } from "@/lib/agents";

export function CaddickRoutingNote({
  nextSpeakers,
  reason,
  synthesis,
}: {
  nextSpeakers: string[];
  reason: string;
  synthesis: string;
}) {
  const caddick = metaFor("Caddick");
  return (
    <div className="my-3 px-3 py-2.5 rounded-md bg-violet-500/5 border border-violet-500/20">
      <div className="flex items-baseline gap-2 mb-1">
        <span className={`text-[11px] font-semibold ${caddick.textClass}`}>Caddick</span>
        <span className="text-[10px] text-[hsl(var(--muted-foreground))] smallcaps">moderator</span>
        {nextSpeakers.length > 0 && (
          <span className="ml-auto text-[10px] tabular text-[hsl(var(--muted-foreground))]">
            calling on <span className={caddick.textClass}>{nextSpeakers.join(", ")}</span>
            {reason && <span className="ml-2 opacity-60">({reason})</span>}
          </span>
        )}
      </div>
      {synthesis && (
        <p className="text-xs text-[hsl(var(--muted-foreground))] leading-relaxed">
          {synthesis}
        </p>
      )}
    </div>
  );
}
