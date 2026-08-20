"""The single source of the version string.

Its own module so that ``/healthz``, the OpenAPI document and the ``X-LearnOS-
Version`` header cannot drift, and so that reading it does not require importing
the app factory.
"""

from __future__ import annotations

VERSION = "0.1.0"
