"""Structured content blocks.

Concept bodies are a list of typed blocks rather than a markdown blob. That is a
deliberate constraint: typed blocks are what let the same concept render as a
lesson, collapse into a flashcard, feed a diagram panel, or become the retrieval
unit for the tutor. A markdown blob can only ever be displayed.
"""

from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import Field

from .common import Id, RuntimeKind, SchemaModel, SourceRef


class ProseBlock(SchemaModel):
    type: Literal["prose"] = "prose"
    md: str = Field(description="Markdown. Inline code and links allowed, no raw HTML.")
    sources: list[SourceRef] = Field(default_factory=list)


class CodeBlock(SchemaModel):
    type: Literal["code"] = "code"
    runtime: RuntimeKind = RuntimeKind.PYTHON
    language: str | None = Field(default=None, description="Highlighting hint; defaults from runtime.")
    code: str
    caption: str | None = None
    runnable: bool = Field(
        default=False,
        description="If true the UI offers a Run button that submits this to the execution service.",
    )
    expected_output: str | None = Field(
        default=None, description="Shown alongside, and used to smoke-test the block in CI."
    )
    highlight_lines: list[int] = Field(default_factory=list)


class CalloutBlock(SchemaModel):
    type: Literal["callout"] = "callout"
    variant: Literal["note", "tip", "warning", "danger", "production"] = "note"
    title: str | None = None
    md: str


class DiagramBlock(SchemaModel):
    type: Literal["diagram"] = "diagram"
    format: Literal["mermaid", "ascii", "topology"] = "mermaid"
    source: str = Field(description="Mermaid source, ASCII art, or a topology JSON string.")
    caption: str | None = None
    interactive: bool = Field(
        default=False, description="Topology diagrams can be made clickable to drive an architecture panel."
    )


class TableBlock(SchemaModel):
    type: Literal["table"] = "table"
    columns: list[str]
    rows: list[list[str]]
    caption: str | None = None


class StepsBlock(SchemaModel):
    type: Literal["steps"] = "steps"
    title: str | None = None
    steps: list[str] = Field(description="Ordered procedure. Each entry is markdown.")


class CommandBlock(SchemaModel):
    type: Literal["command"] = "command"
    shell: Literal["bash", "powershell", "sql"] = "bash"
    commands: list[str]
    caption: str | None = None
    copyable: bool = True


class TermBlock(SchemaModel):
    type: Literal["term"] = "term"
    term: str
    definition_md: str
    aliases: list[str] = Field(default_factory=list)


class EmbedPracticeBlock(SchemaModel):
    """Drops a practice task inline in the middle of a lesson.

    This is how the platform avoids the read-then-quiz split: a check for
    understanding can sit directly under the paragraph it tests.
    """

    type: Literal["embed_practice"] = "embed_practice"
    practice_id: Id


ContentBlock = Annotated[
    Union[
        ProseBlock,
        CodeBlock,
        CalloutBlock,
        DiagramBlock,
        TableBlock,
        StepsBlock,
        CommandBlock,
        TermBlock,
        EmbedPracticeBlock,
    ],
    Field(discriminator="type"),
]
