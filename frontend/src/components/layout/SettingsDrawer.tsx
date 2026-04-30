"use client";

import * as Dialog from "@radix-ui/react-dialog";
import * as Switch from "@radix-ui/react-switch";
import * as Slider from "@radix-ui/react-slider";
import { X } from "lucide-react";
import { useSettingsStore } from "@/lib/stores/settingsStore";

export function SettingsDrawer({ open, onClose }: { open: boolean; onClose: () => void }) {
  const s = useSettingsStore();

  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/40 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed right-0 top-0 bottom-0 z-50 w-full sm:w-[380px] bg-[hsl(var(--card))] border-l border-[hsl(var(--border))] p-5 overflow-y-auto focus:outline-none">
          <div className="flex items-center justify-between">
            <Dialog.Title className="font-semibold">Settings</Dialog.Title>
            <button onClick={onClose} className="p-1 rounded hover:bg-[hsl(var(--muted))]">
              <X size={16} />
            </button>
          </div>

          <div className="mt-6 space-y-6 text-sm">
            <Row label="LLM mode" hint="Use mock for free deterministic playback. Live calls real APIs.">
              <div className="flex gap-2">
                {(["mock", "live"] as const).map((m) => (
                  <button
                    key={m}
                    onClick={() => s.setLLMMode(m)}
                    className={`flex-1 px-3 py-1.5 rounded-md text-xs smallcaps border transition ${
                      s.llmMode === m
                        ? "border-rose-500 bg-rose-500/10 text-rose-500"
                        : "border-[hsl(var(--border))] hover:bg-[hsl(var(--muted))]"
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </Row>

            <Row label="Show agent thinking tokens" hint="Stream tokens as they arrive. Noisy with 6 agents.">
              <Switch.Root
                checked={s.showAgentThinking}
                onCheckedChange={s.setShowAgentThinking}
                className="w-9 h-5 rounded-full bg-[hsl(var(--muted))] data-[state=checked]:bg-rose-500 transition"
              >
                <Switch.Thumb className="block w-4 h-4 bg-white rounded-full shadow translate-x-0.5 data-[state=checked]:translate-x-[18px] transition-transform" />
              </Switch.Root>
            </Row>

            <Row label={`Convergence threshold: ${s.convergenceThreshold.toFixed(2)}`}
                 hint="Min top-Dx probability before team agreement fires.">
              <Slider.Root
                value={[s.convergenceThreshold]}
                onValueChange={([v]) => s.setConvergenceThreshold(v)}
                min={0.5} max={0.95} step={0.01}
                className="relative flex items-center w-full h-5"
              >
                <Slider.Track className="bg-[hsl(var(--muted))] relative grow rounded-full h-1">
                  <Slider.Range className="absolute bg-rose-500 rounded-full h-full" />
                </Slider.Track>
                <Slider.Thumb className="block w-4 h-4 bg-white border-2 border-rose-500 rounded-full shadow focus:outline-none" />
              </Slider.Root>
            </Row>

            <Row label={`Max rounds: ${s.maxRounds}`}>
              <Slider.Root
                value={[s.maxRounds]}
                onValueChange={([v]) => s.setMaxRounds(v)}
                min={3} max={12} step={1}
                className="relative flex items-center w-full h-5"
              >
                <Slider.Track className="bg-[hsl(var(--muted))] relative grow rounded-full h-1">
                  <Slider.Range className="absolute bg-rose-500 rounded-full h-full" />
                </Slider.Track>
                <Slider.Thumb className="block w-4 h-4 bg-white border-2 border-rose-500 rounded-full shadow focus:outline-none" />
              </Slider.Root>
            </Row>

            <Row label="API endpoint" hint="Points the frontend at your FastAPI server.">
              <input
                value={s.apiBaseUrl}
                onChange={(e) => s.setApiBaseUrl(e.target.value)}
                className="w-full px-2 py-1.5 text-xs font-mono bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30"
              />
            </Row>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

function Row({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <div className="space-y-1.5">
      <label className="text-xs font-medium text-[hsl(var(--foreground))]">{label}</label>
      {hint && <p className="text-[11px] text-[hsl(var(--muted-foreground))]">{hint}</p>}
      <div className="pt-1">{children}</div>
    </div>
  );
}
