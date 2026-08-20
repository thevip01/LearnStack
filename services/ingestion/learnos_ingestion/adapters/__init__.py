"""Adapter registry.

One dict, keyed by ``AdapterKind``. A new adapter is one class plus one entry here,
and ``for_source`` is the only way the pipeline constructs one — so there is no
path by which a source runs without the licensing and robots checks in
``SourceAdapter.run``.
"""

from __future__ import annotations

from pathlib import Path

from learnos_schema.ingestion import AdapterKind, SourceSpec

from .base import (
    PERMISSIVE_LICENSES,
    AdapterUnavailable,
    FetchRefused,
    RateLimiter,
    RobotsCache,
    SourceAdapter,
    license_gate,
)
from .local import LocalAdapter
from .structured import GithubAdapter, OpenApiAdapter, PdfAdapter, parse_spec, spec_summary
from .web import RssAdapter, SitemapAdapter, WebAdapter

ADAPTERS: dict[str, type[SourceAdapter]] = {
    AdapterKind.WEB.value: WebAdapter,
    AdapterKind.SITEMAP.value: SitemapAdapter,
    AdapterKind.RSS.value: RssAdapter,
    AdapterKind.GITHUB.value: GithubAdapter,
    AdapterKind.OPENAPI.value: OpenApiAdapter,
    AdapterKind.PDF.value: PdfAdapter,
    AdapterKind.LOCAL.value: LocalAdapter,
}


def for_source(spec: SourceSpec, *, robots: RobotsCache | None = None, local_root: Path | None = None) -> SourceAdapter:
    """Build the adapter for a source.

    ``spec.adapter`` is a plain string here rather than an enum member, because
    ``SchemaModel`` sets ``use_enum_values=True`` — every enum on a validated model
    is already coerced to its value. Indexing a dict keyed by ``.value`` is
    therefore correct; keying it by the enum member would silently miss.
    """
    adapter_cls = ADAPTERS.get(str(spec.adapter))
    if adapter_cls is None:
        raise AdapterUnavailable(f"no adapter registered for kind {spec.adapter!r} (source {spec.id!r})")
    if adapter_cls is LocalAdapter:
        return LocalAdapter(spec, robots=robots, root=local_root)
    return adapter_cls(spec, robots=robots)


__all__ = [
    "ADAPTERS",
    "PERMISSIVE_LICENSES",
    "AdapterUnavailable",
    "FetchRefused",
    "GithubAdapter",
    "LocalAdapter",
    "OpenApiAdapter",
    "PdfAdapter",
    "RateLimiter",
    "RobotsCache",
    "RssAdapter",
    "SitemapAdapter",
    "SourceAdapter",
    "WebAdapter",
    "for_source",
    "license_gate",
    "parse_spec",
    "spec_summary",
]
