#!/usr/bin/env bash
# Behavioural tests for scripts/next_version.sh.
# Run directly (`bash tests/test_next_version.sh`) or via pytest, which shells
# out to this file so one command covers everything.
set -uo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/scripts/next_version.sh"
FAILURES=0
CHECKS=0

fail() {
  echo "  FAIL: $1" >&2
  FAILURES=$((FAILURES + 1))
}

check() {
  local name="$1" expected="$2" messages="$3" current="${4:-1.2.3}"
  CHECKS=$((CHECKS + 1))
  local actual
  actual="$(printf '%s\n' "$messages" | bash "$SCRIPT" --stdin --current "$current" 2>&1)"
  if [[ "$actual" != "$expected" ]]; then
    fail "$name: expected '$expected', got '$actual'"
  else
    echo "  ok: $name"
  fi
}

echo "next_version.sh"
check "feat bumps minor" "1.3.0" "feat: add battery endpoint"
check "fix bumps patch" "1.2.4" "fix: correct threshold"
check "perf bumps patch" "1.2.4" "perf: faster ingest"
check "refactor bumps patch" "1.2.4" "refactor: split store"
check "bang marks breaking" "2.0.0" "feat!: drop v1 payload"
check "breaking change footer" "2.0.0" "feat: new shape
BREAKING CHANGE: telemetry payload changed"
check "chore alone does not bump" "1.2.3" "chore: bump deps"
check "docs alone does not bump" "1.2.3" "docs: fix readme"
check "feat beats fix" "1.3.0" "fix: a
feat: b"
check "breaking beats feat" "2.0.0" "feat: a
feat!: b"
check "scoped types are recognised" "1.3.0" "feat(api): scoped"
check "first release from zero" "0.1.0" "feat: initial service" "0.0.0"
check "zero base with fix" "0.0.1" "fix: patch first" "0.0.0"
check "multi-digit rollover" "1.10.0" "feat: x" "1.9.7"
check "major resets minor and patch" "3.0.0" "fix!: x" "2.7.4"
check "empty input keeps version" "1.2.3" ""

CHECKS=$((CHECKS + 1))
if bash "$SCRIPT" --help >/dev/null 2>&1; then
  echo "  ok: --help exits 0"
else
  fail "--help should exit 0"
fi

CHECKS=$((CHECKS + 1))
if printf 'fix: x\n' | bash "$SCRIPT" --stdin --current "one.two.three" >/dev/null 2>&1; then
  fail "invalid --current should exit non-zero"
else
  echo "  ok: invalid version exits non-zero"
fi

CHECKS=$((CHECKS + 1))
printf 'fix: x\n' | bash "$SCRIPT" --stdin --current "1.2.3" >/dev/null 2>&1
set +e
printf 'fix: x\n' | bash "$SCRIPT" --stdin --nonsense >/dev/null 2>&1
code=$?
set -e
if [[ "$code" -eq 2 ]]; then
  echo "  ok: unknown argument exits 2"
else
  fail "unknown argument should exit 2, got $code"
fi

CHECKS=$((CHECKS + 1))
OUTPUT_FILE="$(mktemp)"
GITHUB_OUTPUT="$OUTPUT_FILE" bash "$SCRIPT" --stdin --current "1.2.3" <<< "feat: x" >/dev/null
if grep -q '^version=1.3.0$' "$OUTPUT_FILE" && grep -q '^bump=minor$' "$OUTPUT_FILE"; then
  echo "  ok: writes version and bump to GITHUB_OUTPUT"
else
  fail "GITHUB_OUTPUT was not written correctly: $(cat "$OUTPUT_FILE")"
fi
rm -f "$OUTPUT_FILE"

echo
if [[ "$FAILURES" -gt 0 ]]; then
  echo "$FAILURES of $CHECKS checks failed" >&2
  exit 1
fi
echo "all $CHECKS checks passed"
