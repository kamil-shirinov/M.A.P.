"""`scripts/publish_site.sh`, run for real against a throwaway repository.

The script's whole job is to refuse to do the wrong irreversible thing, so these tests
run it: the real file, copied into a sandbox clone whose `origin` is a bare repository
on disk. No network, and nothing here can reach the real remote. The build is a stub
that lays down a prepared site, because the real one needs `var/` and a laptop; the
script's own checks are what is under test, and they do not depend on who built.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "publish_site.sh"

_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "T",
    "GIT_AUTHOR_EMAIL": "t@example.test",
    "GIT_COMMITTER_NAME": "T",
    "GIT_COMMITTER_EMAIL": "t@example.test",
    "GIT_CONFIG_GLOBAL": os.devnull,
    "GIT_CONFIG_SYSTEM": os.devnull,
}


def _git(cwd: Path, *args: str) -> str:
    done = subprocess.run(
        ["git", *args], cwd=cwd, env=_ENV, check=True, capture_output=True, text=True
    )
    return done.stdout.strip()


class Sandbox:
    def __init__(self, root: Path) -> None:
        self.origin = root / "origin.git"
        self.work = root / "work"
        _git(root, "init", "--bare", "--initial-branch=main", str(self.origin))
        _git(root, "clone", "--quiet", str(self.origin), str(self.work))
        _git(self.work, "config", "user.name", "T")
        _git(self.work, "config", "user.email", "t@example.test")
        (self.work / "scripts").mkdir()
        shutil.copy(SCRIPT, self.work / "scripts" / "publish_site.sh")
        # The stand-in build: puts whatever the test prepared in `prepared/` at `site/`.
        build = self.work / "scripts" / "build_site.sh"
        build.write_text(
            '#!/usr/bin/env bash\nset -e\nR="$(cd "$(dirname "$0")/.." && pwd)"\n'
            'rm -rf "$R/site"\ncp -R "$R/prepared" "$R/site"\n'
        )
        build.chmod(0o755)
        (self.work / "README").write_text("main\n")
        (self.work / ".gitignore").write_text("site/\nprepared/\n")
        _git(self.work, "add", "-A")
        _git(self.work, "commit", "--quiet", "-m", "main")
        _git(self.work, "push", "--quiet", "origin", "HEAD:main")
        self.prepare()

    def prepare(self, *, companies: int = 0, extra: dict[str, str] | None = None) -> None:
        prepared = self.work / "prepared"
        shutil.rmtree(prepared, ignore_errors=True)
        export = prepared / "assets" / "export"
        export.mkdir(parents=True)
        (prepared / "index.html").write_text("<!doctype html>")
        (prepared / "robots.txt").write_text("User-agent: *\n")
        (export / "manifest.json").write_text(
            json.dumps({"prices": {"snapshot": "2026-09-05", "companies": companies}})
        )
        for name, body in (extra or {}).items():
            target = prepared / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(body)

    def run(self, *args: str, answer: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", str(self.work / "scripts" / "publish_site.sh"), *args],
            cwd=self.work,
            env=_ENV,
            input=answer,
            capture_output=True,
            text=True,
        )

    def pages(self) -> list[str]:
        done = subprocess.run(
            ["git", "ls-tree", "-r", "--name-only", "gh-pages"],
            cwd=self.origin,
            env=_ENV,
            capture_output=True,
            text=True,
        )
        return done.stdout.split() if done.returncode == 0 else []

    def pages_commits(self) -> int:
        return int(_git(self.origin, "rev-list", "--count", "gh-pages"))

    def main(self) -> str:
        return _git(self.origin, "rev-parse", "main")


@pytest.fixture
def box(tmp_path: Path) -> Sandbox:
    return Sandbox(tmp_path)


def test_it_publishes_only_the_site_as_one_commit_with_no_parent(box: Sandbox) -> None:
    before = box.main()
    done = box.run(answer="publish\n")
    assert done.returncode == 0, done.stderr
    assert box.pages() == [".nojekyll", "assets/export/manifest.json", "index.html", "robots.txt"]
    assert box.pages_commits() == 1
    assert _git(box.origin, "rev-list", "--parents", "-n1", "gh-pages").split() == [
        _git(box.origin, "rev-parse", "gh-pages")
    ]
    assert box.main() == before  # main is untouched, and carries no site


def test_the_commit_names_the_main_commit_it_was_built_from(box: Sandbox) -> None:
    box.run(answer="publish\n")
    message = _git(box.origin, "log", "-1", "--format=%B", "gh-pages")
    assert box.main() in message


def test_a_second_deploy_replaces_the_branch_rather_than_extending_it(box: Sandbox) -> None:
    box.run(answer="publish\n")
    box.prepare(extra={"company.html": "<!doctype html>"})
    done = box.run(answer="publish\n")
    assert done.returncode == 0, done.stderr
    assert "company.html" in box.pages()
    assert box.pages_commits() == 1
    assert "replaces" in done.stdout


def test_a_dry_run_prepares_everything_and_pushes_nothing(box: Sandbox) -> None:
    done = box.run("--dry-run")
    assert done.returncode == 0, done.stderr
    assert "nothing was pushed" in done.stdout
    assert box.pages() == []


def test_without_the_word_it_does_not_push(box: Sandbox) -> None:
    for answer in ("", "yes\n", "Publish\n"):
        done = box.run(answer=answer)
        assert done.returncode == 1
        assert "not confirmed" in done.stderr
    assert box.pages() == []


def test_yes_skips_the_question(box: Sandbox) -> None:
    assert box.run("--yes").returncode == 0
    assert box.pages()


def test_a_price_series_is_refused(box: Sandbox) -> None:
    box.prepare(extra={"assets/export/prices/AAPL.json": "{}"})
    done = box.run("--yes")
    assert done.returncode == 1
    assert "prices" in done.stderr
    assert box.pages() == []


def test_a_manifest_that_says_prices_were_exported_is_refused(box: Sandbox) -> None:
    box.prepare(companies=120)
    done = box.run("--yes")
    assert done.returncode == 1
    assert "manifest says prices were exported" in done.stderr
    assert box.pages() == []


def test_a_site_without_a_manifest_is_refused(box: Sandbox) -> None:
    (box.work / "prepared" / "assets" / "export" / "manifest.json").unlink()
    done = box.run("--yes")
    assert done.returncode == 1
    assert "manifest" in done.stderr


def test_a_build_that_produced_nothing_is_refused(box: Sandbox) -> None:
    (box.work / "scripts" / "build_site.sh").write_text("#!/usr/bin/env bash\nrm -rf site\n")
    done = box.run("--yes")
    assert done.returncode == 1
    assert "was not built" in done.stderr


@pytest.mark.parametrize(
    "extra",
    [
        {"var/ledger.json": "{}"},  # an unexpected top-level directory
        {"notes.md": "x"},  # an unexpected top-level file
        {".env": "KEY=1"},  # a hidden one
    ],
)
def test_anything_outside_the_page_files_and_assets_is_refused(
    box: Sandbox, extra: dict[str, str]
) -> None:
    box.prepare(extra=extra)
    done = box.run("--yes")
    assert done.returncode == 1
    assert "unexpected entry" in done.stderr
    assert box.pages() == []


@pytest.mark.parametrize("name", ["trace.jsonl", "p.parquet"])
def test_a_trace_or_a_parquet_file_is_refused_wherever_it_hides(box: Sandbox, name: str) -> None:
    box.prepare(extra={f"assets/export/runs/{name}": "x"})
    done = box.run("--yes")
    assert done.returncode == 1
    assert "parquet, jsonl or env" in done.stderr
    assert box.pages() == []


def test_a_local_home_directory_path_is_a_warning_not_a_refusal(box: Sandbox) -> None:
    box.prepare(extra={"assets/export/note.json": '{"p": "/Users/someone/map/var"}'})
    done = box.run("--yes")
    assert done.returncode == 0
    assert "note.json" in done.stderr
    assert box.pages()


def test_a_commit_that_is_not_on_origin_main_is_refused(box: Sandbox) -> None:
    (box.work / "README").write_text("unmerged\n")
    _git(box.work, "commit", "--quiet", "-am", "unmerged work")
    done = box.run("--yes")
    assert done.returncode == 1
    assert "not on origin/main" in done.stderr
    assert box.pages() == []


def test_missing_git_identity_is_refused_before_anything_is_pushed(box: Sandbox) -> None:
    _git(box.work, "config", "--unset", "user.name")
    done = box.run("--yes")
    assert done.returncode == 1
    assert "user.name" in done.stderr
    assert box.pages() == []


def test_an_unknown_option_is_refused(box: Sandbox) -> None:
    done = box.run("--branch=main")
    assert done.returncode == 2
    assert "unknown option" in done.stderr


def test_a_branch_that_moved_after_the_look_is_not_overwritten(
    box: Sandbox, tmp_path: Path
) -> None:
    """The lease. Someone else's deploy lands between the script's look at the remote
    and its push: the push must fail rather than replace what it never saw. A `git`
    placed ahead on PATH moves the branch at exactly that moment, so a plain `--force`
    would pass this test's setup and fail its assertion."""
    box.run("--yes")
    seen = _git(box.origin, "rev-parse", "gh-pages")
    real = shutil.which("git")
    shim = tmp_path / "shim"
    shim.mkdir()
    (shim / "git").write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "-C" ] && [ "$3" = "push" ]; then\n'
        f"  {real} --git-dir={box.origin} update-ref refs/heads/gh-pages "
        f'"$({real} --git-dir={box.origin} commit-tree -m other {seen}^{{tree}})"\n'
        "fi\n"
        f'exec {real} "$@"\n'
    )
    (shim / "git").chmod(0o755)
    box.prepare(extra={"company.html": "<!doctype html>"})
    done = subprocess.run(
        ["bash", str(box.work / "scripts" / "publish_site.sh"), "--yes"],
        cwd=box.work,
        env={**_ENV, "PATH": f"{shim}{os.pathsep}{os.environ['PATH']}"},
        capture_output=True,
        text=True,
    )
    assert done.returncode != 0
    assert "company.html" not in box.pages()
    assert _git(box.origin, "log", "-1", "--format=%s", "gh-pages") == "other"
