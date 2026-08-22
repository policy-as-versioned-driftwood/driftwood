#!/usr/bin/env bash
# Proves EXPECTED_IDENTITY_REGEXP (release.yml) matches only what it should:
# main and a release/<major>.<minor>.x maintenance branch, anchored to this
# repo's own org/repo/workflow path -- nothing foreign. Ticket cs-14.
#
# Two layers of proof:
#
# (1) Real: every existing v*.*.* tag is verified with the actual gitsign
#     binary against the actual regexp release.yml uses, exactly as
#     release.yml's own verify step does. This is the load-bearing check --
#     it exercises gitsign's real RE2 matcher against a real Fulcio/Rekor
#     signature, not a stand-in for it.
#
# (2) Synthetic: foreign org/repo/path/ref shapes that must NOT match can't
#     be exercised for real (we don't hold a signing identity for a foreign
#     org, and shouldn't want one) so those are checked with grep -E instead.
#     gitsign's --certificate-identity-regexp is RE2; this pattern uses only
#     anchors, escaped literal dots, a character class and alternation, all
#     of which POSIX ERE (grep -E) evaluates identically to RE2, so this is
#     a faithful stand-in for the real matcher on the negative cases only --
#     it is deliberately not asked to carry the positive proof.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

REGEXP=$(grep -E '^ *EXPECTED_IDENTITY_REGEXP:' .github/workflows/release.yml \
  | sed -E 's/^ *EXPECTED_IDENTITY_REGEXP: *//')
ISSUER=$(grep -E '^ *EXPECTED_ISSUER:' .github/workflows/release.yml \
  | sed -E 's/^ *EXPECTED_ISSUER: *//')

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "== 1. real signed tags verify with gitsign itself =="
command -v gitsign >/dev/null || fail "gitsign not on PATH -- install it (see release.yml for pinned version) before running this check"

git fetch --tags --force >/dev/null 2>&1 || true
tags=$(git tag -l 'v*.*.*')
if [ -z "$tags" ]; then
  echo "no v*.*.* tags exist yet in this clone -- nothing signed to verify (not a failure, just nothing to prove yet)"
else
  while IFS= read -r tag; do
    gitsign verify-tag "$tag" \
      --certificate-identity-regexp="$REGEXP" \
      --certificate-oidc-issuer="$ISSUER" \
      || fail "real gitsign verify-tag failed for $tag against EXPECTED_IDENTITY_REGEXP -- this is exactly what release.yml runs on tag push"
    echo "OK gitsign verified: $tag"
  done <<< "$tags"
fi
echo

should_match() {
  echo "$1" | grep -qE "$REGEXP" || fail "expected to MATCH, didn't: $1"
  echo "OK match:     $1"
}

should_not_match() {
  echo "$1" | grep -qE "$REGEXP" && fail "expected to NOT match, did: $1"
  echo "OK no-match:  $1"
}

echo "== 2. synthetic RE2-equivalent shapes (identities we can't/shouldn't real-sign) =="
echo "regexp under test: $REGEXP"
echo

# (a) real identity shapes that must keep matching (belt-and-braces alongside
#     the real gitsign proof above, which is the load-bearing one)
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
