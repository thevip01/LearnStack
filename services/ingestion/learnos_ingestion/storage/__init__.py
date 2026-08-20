"""Raw-byte storage and the ingestion repository.

Split along one line: bytes go to the filesystem, metadata goes to Postgres. A
crawl of a docs site is tens of megabytes of HTML that nothing ever queries by
content, and putting it in a column makes every backup, every replica and every
``SELECT *`` pay for it. The database keeps the hashes, which is what change
detection actually reads.
"""

from __future__ import annotations

from .objects import RawStore
from .repository import IngestionRepository

__all__ = ["IngestionRepository", "RawStore"]
