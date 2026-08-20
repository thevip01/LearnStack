"use client";

import {
  useCallback,
  useRef,
  type KeyboardEvent,
  type PointerEvent as ReactPointerEvent,
  type ReactNode,
} from "react";
import { cn } from "@/lib/utils";

type Orientation = "vertical" | "horizontal";

/**
 * Two panes and a draggable separator. `pane` is the one with an explicit pixel
 * size; the other pane flexes. Pointer capture plus arrow-key stepping means the
 * layout is resizable without a mouse, which matters because these sidebars hold
 * the curriculum tree.
 */
export function Split({
  orientation,
  size,
  min = 160,
  max = 720,
  step = 24,
  onResize,
  invert = false,
  pane,
  children,
  label,
}: {
  orientation: Orientation;
  size: number;
  min?: number;
  max?: number;
  step?: number;
  onResize: (px: number) => void;
  /** true when the sized pane sits after the handle (right sidebar). */
  invert?: boolean;
  pane: ReactNode;
  children: ReactNode;
  label: string;
}) {
  const dragging = useRef<{ origin: number; start: number } | null>(null);
  const vertical = orientation === "vertical";

  const clamp = useCallback((value: number) => Math.min(Math.max(value, min), max), [max, min]);

  const onPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    event.currentTarget.setPointerCapture(event.pointerId);
    dragging.current = { origin: vertical ? event.clientX : event.clientY, start: size };
  };

  const onPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const state = dragging.current;
    if (!state) return;
    const delta = (vertical ? event.clientX : event.clientY) - state.origin;
    onResize(clamp(state.start + (invert ? -delta : delta)));
  };

  const onPointerUp = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
    dragging.current = null;
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const decrease = vertical ? "ArrowLeft" : "ArrowUp";
    const increase = vertical ? "ArrowRight" : "ArrowDown";
    if (event.key !== decrease && event.key !== increase) return;
    event.preventDefault();
    const direction = event.key === increase ? 1 : -1;
    onResize(clamp(size + direction * step * (invert ? -1 : 1)));
  };

  const sizedStyle = vertical ? { width: size, minWidth: size } : { height: size, minHeight: size };

  const handle = (
    <div
      role="separator"
      aria-orientation={vertical ? "vertical" : "horizontal"}
      aria-label={label}
      aria-valuenow={Math.round(size)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onKeyDown={onKeyDown}
      className={cn(
        "group relative shrink-0 bg-line transition-colors hover:bg-accent/60 focus-visible:bg-accent",
        vertical ? "w-px cursor-col-resize" : "h-px cursor-row-resize",
      )}
    >
      {/* Widen the hit area without widening the visual line. */}
      <span
        aria-hidden
        className={cn("absolute", vertical ? "-inset-x-1 inset-y-0" : "-inset-y-1 inset-x-0")}
      />
    </div>
  );

  const sized = (
    <div className={cn("flex min-h-0 min-w-0 overflow-hidden")} style={sizedStyle}>
      {pane}
    </div>
  );

  return (
    <div className={cn("flex min-h-0 min-w-0 flex-1", vertical ? "flex-row" : "flex-col")}>
      {invert ? null : sized}
      {invert ? null : handle}
      <div className="flex min-h-0 min-w-0 flex-1 overflow-hidden">{children}</div>
      {invert ? handle : null}
      {invert ? sized : null}
    </div>
  );
}
