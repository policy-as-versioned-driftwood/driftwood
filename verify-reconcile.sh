#!/usr/bin/env bash
# Beat: "driftwood reconciles from a pinned, signed GitRepository, healthily."
# Run after scripts/up.sh. Three outcomes only:
#   PASS (exit 0)  every assertion observed true
#   FAIL (exit 1)  an assertion observed false
#   SKIP (exit 3)  could not look: no docker, no kind cluster, Flux not Ready
source "$(dirname "${BASH_SOURCE[0]}")/scripts/lib.sh"
need_substrate

fail() { echo "FAIL: $*" >&2; exit 1; }
ready() { # kind/name/ns -> asserts Ready=True
  local got
  got=$(live "$3" "$1" "$2" '{.status.conditions[?(@.type=="Ready")].status}')
  [ "$got" = True ] || fail "$1/$2 Ready=$got (want True)"
}
live() { kubectl --context "$CTX" --request-timeout=20s -n "$1" get "$2" "$3" -o "jsonpath=$4" 2>/dev/null; }
want() { [ "$1" = "$2" ] || fail "$3: live '$1', gitops pins '$2'"; }

# Expected values are READ from the checked-in gitops tree, never hardcoded.
# flux-system/* is applied straight from the working tree. apps/* is what Flux
# reconciles from the self-pin tag, so those are read from that tag's tree
# (a tag cannot carry its own commit, so the working tree is never what the
# cluster reconciles).
field() { sed -n "s/^ *$1: *\"\{0,1\}\([^\" #]*\)\"\{0,1\}.*/\1/p" | sed 1q; }
pin()   { field "$2" < "$GITOPS_DIR/flux-system/$1"; }
SELF_TAG=$(pin gotk-sync.yaml tag);           SELF_COMMIT=$(pin gotk-sync.yaml commit)
NIST_TAG=$(pin gotk-sync-nist.yaml tag);      NIST_COMMIT=$(pin gotk-sync-nist.yaml commit)
PLATFORM_TAG=$(field tag < "$GITOPS_DIR/platform/platform-pin.yaml")
PLATFORM_COMMIT=$(field commit < "$GITOPS_DIR/platform/platform-pin.yaml")
at_pin() { git -C "$HERE" show "$SELF_TAG:gitops/apps/$1" 2>/dev/null || fail "tag $SELF_TAG (the self-pin) is not in this clone; fetch tags"; }
WANT_VERSION=$(at_pin version-configmap.yaml | field policyVersion)
WANT_CATALOG=$(at_pin nist-pin-configmap.yaml | field catalogVersion)
[ -n "$SELF_TAG$NIST_TAG$WANT_VERSION$WANT_CATALOG" ] || fail "could not read the pins from $GITOPS_DIR"

say "1. GitRepository is Ready and pinned to $SELF_TAG @ ${SELF_COMMIT:-<no commit pinned in gotk-sync.yaml>}"
ready gitrepository driftwood flux-system
want "$(live flux-system gitrepository driftwood '{.spec.ref.tag}')" "$SELF_TAG" "GitRepository tag"
c=$(live flux-system gitrepository driftwood '{.spec.ref.commit}')
grep -qE '^[0-9a-f]{40}$' <<<"$c" || fail "GitRepository commit not pinned (got '$c')"
[ -z "$SELF_COMMIT" ] || want "$c" "$SELF_COMMIT" "GitRepository commit"

say "2. Kustomization is Ready (reconcile healthy)"
ready kustomization driftwood flux-system

say "3. the reconciled content actually landed in the cluster (tree at $SELF_TAG)"
kubectl --context "$CTX" --request-timeout=20s get ns driftwood >/dev/null 2>&1 || fail "namespace 'driftwood' not reconciled"
want "$(live driftwood cm driftwood-live-version '{.data.policyVersion}')" "$WANT_VERSION" "live version configmap"

say "4. the pinned nist (regulator) dependency reconciled healthy at $NIST_TAG @ $NIST_COMMIT"
ready gitrepository nist flux-system
want "$(live flux-system gitrepository nist '{.spec.ref.tag}')" "$NIST_TAG" "nist GitRepository tag"
want "$(live flux-system gitrepository nist '{.spec.ref.commit}')" "$NIST_COMMIT" "nist GitRepository commit"
want "$(live driftwood cm driftwood-nist-pin '{.data.catalogVersion}')" "$WANT_CATALOG" "nist-pin configmap"

say "5. the platform pin (opt-in) matches gitops/platform/platform-pin.yaml when applied"
if live flux-system gitrepository platform '{.metadata.name}' | grep -qx platform; then
  want "$(live flux-system gitrepository platform '{.spec.ref.tag}')" "$PLATFORM_TAG" "platform GitRepository tag"
  want "$(live flux-system gitrepository platform '{.spec.ref.commit}')" "$PLATFORM_COMMIT" "platform GitRepository commit"
else
  echo "   platform GitRepository not applied on $CTX (opt-in, see platform-pin.yaml); nothing to compare"
fi

echo "PASS: driftwood reconciles from a pinned GitRepository ($SELF_TAG), healthy, content live, nist dependency pinned ($NIST_TAG)."
