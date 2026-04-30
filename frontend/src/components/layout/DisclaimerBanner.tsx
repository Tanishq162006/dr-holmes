export function DisclaimerBanner() {
  return (
    <div className="bg-amber-100 dark:bg-amber-950/40 border-b border-amber-300 dark:border-amber-900/50 px-4 py-1.5 text-[11px] tabular smallcaps text-amber-900 dark:text-amber-200">
      <div className="max-w-7xl mx-auto flex items-center gap-3 justify-center">
        <span className="font-semibold">⚠ Educational research</span>
        <span className="opacity-70">•</span>
        <span>Not medical advice</span>
        <span className="opacity-70">•</span>
        <span>Not FDA-approved</span>
        <span className="opacity-70">•</span>
        <span>AI outputs may be incorrect</span>
      </div>
    </div>
  );
}
