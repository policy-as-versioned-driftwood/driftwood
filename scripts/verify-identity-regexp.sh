#!/usr/bin/env bash
# Proves EXPECTED_IDENTITY_REGEXP (release.yml) matches only what it should:
# main and a release/<major>.<minor>.x maintenance branch, anchored to this
# repo's own org/repo/workflow path -- nothing foreign. Ticket cs-14.
#
# gitsign's --certificate-identity-regexp is RE2; this pattern uses only
# anchors, escaped literal dots, a character class and alternation, all of
# which POSIX ERE (bash's =~ / grep -E) evaluates identically, so this local
# check is a faithful stand-in for the real gitsign match without needing a
# live signed tag.
set -euo pipefail

REGEXP=$(grep -E '^ *EXPECTED_IDENTITY_REGEXP:' "$(dirname "${BASH_SOURCE[0]}")/../.github/workflows/release.yml" \
  | sed -E 's/^ *EXPECTED_IDENTITY_REGEXP: *//')

fail() { echo "FAIL: $*" >&2; exit 1; }

should_match() {
  echo "$1" | grep -qE "$REGEXP" || fail "expected to MATCH, didn't: $1"
  echo "OK match:     $1"
}

should_not_match() {
  echo "$1" | grep -qE "$REGEXP" && fail "expected to NOT match, did: $1"
  echo "OK no-match:  $1"
}

echo "regexp under test: $REGEXP"
echo

# (a) real identities that must keep verifying
should_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main"
should_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/release/1.0.x"
should_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/release/2.10.x"

# (b) foreign org/repo/path must NOT match
should_not_match "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main"
should_not_match "https://github.com/evil/driftwood/.github/workflows/cut-release.yml@refs/heads/main"
should_not_match "https://github.com/policy-as-versioned-driftwood/other-repo/.github/workflows/cut-release.yml@refs/heads/main"
should_not_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/other.yml@refs/heads/main"
should_not_match "https://evil.com/https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main"
should_not_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main.evil.com"
should_not_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/maint/1.0.x"
should_not_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/release/x.y.x"

echo
echo "PASS: EXPECTED_IDENTITY_REGEXP matches main + release/<major>.<minor>.x only, anchored to this repo."
