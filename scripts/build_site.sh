#!/usr/bin/env bash
#
# Build a self-contained copy of the front end that a reviewer can open.
#
# WHAT THIS IS FOR. The repository is private and a clone cannot regenerate the
# export: `var/` holds the ledger, the runs and the scoring passes, and none of
# it is committed. So a reviewer who clones sees the No-export panel and nothing
# else. This produces a directory that can be served anywhere, with the data in
# it, and nothing else to install.
#
# WITHOUT THE PRICE SERIES. `--no-prices` leaves out the 62,990 daily closes in
# `prices/` — the only third-party market data published here in bulk, and 47% of
# the payload. The company page states the absence it already knows how to state;
# every other figure is untouched, because the journal and the scoring records
# carry their own closes. See `docs/publishing.md` for what does remain.
#
# IT DOES NOT DEPLOY. It writes `site/` and stops. Publishing is a separate,
# deliberate act — see the bottom of this file for the one command that does it,
# commented out on purpose.
#
#   scripts/build_site.sh              # -> site/
#   scripts/build_site.sh --with-prices   # the full 5.5 MB export
#
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/site"
PRICES="--no-prices"

for arg in "$@"; do
  case "$arg" in
    --with-prices) PRICES="" ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

cd "$ROOT"

echo "==> checking the tree is committed"
# The export stamps the commit it was built from, and a dirty forecast root
# records no digest at all (see mapf.core.provenance). A published copy whose
# manifest says `forecast_digest: null` cannot be tied to any code.
if [ -n "$(git status --porcelain -- config src/mapf)" ]; then
  echo "    refusing: config/ or src/mapf/ has uncommitted changes." >&2
  echo "    The export would record no forecast digest and the published copy" >&2
  echo "    could not be tied to a commit. Commit first." >&2
  exit 1
fi
echo "    clean at $(git rev-parse --short HEAD)"

echo "==> both suites"
uv run pytest -q >/dev/null
node --test ui/tests/*.test.mjs >/dev/null
echo "    python and front end pass"

echo "==> export into the working copy"
uv run map export $PRICES >/dev/null
echo "    $(du -sh ui/assets/export | cut -f1) at ui/assets/export"

echo "==> computed styles, in a browser"
# Skips itself (exit 2) when Playwright is not installed; a build should not
# depend on it, but it should use it when it is there.
set +e
node ui/tests/styles.probe.mjs
probe=$?
set -e
case $probe in
  0) echo "    probe passed" ;;
  2) echo "    probe skipped (no Playwright)" ;;
  *) echo "    probe FAILED — not building a copy with broken styling" >&2; exit 1 ;;
esac

echo "==> assembling $OUT"
rm -rf "$OUT"
mkdir -p "$OUT"
# Everything the pages fetch, and nothing else. No tests, no design notes, no
# screenshots: this is the thing a stranger loads, not the thing we work in.
cp ui/*.html "$OUT/"
cp -R ui/assets "$OUT/assets"
rm -rf "$OUT/assets/export/.DS_Store"

cat > "$OUT/robots.txt" <<'EOF'
# A research artifact, not a publication. Not for indexing.
User-agent: *
Disallow: /
EOF

echo "==> built"
du -sh "$OUT"
echo "    pages:  $(ls "$OUT"/*.html | wc -l | tr -d ' ')"
echo "    export: $(du -sh "$OUT/assets/export" | cut -f1)"
echo "    commit: $(git rev-parse --short HEAD)"
echo
echo "Serve it locally to check:"
echo "    python3 -m http.server -d $OUT 8000"
echo
echo "DEPLOYING IS A SEPARATE DECISION and this script does not make it."
echo "The repository is private; a hosted page is public. When you decide:"
echo
echo "    # netlify deploy --dir=site --prod"
echo "    # vercel deploy site --prod"
echo "    # rsync -av --delete site/ user@host:/var/www/map/"
