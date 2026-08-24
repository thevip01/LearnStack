"""Code that runs *inside* a sandbox container.

Nothing in this subpackage may import anything outside the standard library and
pytest, and nothing outside it may import these modules at runtime: the API only
ever reads ``pytest_harness.py`` as text and ships it into a workspace.
"""
