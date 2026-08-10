"""Versioned prompt templates and the renderer that quarantines untrusted text.

The `.md` files here are package data, loaded via `importlib.resources`. They are
versioned in the filename (`intake.v1.md`) because prompts are not portable across
models: a template tuned for one model is often worse on another, and versioning
is what lets per-model variants coexist without touching any logic.

The three templates repeat their guard rules almost verbatim. That duplication is
deliberate — a shared fragment would couple three prompts that are expected to
diverge per model, and a prompt is content, not code.

Nothing is re-exported. `mapf.prompts.loader.FilePromptStore` says where the
implementation lives; `mapf.prompts.sanitise` says where the safety argument does.
"""
