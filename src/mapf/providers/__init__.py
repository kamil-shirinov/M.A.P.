"""Adapters for the inference server.

Three implementations of `mapf.core.ports.LLMProvider`:

- `openai_compat` — the only module in the project that speaks HTTP to a model
- `caching` — a decorator adding a content-addressed disk cache
- `fake` — fixture replay, so the CLI and the test suite run with no server

Nothing is re-exported. As in `mapf.core`, the module a class comes from is part
of what the architecture is arguing: `bootstrap` importing
`mapf.providers.openai_compat` states plainly which adapter is being wired.
"""
