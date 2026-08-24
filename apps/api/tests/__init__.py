"""Makes ``tests`` a package so ``from .conftest import ...`` resolves.

Without this, pytest imports each test module as a top level name and the relative
import fails under the default import mode. The alternative, importing ``conftest``
absolutely, only works while the tests directory happens to be on ``sys.path``.
"""
