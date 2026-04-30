"use client";

import Link from "next/link";
import { Activity, Settings as SettingsIcon, Sun, Moon, Monitor } from "lucide-react";
import { useCaseStore } from "@/lib/stores/caseStore";
import { useSettingsStore, type Theme } from "@/lib/stores/settingsStore";
import { ConnectionStatusPill } from "./ConnectionStatusPill";
import { useState } from "react";
import { SettingsDrawer } from "./SettingsDrawer";

export function Header() {
  const caseId = useCaseStore((s) => s.caseId);
  const status = useCaseStore((s) => s.status);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const theme = useSettingsStore((s) => s.theme);
  const setTheme = useSettingsStore((s) => s.setTheme);

  const cycleTheme = () => {
    const next: Record<Theme, Theme> = { light: "dark", dark: "system", system: "light" };
    setTheme(next[theme]);
  };

  const ThemeIcon = theme === "dark" ? Moon : theme === "light" ? Sun : Monitor;

  return (
    <header className="sticky top-0 z-30 bg-background/80 backdrop-blur-md border-b border-[hsl(var(--border))]">
      <div className="max-w-7xl mx-auto px-4 h-14 flex items-center gap-4">
        <Link href="/" className="flex items-center gap-2 font-semibold">
          <span className="grid place-items-center w-7 h-7 rounded-md bg-rose-600 text-white text-xs font-bold">
            DH
          </span>
          <span className="hidden sm:inline">Dr. Holmes</span>
        </Link>

        <nav className="hidden md:flex items-center gap-4 text-sm text-[hsl(var(--muted-foreground))]">
          <Link href="/" className="hover:text-[hsl(var(--foreground))] transition">Cases</Link>
          <Link href="/eval" className="hover:text-[hsl(var(--foreground))] transition">Eval</Link>
          <Link href="/disclaimer" className="hover:text-[hsl(var(--foreground))] transition">Disclaimer</Link>
        </nav>

        {caseId && (
          <div className="hidden md:flex items-center gap-3 text-xs tabular text-[hsl(var(--muted-foreground))]">
            <Activity size={14} />
            <span>case <span className="text-[hsl(var(--foreground))]">{caseId.slice(-12)}</span></span>
            <span className="opacity-50">•</span>
            <span className="smallcaps">{status}</span>
          </div>
        )}

        <div className="ml-auto flex items-center gap-2">
          <ConnectionStatusPill />
          <button
            onClick={cycleTheme}
            className="p-1.5 rounded-md hover:bg-[hsl(var(--muted))] transition"
            aria-label="Toggle theme"
          >
            <ThemeIcon size={16} />
          </button>
          <button
            onClick={() => setSettingsOpen(true)}
            className="p-1.5 rounded-md hover:bg-[hsl(var(--muted))] transition"
            aria-label="Settings"
          >
            <SettingsIcon size={16} />
          </button>
        </div>
      </div>
      <SettingsDrawer open={settingsOpen} onClose={() => setSettingsOpen(false)} />
    </header>
  );
}
