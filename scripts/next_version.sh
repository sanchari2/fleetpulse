#!/usr/bin/env bash
# Work out the next SemVer from Conventional Commits.
#
#   scripts/next_version.sh                 # commits since the last tag, current version from git
#   scripts/next_version.sh --range HEAD~5..HEAD
#   echo "feat: x" | scripts/next_version.sh --stdin --current 1.2.3
#
# Rules
#   * `type!:` or a `BREAKING CHANGE:` footer  -> major
#   * `feat:`                                  -> minor
#   * `fix:` / `perf:` / `refactor:`           -> patch
#   * anything else (chore, docs, ci, test)    -> no bump, the current version is printed
#
# Prints the bare version on stdout, and also writes `version=<v>` to
# $GITHUB_OUTPUT when that is set, so a workflow step can consume it.
set -euo pipefail

usage() {
  cat <<'EOF'
usage: next_version.sh [--current X.Y.Z] [--range GITRANGE] [--stdin]

  --current   base version instead of `git describe --tags --abbrev=0`
  --range     commit range to read, e.g. v0.1.0..HEAD
  --stdin     read commit messages from stdin instead of git
EOF
}

CURRENT=""
RANGE=""
FROM_STDIN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --current)
      CURRENT="${2:-}"
      [[ -n "$CURRENT" ]] || { echo "next_version: --current needs a value" >&2; exit 2; }
      shift 2
      ;;
    --range)
      RANGE="${2:-}"
      [[ -n "$RANGE" ]] || { echo "next_version: --range needs a value" >&2; exit 2; }
      shift 2
      ;;
    --stdin)
      FROM_STDIN=1
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "next_version: unknown argument '$1'" >&2
      usage >&2
      exit 2
      ;;
  esac
done

LAST_TAG=""
if LAST_TAG="$(git describe --tags --abbrev=0 2>/dev/null)"; then
  :
else
  LAST_TAG=""
fi

if [[ -z "$CURRENT" ]]; then
  if [[ -n "$LAST_TAG" ]]; then
    CURRENT="${LAST_TAG#v}"
  else
    CURRENT="0.0.0"
  fi
fi

if [[ ! "$CURRENT" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "next_version: '$CURRENT' is not a SemVer version (expected X.Y.Z)" >&2
  exit 1
fi

if [[ $FROM_STDIN -eq 1 ]]; then
  MESSAGES="$(cat)"
elif [[ -n "$RANGE" ]]; then
  MESSAGES="$(git log "$RANGE" --no-merges --pretty=%B)"
elif [[ -n "$LAST_TAG" ]]; then
  MESSAGES="$(git log "${LAST_TAG}..HEAD" --no-merges --pretty=%B)"
else
  MESSAGES="$(git log --no-merges --pretty=%B 2>/dev/null || true)"
fi

BUMP="none"
while IFS= read -r line; do
  # breaking change footer
  if [[ "$line" =~ ^BREAKING[[:space:]-]CHANGE: ]]; then
    BUMP="major"
    break
  fi
  # type(scope)!: subject
  if [[ "$line" =~ ^[A-Za-z]+(\([^\)]*\))?!:[[:space:]] ]]; then
    BUMP="major"
    break
  fi
  if [[ "$BUMP" != "minor" && "$line" =~ ^feat(\([^\)]*\))?:[[:space:]] ]]; then
    BUMP="minor"
  fi
  if [[ "$BUMP" == "none" && "$line" =~ ^(fix|perf|refactor)(\([^\)]*\))?:[[:space:]] ]]; then
    BUMP="patch"
  fi
done <<< "$MESSAGES"

IFS='.' read -r MAJOR MINOR PATCH <<< "$CURRENT"
case "$BUMP" in
  major)
    MAJOR=$((MAJOR + 1))
    MINOR=0
    PATCH=0
    ;;
  minor)
    MINOR=$((MINOR + 1))
    PATCH=0
    ;;
  patch)
    PATCH=$((PATCH + 1))
    ;;
  none)
    ;;
esac

NEXT="${MAJOR}.${MINOR}.${PATCH}"

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
  echo "version=${NEXT}" >> "$GITHUB_OUTPUT"
  echo "bump=${BUMP}" >> "$GITHUB_OUTPUT"
fi

echo "$NEXT"
