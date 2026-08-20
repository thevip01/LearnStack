"use client";

import { useId, useRef, type KeyboardEvent, type ReactNode } from "react";
import { cn } from "@/lib/utils";

export type TabItem = { id: string; label: ReactNode; badge?: ReactNode; disabled?: boolean };

/**
 * Roving-tabindex tablist. Arrow keys move, Home/End jump — required because a
 * slot holding several panels is navigated entirely from the keyboard.
 */
export function Tabs({
  items,
  active,
  onChange,
  className,
  size = "sm",
  label,
  idPrefix,
}: {
  items: TabItem[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
  size?: "xs" | "sm";
  label: string;
  /** Supply when the caller renders its own tabpanels and needs `aria-controls` to resolve. */
  idPrefix?: string;
}) {
  const generatedId = useId();
  const baseId = idPrefix ?? generatedId;
  const listRef = useRef<HTMLDivElement>(null);

  function onKeyDown(event: KeyboardEvent<HTMLDivElement>) {
    const enabled = items.filter((item) => !item.disabled);
    const index = enabled.findIndex((item) => item.id === active);
    if (index < 0) return;
    let nextIndex: number | null = null;
    if (event.key === "ArrowRight" || event.key === "ArrowDown") nextIndex = (index + 1) % enabled.length;
    if (event.key === "ArrowLeft" || event.key === "ArrowUp") nextIndex = (index - 1 + enabled.length) % enabled.length;
    if (event.key === "Home") nextIndex = 0;
    if (event.key === "End") nextIndex = enabled.length - 1;
    if (nextIndex === null) return;
    event.preventDefault();
    const target = enabled[nextIndex];
    if (!target) return;
    onChange(target.id);
    listRef.current?.querySelector<HTMLButtonElement>(`#${CSS.escape(`${baseId}-${target.id}`)}`)?.focus();
  }

  return (
    <div
      ref={listRef}
      role="tablist"
      aria-label={label}
      onKeyDown={onKeyDown}
      className={cn("flex min-w-0 items-stretch gap-0.5 overflow-x-auto", className)}
    >
      {items.map((item) => {
        const selected = item.id === active;
        return (
          <button
            key={item.id}
            id={`${baseId}-${item.id}`}
            role="tab"
            type="button"
            aria-selected={selected}
            aria-controls={`${baseId}-${item.id}-panel`}
            tabIndex={selected ? 0 : -1}
            disabled={item.disabled}
            onClick={() => onChange(item.id)}
            className={cn(
              "inline-flex items-center gap-1.5 whitespace-nowrap border-b-2 font-medium transition-colors",
              size === "xs" ? "px-2 py-1 text-2xs" : "px-2.5 py-1.5 text-xs",
              selected
                ? "border-accent text-ink"
                : "border-transparent text-faint hover:border-line-strong hover:text-muted",
              item.disabled && "cursor-not-allowed opacity-40",
            )}
          >
            {item.label}
            {item.badge}
          </button>
        );
      })}
    </div>
  );
}

/** Matches the `aria-controls` value Tabs emits for an item. */
export function tabPanelId(idPrefix: string, itemId: string): string {
  return `${idPrefix}-${itemId}-panel`;
}

export function TabPanel({
  id,
  active,
  children,
  className,
}: {
  id: string;
  active: string;
  children: ReactNode;
  className?: string;
}) {
  const hidden = id !== active;
  return (
    <div role="tabpanel" hidden={hidden} aria-hidden={hidden} className={cn(hidden && "hidden", className)}>
      {children}
    </div>
  );
}
