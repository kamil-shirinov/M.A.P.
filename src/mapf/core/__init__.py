"""The domain layer.

Imports nothing from `mapf.*` and performs no I/O — no HTTP, no disk, no clock.
`import-linter` enforces the first half of that (ADR 0004); the second half is a
review rule, because a stray `datetime.now()` is not an import.

Nothing is re-exported here on purpose. `from mapf.core.models import Forecast`
says where a type is defined; `from mapf.core import Forecast` does not, and the
difference matters in a codebase whose whole argument is about where things live.
"""
