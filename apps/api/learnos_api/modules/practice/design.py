"""Grading for the two design-judgement task kinds: architecture and incident.

Both are graded structurally and deterministically. Neither calls an LLM, and
that is a deliberate constraint rather than a shortcut: a learner is entitled to
know why a design was marked wrong, and "a model thought so" is not an answer they
can act on.

**Architecture** is scored against a vocabulary of generic graph properties. The
property names live in this module, not in any subject package, which is what
keeps ``target_properties: ["no_direct:internet:database"]`` meaningful for AWS,
Kubernetes and a database course alike. A property this module does not recognise
is reported as ungradable and excluded from the denominator, never silently
passed, because a typo in a package would otherwise hand out free marks.

**Incident** is scored on three things a real diagnosis is scored on: did you do
the right thing, did you look at the right telemetry to decide, and can you say
what actually broke. The root-cause component is skipped rather than zeroed when
the learner does not submit one, for the same reason an unmeasured mastery
dimension is not a zero.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from typing import Iterable, Mapping, Sequence

from learnos_schema import ArchitectureNode, ArchitectureTask, IncidentTask

from .results import GradeOutcome, decide, weighted_fraction

# ---------------------------------------------------------------------------
# Architecture
# ---------------------------------------------------------------------------

#: Weight of "you placed the right components" against "the design holds".
COMPONENT_WEIGHT = 1.0
PROPERTY_WEIGHT = 2.0


class Graph:
    """Adjacency over an architecture submission, indexed by node type."""

    def __init__(self, nodes: Sequence[ArchitectureNode], edges: Sequence[Sequence[str]]) -> None:
        self.nodes = {node.id: node for node in nodes}
        self.types: dict[str, str] = {node.id: str(node.type).strip().lower() for node in nodes}
        self.out: dict[str, set[str]] = defaultdict(set)
        self.inbound: dict[str, set[str]] = defaultdict(set)
        for edge in edges:
            if len(edge) != 2:
                continue
            source, target = str(edge[0]), str(edge[1])
            if source not in self.nodes or target not in self.nodes:
                continue
            self.out[source].add(target)
            self.inbound[target].add(source)

    def ids_of_type(self, type_name: str) -> list[str]:
        wanted = type_name.strip().lower()
        return [node_id for node_id, kind in self.types.items() if kind == wanted]

    def type_counts(self) -> Counter[str]:
        return Counter(self.types.values())

    def reachable(self, start: str) -> set[str]:
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            for neighbour in self.out.get(current, ()):
                if neighbour not in seen:
                    seen.add(neighbour)
                    stack.append(neighbour)
        return seen

    def has_cycle(self) -> bool:
        WHITE, GREY, BLACK = 0, 1, 2
        colour = {node_id: WHITE for node_id in self.nodes}

        def visit(node_id: str) -> bool:
            colour[node_id] = GREY
            for neighbour in self.out.get(node_id, ()):
                if colour.get(neighbour) == GREY:
                    return True
                if colour.get(neighbour) == WHITE and visit(neighbour):
                    return True
            colour[node_id] = BLACK
            return False

        return any(colour[node_id] == WHITE and visit(node_id) for node_id in list(self.nodes))


def _describe(name: str) -> str:
    """Human wording for a property id, used in feedback."""
    parts = name.split(":")
    head = parts[0]
    if head == "requires" and len(parts) >= 2:
        return f"includes a {parts[1]}"
    if head in {"min_count", "max_count"} and len(parts) >= 3:
        word = "at least" if head == "min_count" else "at most"
        return f"has {word} {parts[2]} × {parts[1]}"
    if head in {"no_direct", "not_adjacent"} and len(parts) >= 3:
        return f"no direct link between {parts[1]} and {parts[2]}"
    if head == "path" and len(parts) >= 3:
        return f"traffic can reach {parts[2]} from {parts[1]}"
    if head == "behind" and len(parts) >= 3:
        return f"every {parts[1]} sits behind a {parts[2]}"
    return {
        "no_orphans": "every component is connected to something",
        "no_cycles": "no circular dependencies",
        "single_entry": "exactly one entry point",
    }.get(head, name)


def check_property(name: str, graph: Graph) -> bool | None:
    """Evaluate one property. ``None`` means "this module does not know it"."""
    parts = [part.strip().lower() for part in name.split(":")]
    head = parts[0]

    if head == "requires" and len(parts) >= 2:
        return bool(graph.ids_of_type(parts[1]))

    if head in {"min_count", "max_count"} and len(parts) >= 3:
        try:
            bound = int(parts[2])
        except ValueError:
            return None
        count = len(graph.ids_of_type(parts[1]))
        return count >= bound if head == "min_count" else count <= bound

    if head in {"no_direct", "not_adjacent"} and len(parts) >= 3:
        left = set(graph.ids_of_type(parts[1]))
        right = set(graph.ids_of_type(parts[2]))
        for source in left:
            if graph.out.get(source, set()) & right:
                return False
        if head == "not_adjacent":
            for source in right:
                if graph.out.get(source, set()) & left:
                    return False
        return True

    if head == "path" and len(parts) >= 3:
        targets = set(graph.ids_of_type(parts[2]))
        if not targets:
            return False
        return any(graph.reachable(source) & targets for source in graph.ids_of_type(parts[1]))

    if head == "behind" and len(parts) >= 3:
        # Every node of type parts[1] must have every inbound edge come from
        # parts[2]: "the database is only reachable through the app tier".
        gate = set(graph.ids_of_type(parts[2]))
        protected = graph.ids_of_type(parts[1])
        if not protected:
            return False
        return all(graph.inbound.get(node_id, set()) <= gate for node_id in protected)

    if head == "no_orphans":
        return all(
            bool(graph.out.get(node_id)) or bool(graph.inbound.get(node_id)) for node_id in graph.nodes
        ) and bool(graph.nodes)

    if head == "no_cycles":
        return not graph.has_cycle()

    if head == "single_entry":
        roots = [node_id for node_id in graph.nodes if not graph.inbound.get(node_id)]
        return len(roots) == 1

    return None


def required_components(task: ArchitectureTask) -> Counter[str]:
    """Component types the reference solution uses, as a multiset."""
    return Counter(str(node.type).strip().lower() for node in task.solution_nodes)


def grade_architecture(
    task: ArchitectureTask,
    nodes: Sequence[ArchitectureNode],
    edges: Sequence[Sequence[str]],
) -> GradeOutcome:
    graph = Graph(nodes, edges)
    checks: list[tuple[bool, float]] = []
    met: list[str] = []
    unmet: list[str] = []
    ungradable: list[str] = []

    required = required_components(task)
    if required:
        placed = graph.type_counts()
        missing = [kind for kind, count in required.items() if placed.get(kind, 0) < count]
        checks.append((not missing, COMPONENT_WEIGHT))
        if missing:
            unmet.append("missing components: " + ", ".join(sorted(missing)))
        else:
            met.append("all required components placed")

    for name in task.target_properties:
        verdict = check_property(name, graph)
        if verdict is None:
            ungradable.append(name)
            continue
        checks.append((verdict, PROPERTY_WEIGHT))
        (met if verdict else unmet).append(_describe(name))

    extra_types = sorted(set(graph.type_counts()) - set(str(kind).strip().lower() for kind in task.palette))

    if not checks:
        return GradeOutcome(
            score=0.0,
            passed=False,
            feedback_md=(
                "This task declares nothing that can be checked automatically, so "
                "the design could not be scored. Please report it."
            ),
            notes=[f"ungradable properties: {ungradable}"],
        )

    fraction = weighted_fraction(checks)
    score, passed = decide(fraction, task.evaluation)

    lines = ["**Design accepted.**" if passed else "**The design does not hold yet.**"]
    if unmet:
        lines += ["", "Not satisfied:"] + [f"- {item}" for item in unmet]
    if met:
        lines += ["", "Satisfied:"] + [f"- {item}" for item in met]
    if extra_types:
        lines += [
            "",
            "Components outside this task's palette were ignored: " + ", ".join(f"`{k}`" for k in extra_types) + ".",
        ]
    if ungradable:
        lines += [
            "",
            "Some of this task's requirements cannot be checked automatically and were left out of the score: "
            + ", ".join(f"`{name}`" for name in ungradable)
            + ".",
        ]

    return GradeOutcome(
        score=score,
        passed=passed,
        feedback_md="\n".join(lines),
        notes=[f"ungradable properties: {ungradable}"] if ungradable else [],
    ).clamped()


# ---------------------------------------------------------------------------
# Incident
# ---------------------------------------------------------------------------

#: How the three components of an incident score are weighted against each other.
REMEDIATION_WEIGHT = 0.6
DIAGNOSIS_WEIGHT = 0.2
ROOT_CAUSE_WEIGHT = 0.2

_WORD_RE = re.compile(r"[a-z0-9_]{4,}")
_STOPWORDS = {
    "that",
    "this",
    "with",
    "from",
    "were",
    "have",
    "been",
    "when",
    "which",
    "would",
    "because",
    "there",
    "their",
    "then",
    "than",
    "into",
    "after",
    "before",
    "cause",
    "caused",
    "issue",
    "problem",
    "root",
    "service",
    "request",
    "requests",
}


def _keywords(text: str) -> set[str]:
    return {word for word in _WORD_RE.findall(text.lower()) if word not in _STOPWORDS}


def jaccard(left: Iterable[str], right: Iterable[str]) -> float:
    """Intersection over union.

    Chosen over recall on purpose: recall alone would score "select every
    remediation" as a perfect diagnosis, which is the exact behaviour production
    mode exists to train out of people.
    """
    left_set, right_set = set(left), set(right)
    if not left_set and not right_set:
        return 1.0
    union = left_set | right_set
    return len(left_set & right_set) / len(union) if union else 0.0


def root_cause_overlap(submitted: str, authored: str) -> float:
    """Keyword overlap between the learner's explanation and the authored one.

    A blunt instrument, and labelled as such in the feedback: it is scored as
    recall over the authored keywords, so a correct-but-terse answer is not
    punished for brevity, and a long answer that never names the mechanism does
    not pass by volume.
    """
    authored_words = _keywords(authored)
    if not authored_words:
        return 1.0
    submitted_words = _keywords(submitted)
    return len(authored_words & submitted_words) / len(authored_words)


def grade_incident(
    task: IncidentTask,
    *,
    inspected: Sequence[str],
    remediations: Sequence[str],
    root_cause: str | None = None,
) -> GradeOutcome:
    signals = {signal.id: signal for signal in task.signals}
    red_herrings = {signal_id for signal_id, signal in signals.items() if signal.is_red_herring}
    useful = {signal_id for signal_id in signals if signal_id not in red_herrings}

    inspected_valid = [signal_id for signal_id in dict.fromkeys(inspected) if signal_id in signals]
    components: list[tuple[float, float]] = []

    remediation_score = jaccard(task.correct_remediations, remediations)
    components.append((remediation_score, REMEDIATION_WEIGHT))

    # Diagnosis: did they look at the telemetry that mattered, without drowning in
    # it. Scored only when the task actually offers signals to look at.
    if signals:
        looked_useful = len([s for s in inspected_valid if s in useful])
        precision = looked_useful / len(inspected_valid) if inspected_valid else 0.0
        coverage = looked_useful / len(useful) if useful else 1.0
        diagnosis_score = (precision + coverage) / 2
        if task.max_inspections and len(inspected_valid) > task.max_inspections:
            diagnosis_score *= 0.5
        components.append((diagnosis_score, DIAGNOSIS_WEIGHT))
    else:
        diagnosis_score = None  # type: ignore[assignment]

    root_cause_score: float | None = None
    if task.root_cause_md and root_cause and root_cause.strip():
        root_cause_score = root_cause_overlap(root_cause, task.root_cause_md)
        components.append((root_cause_score, ROOT_CAUSE_WEIGHT))

    total_weight = sum(weight for _, weight in components)
    fraction = sum(value * weight for value, weight in components) / total_weight if total_weight else 0.0
    score, passed = decide(fraction, task.evaluation)

    chosen = set(remediations)
    correct = set(task.correct_remediations)
    lines = ["**Incident resolved.**" if passed else "**The incident is not resolved.**"]
    lines.append("")
    lines.append(f"Remediation match: {remediation_score:.0%}.")
    if not passed:
        wrong = sorted(chosen - correct)
        if wrong:
            lines.append(
                f"{len(wrong)} of your chosen actions would not have helped here: "
                "an action that does not address the mechanism usually makes the next incident harder to read."
            )
        if correct - chosen:
            lines.append(f"{len(correct - chosen)} necessary action(s) were not taken.")
    if diagnosis_score is not None:
        lines.append(f"Diagnosis quality: {diagnosis_score:.0%}. You inspected {len(inspected_valid)} signal(s).")
        misled = [signal_id for signal_id in inspected_valid if signal_id in red_herrings]
        if misled:
            lines.append(f"{len(misled)} of those were red herrings.")
    if root_cause_score is not None:
        lines.append(
            f"Your root-cause explanation covered {root_cause_score:.0%} of the key terms in the reference "
            "explanation. This is a keyword comparison, not a judgement of your writing."
        )
    elif task.root_cause_md:
        lines.append("No root-cause explanation was submitted, so that part of the score was skipped rather than zeroed.")

    return GradeOutcome(score=score, passed=passed, feedback_md="\n".join(lines)).clamped()


def incident_reveal(task: IncidentTask) -> Mapping[str, object]:
    """What the client is allowed to see once the incident is graded as passed."""
    return {"root_cause_md": task.root_cause_md, "correct_remediations": list(task.correct_remediations)}
