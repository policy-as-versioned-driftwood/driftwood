#!/usr/bin/env bash
# complete-feed-bump.sh -- eco-system ticket 61. Renovate runs this as a
# postUpgradeTasks command on its own bump branch, after it has edited the
# pin. A pin bump alone can never go green: shift-left's compose-check job
# recomposes on every pull request and fails on any drift against the
# committed composed/ copy, so the pin, party.yaml's inherits entry and the
# composed/ re-render must move in the SAME commit. This script is that
# completion: it re-renders composed/ in the working tree, and Renovate's
# fileFilters (composed/**) fold the render into the bump commit.
#
# The parent checkout refs mirror shift-left.yml's compose-check job exactly,
# on purpose: platform and nist at this tree's OWN pins (so a platform bump
# branch composes against the version it proposes), ico at main and the two
# feed parents at main -- their ticket-57 default branch (no Flux pin exists
# yet -- ticket 62 owns pinning them; when it lands, both jobs move together).
#
# A refusal from composition.py exits non-zero here, which surfaces on the
# Renovate PR as a failed post-upgrade task instead of a silently stale
# composed/ -- "a refusal is the most valuable output the gate produces".
set -euo pipefail

python3 -c 'import yaml' 2>/dev/null || pip install --quiet pyyaml

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# read-two-pins.py prints platform_tag=... / nist_tag=... lines (ticket 18).
eval "$(python3 .github/scripts/read-two-pins.py \
  gitops/platform/platform-pin.yaml platform \
  gitops/flux-system/gotk-sync-nist.yaml nist)"

# Full history, deliberately: composition resolves an UNPINNED parent's sha
# with `git log` on the version-scoped subdirectory -- the last commit that
# touched it. A --depth 1 clone only holds the tip, so every such lookup
# flattens to the tip commit and compose-check refuses the render as drift
# (this exact defect, caught by compose-check on the prep PR, 2026-09-01).
clone() { git clone --quiet --branch "$2" "https://github.com/policy-as-versioned-$1/$1" "$work/$1"; }
clone platform "$platform_tag"
clone nist     "$nist_tag"
clone ico      main
clone feeds    main
clone insurer  main

# Compose TWICE, deliberately. Composition reads the previous composed
# HEADER from disk to fill each price entry's old_version, so a single run
# here would commit a transition record (old_version v1, new_version v2)
# that the NEXT recompose -- compose-check on this PR, and on every PR
# after the merge -- can never reproduce, failing the drift check forever.
# The committed artefact must be the settled fixpoint (old == new); the
# pull request diff itself is the record of the transition.
python3 "$work/platform/compose/composition.py" compose "$PWD" \
  --estate-clone "$work" --out "$PWD" > /dev/null
python3 "$work/platform/compose/composition.py" compose "$PWD" \
  --estate-clone "$work" --out "$PWD"

# --- the twin's derived artefacts follow the pin, in the SAME commit (ticket 72) ---
# The first real bump (PR #20, threat-register v1 -> v2) moved party.yaml and
# composed/ together and left twin/forward-intel/v1/feed.json carrying
# derived_from version 1 and twin/signals.yaml carrying the v1 row: two gate
# checks red on every TRUTH run after it. Both are DERIVED from party.yaml's
# inherits[], so the completer derives them here and renovate.json's
# fileFilters (twin/forward-intel/**, twin/signals.yaml) fold them into the
# bump commit. This is a Renovate pull request a human merges, not a clock
# committing a declaration, so ADR-0024 D1 is untouched; twin-sweep.yml stays
# as the day-after safety net for an overlay that moves on its own.
#
# The signal lookup: rewrite each moved pin's row (version, id token, date);
# a pin with no row, or a row with no pin, is refused -- a human writes those.
python3 .github/scripts/rederive-signals.py

# The forward-intel feed: emit-forward-intel.py finds the hub's `twin` package
# by walking UP from the overlay (it does not self-version yet, ticket 29), and
# Renovate's branch workdir has no hub above it. So the hub is cloned into
# $work and the overlay's inputs are copied to the path clone-estate.sh would
# assemble -- the same plant verify-twin-overlay.sh uses -- rendered there, and
# the one output copied back. A copy, not a symlink: the emitter resolves
# symlinks before it walks, so a link would land it back here, hub-less.
git clone --quiet --depth 1 --branch main \
  "https://github.com/policy-as-versioned-flux/policy-as-versioned-flux" "$work/hub"
mirror="$work/hub/.estate-clone/driftwood"
mkdir -p "$mirror"
cp -R twin selection-policy party.yaml "$mirror/"
python3 "$mirror/twin/emit-forward-intel.py"
cp "$mirror/twin/forward-intel/v1/feed.json" twin/forward-intel/v1/feed.json
