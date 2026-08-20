"use client";

import { createContext, useCallback, useContext, useMemo, useState, type ReactNode } from "react";
import { cn } from "@/lib/utils";

type ToastTone = "info" | "ok" | "error";
type Toast = { id: string; title: string; message?: string; tone: ToastTone };

type ToastApi = { push: (toast: Omit<Toast, "id">) => void };

const ToastContext = createContext<ToastApi | null>(null);

const TONES: Record<ToastTone, { border: string; glyph: string }> = {
  info: { border: "border-info/50", glyph: "i" },
  ok: { border: "border-ok/50", glyph: "✔" },
  error: { border: "border-danger/50", glyph: "!" },
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);

  const push = useCallback((toast: Omit<Toast, "id">) => {
    const id = `${Date.now()}-${Math.random().toString(36).slice(2, 7)}`;
    setToasts((current) => [...current, { ...toast, id }].slice(-4));
    setTimeout(() => setToasts((current) => current.filter((entry) => entry.id !== id)), 6000);
  }, []);

  const api = useMemo(() => ({ push }), [push]);

  return (
    <ToastContext.Provider value={api}>
      {children}
      {/* aria-live so a submission result is announced, not only drawn. */}
      <div
        aria-live="polite"
        aria-atomic="false"
        className="pointer-events-none fixed bottom-4 right-4 z-50 flex w-80 flex-col gap-2"
      >
        {toasts.map((toast) => (
          <div
            key={toast.id}
            className={cn(
              "pointer-events-auto animate-slide-up rounded-panel border bg-surface/95 p-3 shadow-panel backdrop-blur",
              TONES[toast.tone].border,
            )}
          >
            <div className="flex items-start gap-2">
              <span aria-hidden className="mt-0.5 font-mono text-2xs text-muted">
                {TONES[toast.tone].glyph}
              </span>
              <div className="min-w-0">
                <div className="text-xs font-semibold text-ink">{toast.title}</div>
                {toast.message ? <div className="mt-0.5 break-words text-2xs text-muted">{toast.message}</div> : null}
              </div>
            </div>
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

/** No-ops outside a provider so a panel rendered in isolation cannot crash. */
export function useToast(): ToastApi {
  return useContext(ToastContext) ?? { push: () => undefined };
}
