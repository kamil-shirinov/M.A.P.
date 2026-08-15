"""Configuration loading, precedence, and startup policy.

No network and no inference server. The only filesystem touched is `tmp_path`,
plus one deliberate read of the committed `config/default.toml` to prove the
shipped placeholder is rejected rather than merely documented.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError
from structlog.testing import capture_logs

from mapf.core.errors import (
    ConfigurationError,
    DeterminismPolicyError,
    ModelNotAvailableError,
    PlaceholderConfigError,
)
from mapf.core.ports import ModelInfo
from mapf.settings import ModelRegistry, load

REPO_ROOT = Path(__file__).parents[2]

VALID_TOML = """
[inference]
base_url = "http://localhost:1234/v1"
connect_timeout_s = 10.0
read_timeout_s = 600.0
max_repair_attempts = 3

[models.intake]
alias = "llama-3.2-3b-instruct"
temperature = 0.0

[models.analyst]
alias = "gemma4:12b"
temperature = 0.7
seed = 20260809

[models.structuralist]
alias = "qwen3:4b"
temperature = 0.0

[cache]
llm_dir = "var/llm"
price_dir = "var/prices"

[data]
provider_order = ["yfinance", "stooq"]
adjustment = "split_adjusted"
history_days = 730

[data.sec]
user_agent = "Jane Doe jane@example.com M.A.P. research tool"
requests_per_second = 8.0
tickers_url = "https://www.sec.gov/files/company_tickers_exchange.json"
symbols_db = "var/symbols.sqlite"
refresh_days = 30

[news]
dir = "news"
rss_urls = []

[paths]
runs_dir = "runs"
"""


def _write(tmp_path: Path, content: str, name: str = "default.toml") -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Loading and types
# ---------------------------------------------------------------------------
def test_loads_and_coerces_types(tmp_path: Path) -> None:
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.inference.base_url == "http://localhost:1234/v1"
    assert settings.inference.connect_timeout_s == pytest.approx(10.0)
    assert settings.inference.read_timeout_s == pytest.approx(600.0)
    assert settings.inference.max_repair_attempts == 3
    assert settings.data.provider_order == ("yfinance", "stooq")
    assert settings.cache.llm_dir == Path("var/llm")
    assert settings.models.analyst.seed == 20260809
    assert settings.models.intake.seed is None


def test_settings_are_frozen(tmp_path: Path) -> None:
    """Nothing reconfigures itself mid-run."""
    settings = load([_write(tmp_path, VALID_TOML)])
    with pytest.raises(ValidationError):
        settings.inference.read_timeout_s = 1.0  # type: ignore[misc]


def test_unknown_config_keys_are_rejected(tmp_path: Path) -> None:
    """A typo in a config key must fail rather than be silently ignored."""
    with pytest.raises(ValidationError):
        load([_write(tmp_path, VALID_TOML + '\n[telemetry]\nendpoint = "https://x"\n')])


def test_missing_files_are_skipped_not_fatal(tmp_path: Path) -> None:
    """`config/local.toml` is optional by design."""
    settings = load([_write(tmp_path, VALID_TOML), tmp_path / "local.toml"])
    assert settings.paths.runs_dir == Path("runs")


def test_no_config_file_anywhere_gives_an_actionable_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match="no configuration file found"):
        load([tmp_path / "absent.toml"])


# ---------------------------------------------------------------------------
# Precedence
# ---------------------------------------------------------------------------
def test_environment_overrides_the_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The file is the committed baseline; the environment is the per-machine
    override. Inverted from pydantic-settings' default on purpose."""
    monkeypatch.setenv("MAP_INFERENCE__BASE_URL", "http://localhost:11434/v1")
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.inference.base_url == "http://localhost:11434/v1"


def test_deeply_nested_environment_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("MAP_DATA__SEC__REQUESTS_PER_SECOND", "4")
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.data.sec.requests_per_second == pytest.approx(4.0)
    # Siblings in the same table survive the override.
    assert settings.data.sec.refresh_days == 30


def test_backend_swap_is_config_only(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """CLAUDE.md §3: switching servers is a config edit, never a code edit."""
    monkeypatch.setenv("MAP_INFERENCE__BASE_URL", "http://localhost:11434/v1")
    monkeypatch.setenv("MAP_MODELS__STRUCTURALIST__ALIAS", "qwen3-4b-instruct")
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.models.structuralist.alias == "qwen3-4b-instruct"


def test_local_file_overlays_the_default_table_by_table(tmp_path: Path) -> None:
    """A shallow merge would delete every other key in the overridden table."""
    default = _write(tmp_path, VALID_TOML)
    local = _write(
        tmp_path,
        '[data.sec]\nuser_agent = "Local Dev local@example.com M.A.P."\n',
        name="local.toml",
    )
    settings = load([default, local])
    assert settings.data.sec.user_agent.startswith("Local Dev")
    assert settings.data.sec.refresh_days == 30
    assert settings.data.history_days == 730


# ---------------------------------------------------------------------------
# SEC User-Agent policy
# ---------------------------------------------------------------------------
def test_placeholder_user_agent_is_rejected(tmp_path: Path) -> None:
    content = VALID_TOML.replace(
        'user_agent = "Jane Doe jane@example.com M.A.P. research tool"',
        'user_agent = "REPLACE_ME <your.name> <your.email@example.com> M.A.P."',
    )
    with pytest.raises(PlaceholderConfigError) as caught:
        load([_write(tmp_path, content)])
    assert caught.value.key == "data.sec.user_agent"


def test_placeholder_error_says_what_to_do(tmp_path: Path) -> None:
    """A config error without a remedy just tells the operator they are wrong."""
    content = VALID_TOML.replace(
        'user_agent = "Jane Doe jane@example.com M.A.P. research tool"',
        'user_agent = "REPLACE_ME"',
    )
    with pytest.raises(PlaceholderConfigError) as caught:
        load([_write(tmp_path, content)])
    message = str(caught.value)
    assert "data.sec.user_agent" in message
    assert "MAP_DATA__SEC__USER_AGENT" in message
    assert "403" in message


def test_user_agent_without_a_contact_address_is_rejected(tmp_path: Path) -> None:
    """A name with no email is what actually earns the block."""
    content = VALID_TOML.replace(
        'user_agent = "Jane Doe jane@example.com M.A.P. research tool"',
        'user_agent = "M.A.P. research tool 1.0"',
    )
    with pytest.raises(ConfigurationError, match="no contact address"):
        load([_write(tmp_path, content)])


def test_the_committed_default_config_still_carries_its_placeholder() -> None:
    """The shipped `config/default.toml` must fail closed.

    If this ever stops raising, someone has committed a real contact address to
    version control — which is both a privacy leak and a config that works on one
    machine only.
    """
    with pytest.raises(PlaceholderConfigError):
        load([REPO_ROOT / "config" / "default.toml"])


def test_environment_can_rescue_the_shipped_placeholder(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The documented setup path: export the variable, leave the file alone."""
    monkeypatch.setenv("MAP_DATA__SEC__USER_AGENT", "Jane Doe jane@example.com M.A.P.")
    settings = load([REPO_ROOT / "config" / "default.toml"])
    assert settings.data.sec.user_agent.startswith("Jane Doe")


# ---------------------------------------------------------------------------
# Determinism policy
# ---------------------------------------------------------------------------
@pytest.mark.parametrize(
    ("agent", "alias"),
    [("intake", "llama-3.2-3b-instruct"), ("structuralist", "qwen3:4b")],
)
def test_sampling_is_rejected_for_deterministic_agents(
    tmp_path: Path, agent: str, alias: str
) -> None:
    """CLAUDE.md §6. The damage is invisible otherwise: a sampling structuralist
    still produces a valid forecast, and only the inability to reproduce it later
    reveals the problem."""
    content = VALID_TOML.replace(
        f'alias = "{alias}"\ntemperature = 0.0',
        f'alias = "{alias}"\ntemperature = 0.4',
    )
    with pytest.raises(DeterminismPolicyError) as caught:
        load([_write(tmp_path, content)])
    assert caught.value.agent == agent


def test_the_analyst_may_sample(tmp_path: Path) -> None:
    """Agent 2 is the one place sampling diversity is wanted, and it is not covered
    by the guard at all — which is why the override should rarely be needed."""
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.models.analyst.temperature == pytest.approx(0.7)


def _sampling_structuralist(*, override: bool) -> str:
    content = VALID_TOML.replace(
        'alias = "qwen3:4b"\ntemperature = 0.0',
        'alias = "qwen3:4b"\ntemperature = 0.4',
    )
    if override:
        content = content.replace(
            "[models.intake]", "[models]\nallow_nondeterministic = true\n\n[models.intake]"
        )
    return content


def test_the_override_must_be_set_deliberately(tmp_path: Path) -> None:
    """Default false. Without it the guard is a hard failure (ADR 0007)."""
    with pytest.raises(DeterminismPolicyError):
        load([_write(tmp_path, _sampling_structuralist(override=False))])


def test_the_override_permits_sampling(tmp_path: Path) -> None:
    settings = load([_write(tmp_path, _sampling_structuralist(override=True))])
    assert settings.models.allow_nondeterministic is True
    assert settings.models.structuralist.temperature == pytest.approx(0.4)


def test_the_override_warns_at_startup(tmp_path: Path) -> None:
    """A warning is ephemeral, but it is the part a human sees at the moment it
    matters. The durable half is the manifest flag."""
    path = _write(tmp_path, _sampling_structuralist(override=True))
    with capture_logs() as logs:
        load([path])
    warnings = [entry for entry in logs if entry["event"] == "determinism_override_active"]
    assert len(warnings) == 1
    assert warnings[0]["log_level"] == "warning"
    assert warnings[0]["agents"] == ["structuralist"]


def test_no_warning_when_nothing_is_actually_overridden(tmp_path: Path) -> None:
    """Setting the flag while every agent is still deterministic must stay quiet —
    otherwise the warning becomes noise and stops being read."""
    content = VALID_TOML.replace(
        "[models.intake]", "[models]\nallow_nondeterministic = true\n\n[models.intake]"
    )
    with capture_logs() as logs:
        load([_write(tmp_path, content)])
    assert [entry for entry in logs if entry["event"] == "determinism_override_active"] == []


def test_the_error_names_both_remedies(tmp_path: Path) -> None:
    with pytest.raises(DeterminismPolicyError) as caught:
        load([_write(tmp_path, _sampling_structuralist(override=False))])
    message = str(caught.value)
    assert "temperature = 0.0" in message
    assert "allow_nondeterministic" in message


def test_the_override_flag_is_reachable_for_the_manifest(tmp_path: Path) -> None:
    """ADR 0007: the durable record is the manifest, so the flag must be readable
    from settings by whatever writes it (module 7)."""
    settings = load([_write(tmp_path, VALID_TOML)])
    assert settings.models.allow_nondeterministic is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def _registry(tmp_path: Path) -> ModelRegistry:
    return ModelRegistry(load([_write(tmp_path, VALID_TOML)]).models)


def test_registry_exposes_specs_in_pipeline_order(tmp_path: Path) -> None:
    assert [spec.agent for spec in _registry(tmp_path).specs] == [
        "intake",
        "analyst",
        "structuralist",
    ]


def test_spec_carries_sampling_from_config(tmp_path: Path) -> None:
    spec = _registry(tmp_path).spec("analyst")
    assert spec.alias == "gemma4:12b"
    assert spec.sampling.temperature == pytest.approx(0.7)
    assert spec.sampling.seed == 20260809


def test_resolve_matches_an_exact_server_id(tmp_path: Path) -> None:
    available = [ModelInfo(id="qwen3:4b", fingerprint="f", fingerprint_source="tag")]
    assert _registry(tmp_path).resolve("structuralist", available).id == "qwen3:4b"


def test_resolve_is_case_insensitive(tmp_path: Path) -> None:
    available = [ModelInfo(id="QWEN3:4B", fingerprint="f", fingerprint_source="tag")]
    assert _registry(tmp_path).resolve("structuralist", available).id == "QWEN3:4B"


def test_resolve_does_not_guess(tmp_path: Path) -> None:
    """No fuzzy matching. A near-miss that silently selects different weights
    produces a complete, valid, wrong forecast."""
    available = [ModelInfo(id="qwen3-4b-instruct", fingerprint="f", fingerprint_source="tag")]
    with pytest.raises(ModelNotAvailableError):
        _registry(tmp_path).resolve("structuralist", available)


def test_missing_model_error_lists_what_the_server_has(tmp_path: Path) -> None:
    available = [ModelInfo(id="llama-3.2-3b-instruct", fingerprint="f", fingerprint_source="tag")]
    with pytest.raises(ModelNotAvailableError) as caught:
        _registry(tmp_path).resolve("analyst", available)
    assert caught.value.alias == "gemma4:12b"
    assert "llama-3.2-3b-instruct" in str(caught.value)


def test_resolve_all_returns_every_agent(tmp_path: Path) -> None:
    available = [
        ModelInfo(id="llama-3.2-3b-instruct", fingerprint="a", fingerprint_source="digest"),
        ModelInfo(id="gemma4:12b", fingerprint="b", fingerprint_source="composite"),
        ModelInfo(id="qwen3:4b", fingerprint="c", fingerprint_source="tag"),
    ]
    resolved = _registry(tmp_path).resolve_all(available)
    assert set(resolved) == {"intake", "analyst", "structuralist"}
    assert resolved["analyst"].fingerprint_source == "composite"


def test_resolve_all_reports_every_missing_model_at_once(tmp_path: Path) -> None:
    """Discovering the third missing alias after two model swaps is a slow way to
    learn something one startup check could have said immediately."""
    available = [ModelInfo(id="gemma4:12b", fingerprint="b", fingerprint_source="tag")]
    with pytest.raises(ModelNotAvailableError) as caught:
        _registry(tmp_path).resolve_all(available)
    message = str(caught.value)
    assert "llama-3.2-3b-instruct" in message
    assert "qwen3:4b" in message


def test_empty_server_is_reported_clearly(tmp_path: Path) -> None:
    with pytest.raises(ModelNotAvailableError, match=r"\(none\)"):
        _registry(tmp_path).resolve("intake", [])


# ---------------------------------------------------------------------------
# Vendor-string ban (CLAUDE.md §3)
# ---------------------------------------------------------------------------
def test_no_vendor_names_appear_in_application_code() -> None:
    """import-linter cannot check this, and the config file is the only place a
    backend may be named."""
    offenders: list[str] = []
    for path in (REPO_ROOT / "src").rglob("*.py"):
        text = path.read_text(encoding="utf-8").casefold()
        if "lm studio" in text or "lmstudio" in text or "ollama" in text:
            offenders.append(str(path.relative_to(REPO_ROOT)))
    assert offenders == []


# ---------------------------------------------------------------------------
# Token budgets must be reachable inside the read timeout
# ---------------------------------------------------------------------------
def test_an_unreachable_token_budget_is_rejected(tmp_path: Path) -> None:
    """`max_tokens` and `read_timeout_s` are set independently and the hardware
    couples them. A budget the model cannot finish spending before the timeout
    fires is a timeout wearing a budget's name — the run would fail as
    InferenceTimeoutError and send the reader hunting for a cold model load."""
    from mapf.core.errors import UnreachableTokenBudgetError

    content = VALID_TOML.replace(
        "read_timeout_s = 600.0", "read_timeout_s = 600.0\nmin_tokens_per_second = 10.0"
    ).replace(
        'alias = "gemma4:12b"',
        'alias = "gemma4:12b"\nmax_tokens = 12000\ncontext_tokens = 32768',
    )
    with pytest.raises(UnreachableTokenBudgetError) as caught:
        load([_write(tmp_path, content)])
    assert caught.value.agent == "analyst"
    assert "1200s" in str(caught.value)
    assert "min_tokens_per_second" in str(caught.value)


def test_a_reachable_budget_is_accepted(tmp_path: Path) -> None:
    content = VALID_TOML.replace(
        "read_timeout_s = 600.0", "read_timeout_s = 900.0\nmin_tokens_per_second = 10.0"
    ).replace('alias = "gemma4:12b"', 'alias = "gemma4:12b"\nmax_tokens = 6000')
    settings = load([_write(tmp_path, content)])
    assert settings.models.analyst.max_tokens == 6000


def test_faster_hardware_can_be_declared(tmp_path: Path) -> None:
    """The rate is an assumption about the machine, stated so it can be corrected
    rather than discovered."""
    content = VALID_TOML.replace(
        "read_timeout_s = 600.0", "read_timeout_s = 600.0\nmin_tokens_per_second = 40.0"
    ).replace(
        'alias = "gemma4:12b"',
        'alias = "gemma4:12b"\nmax_tokens = 12000\ncontext_tokens = 32768',
    )
    assert load([_write(tmp_path, content)]).models.analyst.max_tokens == 12000


def test_an_unset_budget_is_not_checked(tmp_path: Path) -> None:
    """`max_tokens` is optional; only a configured one can be unreachable."""
    assert load([_write(tmp_path, VALID_TOML)]).models.intake.max_tokens is None


def test_the_committed_config_has_a_reachable_budget() -> None:
    """The shipped pair must satisfy its own validator, or the first run after a
    clone fails on config."""
    import os

    os.environ["MAP_DATA__SEC__USER_AGENT"] = "Test Runner test@example.com"
    try:
        settings = load([REPO_ROOT / "config" / "default.toml"])
    finally:
        del os.environ["MAP_DATA__SEC__USER_AGENT"]
    budget = settings.models.analyst.max_tokens
    assert budget is not None
    needed = budget / settings.inference.min_tokens_per_second
    assert needed <= settings.inference.read_timeout_s * settings.inference.budget_margin


def test_a_budget_that_cannot_fit_its_context_is_rejected(tmp_path: Path) -> None:
    """Generation shares the window with the prompt, so max_tokens at or above
    context_tokens is a budget that can never be spent — the model stops at the
    context ceiling and reports exhaustion. Exactly how the first corpus run failed
    on TSLA: 6,699 reasoning tokens against a 12,000 budget in an 8,192 window."""
    from mapf.core.errors import UnreachableContextBudgetError

    content = VALID_TOML.replace(
        'alias = "gemma4:12b"',
        'alias = "gemma4:12b"\nmax_tokens = 12000\ncontext_tokens = 8192',
    )
    with pytest.raises(UnreachableContextBudgetError) as caught:
        load([_write(tmp_path, content)])
    assert caught.value.agent == "analyst"
    assert caught.value.context_tokens == 8192
    assert "unreachable" in str(caught.value)
