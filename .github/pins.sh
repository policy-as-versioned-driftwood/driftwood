#!/usr/bin/env bash
# Check out the three pins of a party file and verify each one.
# Usage: pins.sh <party.json> <directory>. Each pin lands in <directory>/<name>.
set -euo pipefail
party=$1
mkdir -p "$2"
dest=$(cd "$2" && pwd)
pin_line='^    "(platform|ico|feeds)": \{"repo": "(policy-as-versioned-[a-z]+/[a-z]+)", "ref": "([A-Za-z0-9._/-]+)", "commit": "([0-9a-f]{40})"\},?$'
refuse() { echo "refused: $*" >&2; exit 1; }

count=0
while IFS= read -r line; do
  [[ $line =~ $pin_line ]] || continue
  name=${BASH_REMATCH[1]} repo=${BASH_REMATCH[2]} ref=${BASH_REMATCH[3]} commit=${BASH_REMATCH[4]}
  dir="$dest/$name"
  git clone --quiet "https://github.com/$repo" "$dir"
  git -C "$dir" checkout --quiet --detach "$commit"
  [ "$(git -C "$dir" rev-parse HEAD)" = "$commit" ] || refuse "$name is not at $commit"
  if [[ $ref =~ v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
    # A tag: it must resolve to the pinned commit and carry the publisher's signature.
    [ "$(git -C "$dir" rev-parse "refs/tags/$ref^{commit}")" = "$commit" ] || refuse "$name: tag $ref is not $commit"
    if [ ! -x "$dest/gitsign" ]; then
      curl -fsSL -o "$dest/gitsign" https://github.com/sigstore/gitsign/releases/download/v0.17.1/gitsign_0.17.1_linux_amd64
      echo "69213a8a0813a151e5a47d0060862952ff833a845d57309dff76f7ba6600abae  $dest/gitsign" | sha256sum -c -
      chmod +x "$dest/gitsign"
    fi
    (cd "$dir" && GITSIGN_REKOR_MODE=offline "$dest/gitsign" verify-tag "$ref" --certificate-oidc-issuer=https://token.actions.githubusercontent.com --certificate-identity-regexp="^https://github\.com/${repo}/\.github/workflows/cut-release\.yml@refs/heads/main$")
  else
    # A branch: the pinned commit must have landed on it.
    git -C "$dir" merge-base --is-ancestor "$commit" "origin/$ref" || refuse "$name: $commit is not on $ref"
  fi
  count=$((count + 1))
done < "$party"
[ "$count" -eq 3 ] || refuse "$party does not hold three pin lines"
