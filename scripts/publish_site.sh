#!/usr/bin/env bash
#
# Build the site WITHOUT prices and publish it to the `gh-pages` branch, which
# holds only the built site and is replaced on every deploy.
#
# RUN THIS ON THE LAPTOP. `map export` needs `var/`, the runs and the scoring
# passes, none of which are committed, so nothing else can build the site. That
# is also why this is not a CI job: a runner would have no export to publish.
#
# WHAT IT DOES, in order, stopping at the first thing that is wrong:
#   1. checks HEAD is already on origin/main, so the published copy names a commit
#      anyone can read
#   2. runs scripts/build_site.sh (which refuses a dirty config/ or src/mapf/,
#      runs both suites and the style probe, and exports without prices)
#   3. VERIFIES what it built rather than trusting the builder: no prices/, the
#      manifest says no company was priced, and nothing outside the page files
#      and assets/ is in there
#   4. makes a fresh repository holding only that directory, as ONE commit with
#      no parent, in a temporary directory — your clone is never switched
#      to gh-pages, so there is nothing to stash and nothing to get back from
#   5. shows what it is about to do and asks for the word "publish"
#   6. pushes to refs/heads/gh-pages and nothing else, forcing only against the
#      commit it saw there a moment earlier
#
#   scripts/publish_site.sh --dry-run   # 1-5, then stop. Pushes nothing.
#   scripts/publish_site.sh             # asks, then pushes
#   scripts/publish_site.sh --yes       # does not ask. For when you have already looked.
#
# WHAT CANNOT BE TAKEN BACK. A Pages site is public whatever the repository's own
# visibility. A force-push replaces the branch, but GitHub keeps unreachable
# commits retrievable by their hash for some time and does not let you purge them
# on request from here; a deploy that included something it should not have is
# not undone by the next one. That is why step 3 refuses on prices rather than
# warning, and why step 5 exists. See docs/publishing.md.
#
# bash 3.2 (macOS's own) is the target: no mapfile, no associative arrays.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/site"
REMOTE="origin"
# A constant, not an option. A flag that names the branch is a flag that can be
# given main.
BRANCH="gh-pages"

DRY_RUN=0
ASSUME_YES=0
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY_RUN=1 ;;
    --yes) ASSUME_YES=1 ;;
    *) echo "unknown option: $arg" >&2; echo "usage: $0 [--dry-run] [--yes]" >&2; exit 2 ;;
  esac
done

die() { echo "refusing: $*" >&2; exit 1; }

cd "$ROOT"

echo "==> is this commit already on $REMOTE/main"
git fetch --quiet "$REMOTE" main || die "could not fetch $REMOTE/main"
HEAD_SHA="$(git rev-parse HEAD)"
if ! git merge-base --is-ancestor "$HEAD_SHA" "$REMOTE/main"; then
  die "HEAD ($(git rev-parse --short HEAD)) is not on $REMOTE/main. The published copy would name a commit nobody else can read. Merge first."
fi
echo "    $(git rev-parse --short HEAD)"

echo "==> building without prices"
# No flag: build_site.sh leaves prices out unless asked to put them in, and this
# script never asks. Step 3 checks the result anyway.
"$ROOT/scripts/build_site.sh"

echo "==> verifying what was built"
[ -d "$SITE" ] || die "$SITE was not built"
[ -f "$SITE/assets/export/manifest.json" ] || die "no manifest.json in the export"
if [ -e "$SITE/assets/export/prices" ]; then
  die "$SITE/assets/export/prices exists. This is the redistributable price series and it does not go on a public page."
fi
python3 - "$SITE/assets/export/manifest.json" <<'PY' || die "the manifest says prices were exported"
import json, sys
manifest = json.load(open(sys.argv[1], encoding="utf-8"))
companies = (manifest.get("prices") or {}).get("companies")
sys.exit(0 if companies == 0 else 1)
PY
# Only what the pages load. An unexpected top-level name is a file nobody meant to
# publish, and finding it AFTER the push is too late.
for entry in "$SITE"/* "$SITE"/.[!.]*; do
  [ -e "$entry" ] || continue
  name="$(basename "$entry")"
  case "$name" in
    *.html|assets|robots.txt) ;;
    *) die "unexpected entry in the site: $name" ;;
  esac
done
if [ -n "$(find "$SITE" \( -name '*.parquet' -o -name '*.jsonl' -o -name '*.env' \) -print | head -n 1)" ]; then
  die "the site holds a parquet, jsonl or env file"
fi
# A laptop's home directory in a public file is not a defect in the same class as
# prices, so this warns. It is worth a look before it is on the internet.
if grep -rIlE '/(Users|home)/[A-Za-z0-9._-]+/' "$SITE" >/dev/null 2>&1; then
  echo "    WARNING: a local home-directory path appears in:" >&2
  grep -rIlE '/(Users|home)/[A-Za-z0-9._-]+/' "$SITE" | sed 's/^/      /' >&2
fi
echo "    no prices; $(find "$SITE" -type f | wc -l | tr -d ' ') files; $(du -sh "$SITE" | cut -f1)"

echo "==> assembling a one-commit repository"
STAGE="$(mktemp -d "${TMPDIR:-/tmp}/map-site.XXXXXX")"
trap 'rm -rf "$STAGE"' EXIT
cp -R "$SITE/." "$STAGE/"
# Without it Pages runs the files through Jekyll, which drops anything whose name
# starts with an underscore.
: > "$STAGE/.nojekyll"
git_user_name="$(git config user.name || true)"
git_user_email="$(git config user.email || true)"
[ -n "$git_user_name" ] && [ -n "$git_user_email" ] || die "git user.name / user.email are not set"
(
  cd "$STAGE"
  git init --quiet --initial-branch="$BRANCH"
  git add -A
  git -c user.name="$git_user_name" -c user.email="$git_user_email" commit --quiet \
    -m "Publish the site built from $HEAD_SHA" \
    -m "No prices. Replaces the previous contents of this branch; it carries no history."
)
PUBLISHED="$(git -C "$STAGE" rev-parse --short HEAD)"

REMOTE_URL="$(git remote get-url "$REMOTE")"
CURRENT="$(git ls-remote "$REMOTE" "refs/heads/$BRANCH" | cut -f1)"

echo
echo "About to publish:"
echo "    from      $(git rev-parse --short HEAD) (on $REMOTE/main)"
echo "    to        $REMOTE_URL  refs/heads/$BRANCH"
echo "    commit    $PUBLISHED, no parent"
if [ -n "$CURRENT" ]; then
  echo "    replaces  ${CURRENT:0:7}, forced only if the branch is still there"
else
  echo "    replaces  nothing: the branch does not exist yet"
fi
echo
echo "A Pages site is PUBLIC whatever this repository's visibility. A force-push cannot"
echo "be taken back by publishing again: the old commit stays retrievable by its hash."

if [ "$DRY_RUN" -eq 1 ]; then
  echo
  echo "--dry-run: nothing was pushed."
  exit 0
fi

if [ "$ASSUME_YES" -ne 1 ]; then
  printf 'Type "publish" to continue: '
  reply=""
  read -r reply || true
  [ "$reply" = "publish" ] || die "not confirmed; nothing was pushed"
fi

echo "==> pushing"
if [ -n "$CURRENT" ]; then
  git -C "$STAGE" push "$REMOTE_URL" "$BRANCH:refs/heads/$BRANCH" \
    --force-with-lease="refs/heads/$BRANCH:$CURRENT"
else
  # Plain push: if someone created the branch since the look above, this fails
  # rather than overwrites.
  git -C "$STAGE" push "$REMOTE_URL" "$BRANCH:refs/heads/$BRANCH"
fi

echo
echo "==> published $PUBLISHED"
case "$REMOTE_URL" in
  *github.com[:/]*)
    slug="${REMOTE_URL#*github.com[:/]}"
    slug="${slug%.git}"
    echo "    once Settings > Pages is set to deploy from $BRANCH (root):"
    echo "    https://${slug%%/*}.github.io/${slug#*/}/"
    ;;
esac
