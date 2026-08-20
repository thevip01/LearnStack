"""UI schema: the subject describes its own workspace.

The frontend ships a registry of panel components and a small number of layouts.
A subject package chooses which panels appear, in which slot, for which learning
mode. That is the whole mechanism by which Python, AWS and trading become
different-looking applications on one runtime.

Panel ``type`` values must exist in the frontend component registry. Validation
against that registry happens at publish time, not render time, so a bad package
fails in CI rather than as a blank pane in front of a learner.
"""

from __future__ import annotations

from enum import Enum
from typing import Literal

from pydantic import Field, model_validator

from .common import Id, LearningMode, SchemaModel


class PanelType(str, Enum):
    """Mirror of the frontend component registry.

    Adding a value here without adding the component is a publish-time error.
    """

    CURRICULUM = "curriculum"
    CONTENT = "content"
    CONCEPT_META = "concept_meta"
    INSTRUCTIONS = "instructions"
    CODE_EDITOR = "code_editor"
    FILE_EXPLORER = "file_explorer"
    CONSOLE = "console"
    TERMINAL = "terminal"
    TEST_RESULTS = "test_results"
    QUIZ = "quiz"
    FLASHCARDS = "flashcards"
    DIAGRAM = "diagram"
    ARCHITECTURE_CANVAS = "architecture_canvas"
    CLOUD_TOPOLOGY = "cloud_topology"
    SQL_CONSOLE = "sql_console"
    NOTEBOOK = "notebook"
    DATASET_VIEWER = "dataset_viewer"
    METRICS = "metrics"
    CHART = "chart"
    TRADING_CHART = "trading_chart"
    BROWSER_PREVIEW = "browser_preview"
    API_CLIENT = "api_client"
    HTTP_INSPECTOR = "http_inspector"
    SIMULATION_CANVAS = "simulation_canvas"
    INCIDENT_CONSOLE = "incident_console"
    TUTOR = "tutor"
    HINTS = "hints"
    MASTERY = "mastery"
    PROJECT_BRIEF = "project_brief"
    SOURCES = "sources"


Slot = Literal["left", "main", "right", "bottom"]


class Panel(SchemaModel):
    id: str = Field(description="Unique within the mode. Used as the tab key when a slot holds several panels.")
    type: PanelType
    slot: Slot = "main"
    title: str | None = None
    config: dict = Field(default_factory=dict, description="Passed through to the component untouched.")
    collapsible: bool = True
    default_collapsed: bool = False
    min_width: int | None = None
    min_height: int | None = None
    flex: float = Field(default=1.0, gt=0.0, description="Share of the slot when several panels stack in it.")


class ModeLayout(SchemaModel):
    label: str | None = None
    panels: list[Panel] = Field(min_length=1)
    primary_slot: Slot = "main"

    @model_validator(mode="after")
    def _unique_panel_ids(self) -> "ModeLayout":
        ids = [p.id for p in self.panels]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate panel ids in layout: {ids}")
        return self


class ThemeSpec(SchemaModel):
    accent: str = Field(default="#6366f1", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_soft: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    icon: str | None = Field(default=None, description="Icon key resolved by the frontend, not a URL.")
    mono_font: str | None = None
    density: Literal["comfortable", "compact"] = "comfortable"


class UISchema(SchemaModel):
    layout: Literal["learning_lab", "ml_workbench", "trading_desk", "reader", "canvas"] = "learning_lab"
    theme: ThemeSpec = Field(default_factory=ThemeSpec)
    modes: dict[LearningMode, ModeLayout] = Field(min_length=1)
    default_mode: LearningMode = LearningMode.LEARN
    global_panels: list[Panel] = Field(
        default_factory=list, description="Present in every mode, e.g. the tutor. Merged into each layout."
    )

    @model_validator(mode="after")
    def _default_mode_present(self) -> "UISchema":
        if self.default_mode not in self.modes:
            raise ValueError(f"default_mode {self.default_mode!r} has no layout defined")
        return self

    def layout_for(self, mode: LearningMode) -> ModeLayout:
        base = self.modes[mode]
        if not self.global_panels:
            return base
        existing = {p.id for p in base.panels}
        extra = [p for p in self.global_panels if p.id not in existing]
        return base.model_copy(update={"panels": base.panels + extra})


class NavigationItem(SchemaModel):
    """Flattened navigation, precomputed server-side.

    The sidebar should never have to walk the curriculum to work out what to
    draw, because the same flattening then has to be reimplemented for search,
    breadcrumbs and next/previous.
    """

    id: Id
    title: str
    kind: Literal["track", "module", "concept", "project", "assessment", "lab"]
    depth: int = Field(ge=0, le=4)
    parent_id: Id | None = None
    icon: str | None = None
    estimated_minutes: int | None = None
    skills: list[Id] = Field(default_factory=list)
