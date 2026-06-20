"use client";

import type { PanelType } from "@/lib/types";
import { ApiClientPanel } from "@/components/panels/ApiClientPanel";
import { ArchitectureCanvasPanel } from "@/components/panels/ArchitectureCanvasPanel";
import { BrowserPreviewPanel } from "@/components/panels/BrowserPreviewPanel";
import { ChartPanel } from "@/components/panels/ChartPanel";
import { CloudTopologyPanel } from "@/components/panels/CloudTopologyPanel";
import { CodeEditorPanel } from "@/components/panels/CodeEditorPanel";
import { ConceptMetaPanel } from "@/components/panels/ConceptMetaPanel";
import { ConsolePanel } from "@/components/panels/ConsolePanel";
import { ContentPanel } from "@/components/panels/ContentPanel";
import { CurriculumPanel } from "@/components/panels/CurriculumPanel";
import { DatasetViewerPanel } from "@/components/panels/DatasetViewerPanel";
import { DiagramPanel } from "@/components/panels/DiagramPanel";
import { FileExplorerPanel } from "@/components/panels/FileExplorerPanel";
import { FlashcardsPanel } from "@/components/panels/FlashcardsPanel";
import { HintsPanel } from "@/components/panels/HintsPanel";
import { HttpInspectorPanel } from "@/components/panels/HttpInspectorPanel";
import { IncidentConsolePanel } from "@/components/panels/IncidentConsolePanel";
import { InstructionsPanel } from "@/components/panels/InstructionsPanel";
import { MasteryPanel } from "@/components/panels/MasteryPanel";
import { MetricsPanel } from "@/components/panels/MetricsPanel";
import { NotebookPanel } from "@/components/panels/NotebookPanel";
import { ProjectBriefPanel } from "@/components/panels/ProjectBriefPanel";
import { QuizPanel } from "@/components/panels/QuizPanel";
import { SimulationCanvasPanel } from "@/components/panels/SimulationCanvasPanel";
import { SourcesPanel } from "@/components/panels/SourcesPanel";
import { SqlConsolePanel } from "@/components/panels/SqlConsolePanel";
import { TerminalPanel } from "@/components/panels/TerminalPanel";
import { TestResultsPanel } from "@/components/panels/TestResultsPanel";
import { TradingChartPanel } from "@/components/panels/TradingChartPanel";
import { TutorPanel } from "@/components/panels/TutorPanel";
import type { PanelComponent } from "./types";

/**
 * The registry named by `learnos_schema.ui.PanelType`.
 *
 * This is the single lookup that turns a subject package into an application.
 * Every enum value in ui.py has exactly one entry here and the map is exhaustive
 * by type, so adding a value to the Python enum without adding a component is a
 * TypeScript error rather than a blank pane in front of a learner.
 *
 * There is no branch anywhere in this file on subject, provider or domain. If a
 * new subject cannot express itself with these thirty components, the fix is a
 * thirty-first component plus a new `PanelType`, never a conditional.
 */
export const PANEL_REGISTRY: Record<PanelType, PanelComponent> = {
  curriculum: CurriculumPanel,
  content: ContentPanel,
  concept_meta: ConceptMetaPanel,
  instructions: InstructionsPanel,
  code_editor: CodeEditorPanel,
  file_explorer: FileExplorerPanel,
  console: ConsolePanel,
  terminal: TerminalPanel,
  test_results: TestResultsPanel,
  quiz: QuizPanel,
  flashcards: FlashcardsPanel,
  diagram: DiagramPanel,
  architecture_canvas: ArchitectureCanvasPanel,
  cloud_topology: CloudTopologyPanel,
  sql_console: SqlConsolePanel,
  notebook: NotebookPanel,
  dataset_viewer: DatasetViewerPanel,
  metrics: MetricsPanel,
  chart: ChartPanel,
  trading_chart: TradingChartPanel,
  browser_preview: BrowserPreviewPanel,
  api_client: ApiClientPanel,
  http_inspector: HttpInspectorPanel,
  simulation_canvas: SimulationCanvasPanel,
  incident_console: IncidentConsolePanel,
  tutor: TutorPanel,
  hints: HintsPanel,
  mastery: MasteryPanel,
  project_brief: ProjectBriefPanel,
  sources: SourcesPanel,
};

/** Fallback tab/header label when a package leaves `panel.title` null. */
export const PANEL_LABELS: Record<PanelType, string> = {
  curriculum: "Curriculum",
  content: "Lesson",
  concept_meta: "Concept",
  instructions: "Instructions",
  code_editor: "Editor",
  file_explorer: "Files",
  console: "Console",
  terminal: "Terminal",
  test_results: "Tests",
  quiz: "Quiz",
  flashcards: "Flashcards",
  diagram: "Diagram",
  architecture_canvas: "Architecture",
  cloud_topology: "Topology",
  sql_console: "SQL",
  notebook: "Notebook",
  dataset_viewer: "Dataset",
  metrics: "Metrics",
  chart: "Chart",
  trading_chart: "Market",
  browser_preview: "Preview",
  api_client: "API client",
  http_inspector: "HTTP inspector",
  simulation_canvas: "Simulation",
  incident_console: "Incident",
  tutor: "Tutor",
  hints: "Hints",
  mastery: "Mastery",
  project_brief: "Brief",
  sources: "Sources",
};

export function panelLabel(panel: { type: PanelType; title: string | null }): string {
  return panel.title ?? PANEL_LABELS[panel.type] ?? panel.type;
}

export function lookupPanel(type: PanelType): PanelComponent | null {
  return PANEL_REGISTRY[type] ?? null;
}
