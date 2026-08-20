"""Domain modules.

Each subpackage owns one slice of behaviour and is importable without FastAPI in
the picture, so the graders and the mastery maths can be unit tested without an
app, a database or a container runtime.
"""
