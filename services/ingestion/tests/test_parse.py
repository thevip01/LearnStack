"""Parse and clean.

The stage that decides what counts as content. Its failure mode is the quietest one
in the pipeline: a selector that removes too much deletes text without erroring, and
nobody notices until a learner reads a concept with a hole in it. So the tests here
lean on the two things that are checkable: code samples survive byte-exact, and a
page that cleans down to nothing is reported rather than stored.
"""

from __future__ import annotations

import pytest
from learnos_schema.ingestion import ParsedDocument

from learnos_ingestion.hashing import content_hash
from learnos_ingestion.stages.parse import clean_report, clean_text, parse_document, parse_markdown

PROSE = "Load balancer health checks decide which targets receive traffic. " * 6


class TestCleanText:
    def test_collapses_blank_runs(self) -> None:
        assert clean_text("a\n\n\n\n\nb") == "a\n\nb"

    def test_strips_trailing_whitespace_per_line(self) -> None:
        assert clean_text("a   \nb\t\n") == "a\nb"

    def test_normalises_line_endings(self) -> None:
        assert clean_text("a\r\nb\rc") == "a\nb\nc"

    def test_removes_invisible_characters(self) -> None:
        """Zero-width characters break exact-match grading.

        A learner types the right answer, the grader compares it against a string with
        a zero-width space in it, and the platform tells them they are wrong. Removing
        these at parse time is the only place it can be done once.
        """
        assert clean_text("time​out") == "timeout"

    def test_leaves_punctuation_alone(self) -> None:
        """Deliberately not normalising quotes or dashes.

        A smart quote in prose is correct and a smart quote in a code sample is a bug
        in the source: this function cannot tell them apart, and guessing would
        corrupt code, which is the one thing that must survive byte-exact.
        """
        text = "Use “smart” quotes — they are fine."
        assert clean_text(text) == text


class TestParseMarkdown:
    def test_extracts_fences_verbatim_with_their_language(self) -> None:
        """Indentation inside a fence is semantic in Python. Any normalisation of the
        block makes every practice task generated from it broken."""
        body = "# Title\n\n```python\ndef f():\n    return   1\n```\n"
        _, _, _, code_blocks = parse_markdown(body)
        assert code_blocks == [{"ordinal": 0, "language": "python", "source": "def f():\n    return   1"}]

    def test_a_hash_inside_a_fence_is_not_a_heading(self) -> None:
        """Comments in shell samples start with ``#``. Treating them as headings would
        produce a heading path made of code comments, and every chunk under it would
        cite a heading that does not exist on the page."""
        body = "# Real\n\n```bash\n# not a heading\naws elbv2 describe-target-health\n```\n"
        _, title, heading_path, _ = parse_markdown(body)
        assert title == "Real"
        assert heading_path == ["Real"]

    def test_title_is_the_first_heading(self) -> None:
        _, title, _, _ = parse_markdown("## Second level first\n\nbody\n\n# Later h1\n")
        assert title == "Second level first"

    def test_heading_path_is_capped(self) -> None:
        """An API reference page can have hundreds of headings. Storing them all makes
        the column large and the breadcrumb meaningless."""
        body = "\n\n".join(f"## Heading {index}" for index in range(40))
        _, _, heading_path, _ = parse_markdown(body)
        assert len(heading_path) == 12

    def test_text_keeps_the_fences(self) -> None:
        """The chunker splits on fences to avoid bisecting them, so it needs them
        present in the text: extracting them is additive, not a move."""
        text, _, _, _ = parse_markdown("# T\n\n```py\nx = 1\n```\n")
        assert "```py" in text


class TestParseDocument:
    def test_skips_a_page_too_thin_to_teach(self) -> None:
        """Redirect stubs, 404 bodies and nav-only indexes all land here. Letting them
        through spends extraction budget on pages that say nothing."""
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/markdown", body=b"# Hi\n\nShort.", url=None
        )
        assert result.parsed is None
        assert "characters of text" in (result.skipped_reason or "")

    def test_pdf_is_an_explicit_skip_not_an_empty_parse(self) -> None:
        """An empty-but-successful parse is indistinguishable from a PDF that genuinely
        has no content, so the unwired path has to say so."""
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="application/pdf", body=b"%PDF-1.7", url=None
        )
        assert result.parsed is None
        assert "pdf" in (result.skipped_reason or "").lower()

    def test_returns_a_reason_rather_than_raising(self) -> None:
        """One malformed document must not abort a crawl of nine hundred."""
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="application/json", body=b"{not json", url=None
        )
        assert result.parsed is None
        assert result.skipped_reason

    def test_parsed_id_is_stable_for_identical_text(self) -> None:
        body = f"# Health checks\n\n{PROSE}".encode()
        first = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/markdown", body=body, url=None
        )
        second = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/markdown", body=body, url=None
        )
        assert first.parsed is not None and second.parsed is not None
        assert first.parsed.id == second.parsed.id
        assert first.parsed.content_hash == second.parsed.content_hash

    def test_url_is_carried_through_as_canonical_when_none_is_declared(self) -> None:
        result = parse_document(
            document_id="doc.1",
            source_id="s.1",
            media_type="text/markdown",
            body=f"# T\n\n{PROSE}".encode(),
            url="https://example.test/page",
        )
        assert result.parsed is not None
        assert result.parsed.canonical_url == "https://example.test/page"


class TestParseHtml:
    """HTML parsing needs lxml, which is a hard dependency of the service but not of
    a bare checkout, so these skip rather than fail when it is absent."""

    @pytest.fixture(autouse=True)
    def _needs_lxml(self) -> None:
        pytest.importorskip("lxml")
        pytest.importorskip("bs4")

    def html(self, main: str, *, head: str = "") -> bytes:
        return f"<html><head><title>Docs</title>{head}</head><body>{main}</body></html>".encode()

    def test_removes_chrome(self) -> None:
        body = self.html(
            "<nav>Navigation</nav>"
            '<div class="sidebar">Sidebar links</div>'
            '<div id="toc-container">On this page</div>'
            f"<main><h1>Health checks</h1><p>{PROSE}</p></main>"
            "<footer>Copyright</footer>"
        )
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/html", body=body, url=None
        )
        assert result.parsed is not None
        text = result.parsed.text
        assert "Health checks" in text
        for chrome in ("Navigation", "Sidebar links", "On this page", "Copyright"):
            assert chrome not in text

    def test_code_survives_whitespace_normalisation(self) -> None:
        """Extracted before the tree is flattened, precisely so that indentation and
        blank lines inside the sample are not touched by ``clean_text``."""
        code = "def f():\n    if True:\n\n        return   1\n"
        body = self.html(
            f'<main><h1>Example</h1><p>{PROSE}</p>'
            f'<pre><code class="language-python">{code}</code></pre></main>'
        )
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/html", body=body, url=None
        )
        assert result.parsed is not None
        assert result.parsed.code_blocks
        block = result.parsed.code_blocks[0]
        assert block["language"] == "python"
        assert "    if True:" in block["source"]

    def test_a_code_inside_a_pre_is_one_block(self) -> None:
        body = self.html(f"<main><h1>T</h1><p>{PROSE}</p><pre><code>x = 1</code></pre></main>")
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/html", body=body, url=None
        )
        assert result.parsed is not None
        assert len(result.parsed.code_blocks) == 1

    def test_headings_survive_as_markdown(self) -> None:
        """The chunker splits on ``#`` markers. Flattening headings into bare text
        would put every chunk boundary mid-explanation."""
        body = self.html(f"<main><h1>Top</h1><p>{PROSE}</p><h2>Nested</h2><p>{PROSE}</p></main>")
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/html", body=body, url=None
        )
        assert result.parsed is not None
        assert "# Top" in result.parsed.text
        assert "## Nested" in result.parsed.text

    def test_canonical_link_beats_the_fetched_url(self) -> None:
        """Docs sites serve the same page under versioned paths. Without this, one page
        is ingested three times and the learner sees three copies of one concept."""
        body = self.html(
            f"<main><h1>T</h1><p>{PROSE}</p></main>",
            head='<link rel="canonical" href="https://example.test/latest/page"/>',
        )
        result = parse_document(
            document_id="doc.1",
            source_id="s.1",
            media_type="text/html",
            body=body,
            url="https://example.test/v1.2/page",
        )
        assert result.parsed is not None
        assert result.parsed.canonical_url == "https://example.test/latest/page"

    def test_tables_are_kept_as_rows(self) -> None:
        body = self.html(
            f"<main><h1>T</h1><p>{PROSE}</p>"
            "<table><tr><th>Setting</th><th>Default</th></tr>"
            "<tr><td>timeout</td><td>5s</td></tr></table></main>"
        )
        result = parse_document(
            document_id="doc.1", source_id="s.1", media_type="text/html", body=body, url=None
        )
        assert result.parsed is not None
        assert result.parsed.tables
        assert result.parsed.tables[0]["rows"][0] == ["Setting", "Default"]


def parsed_of(text: str) -> ParsedDocument:
    return ParsedDocument(
        id="parsed.1", document_id="doc.1", source_id="s.1", text=text, content_hash=content_hash(text)
    )


class TestCleanReport:
    def test_reports_the_kept_ratio(self) -> None:
        report = clean_report([parsed_of("x" * 500)], raw_bytes=1000)
        assert report.ok
        assert any("50.0%" in message for message in report.messages)

    def test_a_collapse_below_five_percent_fails_the_stage(self) -> None:
        """The single most useful signal that a source changed its template.

        Failing the stage rather than logging is the point: the run continues and the
        candidates land in review, but the report says not to approve them until
        someone has looked at a parsed document.
        """
        report = clean_report([parsed_of("x" * 40)], raw_bytes=100_000)
        assert not report.ok
        assert any("template" in message for message in report.messages)

    def test_no_raw_byte_count_means_no_ratio_claim(self) -> None:
        report = clean_report([parsed_of("x" * 500)], raw_bytes=0)
        assert report.ok
        assert report.messages == []
