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
# Parent checkouts use the same exact pins as CI. Compiler software has its
# own pin; updating it never changes the implementation policy window.
#
# A refusal from composition.py exits non-zero here, which surfaces on the
# Renovate PR as a failed post-upgrade task instead of a silently stale
# composed/ -- "a refusal is the most valuable output the gate produces".
set -euo pipefail

python3 -c 'import yaml' 2>/dev/null || pip install --quiet pyyaml

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT

# Read the same six tag/SHA pairs as CI; no moving publisher branches.
eval "$(python3 .github/scripts/read-pins.py \
  .github/platform-tools-pin.yaml tools \
  gitops/platform/platform-pin.yaml platform \
  gitops/flux-system/gotk-sync-nist.yaml nist \
  gitops/flux-system/gotk-sync-ico.yaml ico \
  gitops/flux-system/gotk-sync-feeds.yaml feeds \
  gitops/flux-system/gotk-sync-insurer.yaml insurer)"
clone() { git clone --quiet --branch "$2" "https://github.com/policy-as-versioned-$1/$1" "$work/${3:-$1}"; }
clone platform "$tools_tag" platform-tools
clone platform "$platform_tag"
clone nist "$nist_tag"
clone ico "$ico_tag"
clone feeds "$feeds_tag"
clone insurer "$insurer_tag"
python3 .github/scripts/verify-pinned-checkouts.py \
  gitops/platform/platform-pin.yaml "$work/platform" \
  gitops/flux-system/gotk-sync-nist.yaml "$work/nist" \
  gitops/flux-system/gotk-sync-ico.yaml "$work/ico" \
  gitops/flux-system/gotk-sync-feeds.yaml "$work/feeds" \
  gitops/flux-system/gotk-sync-insurer.yaml "$work/insurer"
# gitsign must be installed on the Renovate runner; the tool runner refuses
# missing verifiers and rejects an incorrect release identity before execution.

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

# Render against the exact published hub_commit in twin/PIN.yaml, never
# whatever happens to be on main. A temporary mirror supplies the emitter's
# hub layout, and only its declared current VERSION's feed is copied back.
python3 .github/scripts/refresh-twin-feed.py "$work/hub"

# All nonhidden twin inputs above participate in tools5's comparison identity.
# Compose after deriving them so the committed output replays from this source.
# Compose TWICE with the existing authenticated runner, after all derived inputs.
# Both passes see the same final source; the second publishes the settled output.
python3 .github/scripts/platform-tools.py --tools-dir "$work/platform-tools" compose "$PWD" \
  --estate-clone "$work" --out "$PWD" > /dev/null
python3 .github/scripts/platform-tools.py --tools-dir "$work/platform-tools" compose "$PWD" \
  --estate-clone "$work" --out "$PWD"
