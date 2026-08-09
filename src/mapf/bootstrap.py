"""Composition root.

The only module permitted to know which concrete adapters exist. It reads
settings, constructs implementations, and hands them to `mapf.pipeline` as
Protocols — which is what lets every layer above depend on `mapf.core.ports`
alone (ADR 0004).

Exempt from the `forbidden` contracts by design, and therefore the one place a
boundary breach can still hide. It stays small and free of logic for that reason.

Not yet implemented — Phase 1, module 7.
"""
