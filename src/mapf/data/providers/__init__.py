"""Price-source adapters and the failover chain.

Each adapter normalises into the canonical basis itself (ADR 0003). Nothing is
re-exported: `bootstrap` importing `mapf.data.providers.stooq` states plainly
which source is being wired.
"""
