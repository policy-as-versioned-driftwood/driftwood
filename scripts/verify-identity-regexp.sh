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

# (c) the PROPOSER's identity is not a publisher's identity (ticket 78).
#     propose-tier.yml signs cage-tier proposal COMMITS with this repo's own
#     Actions identity; a release TAG must never verify under it, or a workflow
#     that may only propose could publish.
should_not_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main"

echo
echo "PASS: EXPECTED_IDENTITY_REGEXP matches main + release/<major>.<minor>.x only, anchored to this repo."

echo
echo "== 3. EXPECTED_PROPOSAL_IDENTITY_REGEXP (propose-tier.yml -- the cage-tier proposal commit, ticket 78) =="
# A SECOND constant, deliberately not an alternation widened into the one above:
# the proposal commit and the release tag are different powers, and the identity
# that may propose a tighter cage must not be the identity that may publish.
PROPOSAL_REGEXP=$(grep -E '^ *EXPECTED_PROPOSAL_IDENTITY_REGEXP:' .github/workflows/propose-tier.yml \
  | sed -E 's/^ *EXPECTED_PROPOSAL_IDENTITY_REGEXP: *//')
[ -n "$PROPOSAL_REGEXP" ] || fail "no EXPECTED_PROPOSAL_IDENTITY_REGEXP in propose-tier.yml -- the proposal commit's signature would be verified against nothing"
echo "regexp under test: $PROPOSAL_REGEXP"

proposal_match() {
  echo "$1" | grep -qE "$PROPOSAL_REGEXP" || fail "expected to MATCH the proposal regexp, didn't: $1"
  echo "OK match:     $1"
}
proposal_no_match() {
  echo "$1" | grep -qE "$PROPOSAL_REGEXP" && fail "expected to NOT match the proposal regexp, did: $1"
  echo "OK no-match:  $1"
}

# (a) what propose-tier.yml's own run actually presents. `refs/heads/main` is the
#     ref the WORKFLOW runs on (schedule, dispatch, merged pin bump), never the
#     `wargamer/retune-*` branch it writes.
proposal_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main"

# (b) the publisher's identity must NOT verify a proposal, and neither may a
#     maintenance branch, a foreign org/repo/path, or a smuggled prefix/suffix
proposal_no_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main"
proposal_no_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/twin-sweep.yml@refs/heads/main"
proposal_no_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/release/1.0.x"
proposal_no_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/wargamer/retune-tier-driftwood-cage-tier-feeds-feed"
proposal_no_match "https://github.com/policy-as-versioned-tuppence/tuppence/.github/workflows/propose-tier.yml@refs/heads/main"
proposal_no_match "https://github.com/policy-as-versioned-driftwood/other-repo/.github/workflows/propose-tier.yml@refs/heads/main"
proposal_no_match "https://evil.com/https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main"
proposal_no_match "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main.evil.com"
proposal_no_match "https://githubXcom/policy-as-versioned-driftwood/driftwood/.github/workflows/propose-tier.yml@refs/heads/main"

echo
echo "PASS: EXPECTED_PROPOSAL_IDENTITY_REGEXP matches only this repo's propose-tier.yml on main, and the release and proposal identities do not overlap."
