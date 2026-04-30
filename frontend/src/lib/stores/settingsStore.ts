/**
 * User settings — persisted to localStorage. Safe to persist (no PHI).
 */
import { create } from "zustand";
import { persist } from "zustand/middleware";

export type LLMMode = "live" | "mock";
export type Theme = "light" | "dark" | "system";

interface SettingsState {
  llmMode: LLMMode;
  showAgentThinking: boolean;
  convergenceThreshold: number;
  maxRounds: number;
  theme: Theme;
  apiBaseUrl: string;
  hasSeenDisclaimer: boolean;

  setLLMMode: (m: LLMMode) => void;
  setShowAgentThinking: (b: boolean) => void;
  setConvergenceThreshold: (n: number) => void;
  setMaxRounds: (n: number) => void;
  setTheme: (t: Theme) => void;
  setApiBaseUrl: (s: string) => void;
  setHasSeenDisclaimer: (b: boolean) => void;
}

const DEFAULT_API = typeof window !== "undefined"
  ? (process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000")
  : "http://localhost:8000";

export const useSettingsStore = create<SettingsState>()(
  persist(
    (set) => ({
      llmMode: "mock",
      showAgentThinking: false,
      convergenceThreshold: 0.8,
      maxRounds: 6,
      theme: "system",
      apiBaseUrl: DEFAULT_API,
      hasSeenDisclaimer: false,
      setLLMMode: (m) => set({ llmMode: m }),
      setShowAgentThinking: (b) => set({ showAgentThinking: b }),
      setConvergenceThreshold: (n) => set({ convergenceThreshold: n }),
      setMaxRounds: (n) => set({ maxRounds: n }),
      setTheme: (t) => set({ theme: t }),
      setApiBaseUrl: (s) => set({ apiBaseUrl: s }),
      setHasSeenDisclaimer: (b) => set({ hasSeenDisclaimer: b }),
    }),
    { name: "dr-holmes-settings", version: 1 },
  ),
);
