"use client";

import { AlertOctagon } from "lucide-react";
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/Button";

/**
 * One boundary per panel.
 *
 * A workspace draws six or seven independent panels from an authored layout.
 * Without a boundary here, a single malformed diagram or an unexpected null in
 * one panel's payload unmounts the whole workspace, including the editor holding
 * the learner's unsaved work. Isolating the failure keeps the rest of the
 * workspace usable and names the panel that broke.
 */
type Props = { panelId: string; panelType: string; children: ReactNode };
type State = { error: Error | null };

export class PanelErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Console only, and only the panel identity plus the message. Practice
    // payloads are sanitised upstream but must not be logged anywhere a learner
    // can read them, so the component stack is all we keep.
    console.error(`[panel ${this.props.panelId}:${this.props.panelType}] ${error.message}`, info.componentStack);
  }

  private reset = () => this.setState({ error: null });

  render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="panel-scroll p-pad">
        <div className="rounded-panel border border-danger/40 bg-danger/5 p-pad">
          <div className="flex items-center gap-2 text-xs font-semibold text-danger">
            <AlertOctagon className="size-3.5" aria-hidden />
            Panel failed
          </div>
          <p className="mt-1.5 text-2xs leading-relaxed text-muted">
            <span className="font-mono text-ink">{this.props.panelId}</span> ({this.props.panelType}) stopped
            rendering. The rest of the workspace is unaffected.
          </p>
          <pre className="mt-2 max-h-32 overflow-auto whitespace-pre-wrap rounded border border-line bg-canvas p-2 font-mono text-2xs text-muted">
            {error.message}
          </pre>
          <Button className="mt-2" size="xs" variant="outline" onClick={this.reset}>
            Retry panel
          </Button>
        </div>
      </div>
    );
  }
}
