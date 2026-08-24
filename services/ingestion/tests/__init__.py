"""Makes ``tests`` a package so ``from .conftest import ...`` resolves.

Three test modules here import ``FakeRepo`` and friends relatively. Without this
file, pytest imports each module as a top level name and collection fails with
"attempted relative import with no known parent package", which is what happens when
``make test`` runs ``pytest services/ingestion/tests`` from the repo root.
"""
