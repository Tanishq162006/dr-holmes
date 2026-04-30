"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { X } from "lucide-react";

export function DialogShell({
  open, onClose, title, children,
}: {
  open: boolean;
  onClose: () => void;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(o) => !o && onClose()}>
      <Dialog.Portal>
        <Dialog.Overlay className="fixed inset-0 bg-black/50 backdrop-blur-sm z-40" />
        <Dialog.Content className="fixed left-1/2 top-1/2 -translate-x-1/2 -translate-y-1/2 z-50 w-[92vw] max-w-md bg-[hsl(var(--card))] border border-[hsl(var(--border))] rounded-xl p-5 shadow-2xl focus:outline-none">
          <header className="flex items-center justify-between mb-4">
            <Dialog.Title className="font-semibold">{title}</Dialog.Title>
            <button onClick={onClose} className="p-1 rounded hover:bg-[hsl(var(--muted))]">
              <X size={16} />
            </button>
          </header>
          {children}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function PrimaryButton({
  children, onClick, disabled,
}: {
  children: React.ReactNode;
  onClick: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      onClick={onClick}
      disabled={disabled}
      className="w-full py-2 rounded-md bg-rose-600 hover:bg-rose-700 disabled:opacity-50 text-white text-sm font-medium transition"
    >
      {children}
    </button>
  );
}

export function FieldLabel({ children }: { children: React.ReactNode }) {
  return <label className="text-xs font-medium block mb-1">{children}</label>;
}

export function TextInput(props: React.InputHTMLAttributes<HTMLInputElement>) {
  return (
    <input
      {...props}
      className="w-full px-3 py-2 text-sm bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30"
    />
  );
}

export function TextArea(props: React.TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return (
    <textarea
      {...props}
      className="w-full px-3 py-2 text-sm bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30 resize-none"
    />
  );
}

export function Select({ children, ...props }: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      {...props}
      className="w-full px-3 py-2 text-sm bg-[hsl(var(--muted))] rounded border border-[hsl(var(--border))] focus:outline-none focus:ring-2 focus:ring-rose-500/30"
    >
      {children}
    </select>
  );
}
