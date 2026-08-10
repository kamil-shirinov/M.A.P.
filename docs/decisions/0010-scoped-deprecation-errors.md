# 0010 — Deprecation warnings are errors, scoped to our own code

Status: Accepted · Date: 2026-08-10 · Phase 1

## Context

This project must still run in roughly three years, and its results must be
reproducible across that span. A removed API discovered at the moment it is
removed is a bad way to learn about it; the deprecation warning that preceded it
by two releases is the useful signal, and warnings scroll past unread.

Making all deprecations errors has an obvious cost, and it is not hypothetical: a
dependency ships a release that deprecates something *it* uses internally, and the
build breaks with no change on our side. CI then gates on other projects' release
timing, which is both noisy and outside our control.

## Options

1. **Warnings stay warnings.** Free, and they are never read.
2. **All deprecations are errors.** Catches everything, and inherits every
   upstream release schedule.
3. **Errors only for warnings attributed to our own code.**
4. **All deprecations are errors, with a per-dependency ignore list.** Equivalent
   coverage to (3) at the cost of a list someone must maintain forever.

## Decision

```toml
filterwarnings = ["default::DeprecationWarning", "error::DeprecationWarning:mapf"]
```

A deprecation attributed to a `mapf.*` frame fails the test run. One attributed
anywhere else is reported and does not.

**A green build now asserts something new**, which is why this is an ADR and not a
config tweak: it asserts that no code in `src/mapf` calls a deprecated API. That
claim is worth having and worth writing down.

**The `module` field matches where a warning is *attributed*, not where the code
lives** — attribution follows the `stacklevel` the warning was raised with. This
was verified experimentally rather than assumed, because the natural reading is
wrong: a warning raised inside `mapf` with `stacklevel=2` is attributed to its
*caller*, and if the caller is a test module the filter will not fire.

The practical consequence is that this catches the common case — our code calling
a deprecated stdlib or library API, where the library raises the warning with a
stacklevel pointing at us — and does not catch a deprecation we raise *for* our
own callers. The first is the case that matters.

## Consequences

- The very first run under this rule caught a real one:
  `importlib.abc.Traversable`, deprecated for removal in 3.14, in code written
  minutes earlier. That is the mechanism working as intended.
- A deprecation in a dependency is visible in the test output and does not break
  the build. Someone still has to read it; the filter buys attention, not action.
- No ignore list to maintain, and no annual pruning of entries for dependencies
  that have long since fixed themselves.
- The scope is `mapf`, matched as a prefix. A future top-level package would need
  adding, and a package named `mapfoo` would be caught by accident. Neither exists.
