#!/usr/bin/env bash
# Publish docs/wiki/ to the GitHub wiki.
#
# The wiki is a second git repository, github.com/<owner>/<repo>.wiki.git, and
# GitHub only creates it once the wiki has been initialised. If this fails with
# "Repository not found", open the repository's Wiki tab and save any page once;
# from then on this script owns the content.
#
# The source of truth is docs/wiki/ in the main repository, so wiki pages are
# reviewed in pull requests like anything else.
set -euo pipefail

REPO="${1:-https://github.com/GiladBronshtein/verba.wiki.git}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

git clone --depth 1 "$REPO" "$WORK/wiki"
rm -f "$WORK"/wiki/*.md
cp "$HERE"/docs/wiki/*.md "$WORK/wiki/"

cd "$WORK/wiki"
if git diff --quiet && git diff --cached --quiet && [ -z "$(git status --porcelain)" ]; then
  echo "wiki already matches docs/wiki"
  exit 0
fi
git add -A
git commit -m "docs: sync wiki from docs/wiki"
git push
echo "published $(ls "$HERE"/docs/wiki/*.md | wc -l | tr -d ' ') pages"
