export function RoundDivider({ round, tokenCount }: { round: number; tokenCount?: number }) {
  return (
    <div className="flex items-center gap-3 py-4 my-2">
      <div className="flex-1 h-px bg-[hsl(var(--border))]" />
      <span className="smallcaps text-[10px] tabular text-[hsl(var(--muted-foreground))]">
        round {round}
      </span>
      <div className="flex-1 h-px bg-[hsl(var(--border))]" />
      {tokenCount !== undefined && (
        <span className="text-[10px] tabular text-[hsl(var(--muted-foreground))] opacity-70">
          {tokenCount.toLocaleString()} tokens
        </span>
      )}
    </div>
  );
}
