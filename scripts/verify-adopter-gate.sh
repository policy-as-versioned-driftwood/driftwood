#!/usr/bin/env bash
# driftwood's adopter gate, exercised against the artefact it actually
# verifies. Eco-system ticket 101, 2026-09-06.
#
# WHY THIS FILE EXISTS. Until 2026-09-05 driftwood carried
# verify-reconcile.sh and verify-twin-overlay.sh and NO harness for its
# adopter gate, so nothing in the estate had ever run it -- and driftwood's
# gate is the one whose reading of ADR-0011 the other two adopters were
# changed to match. The hub's verify-fold-agreement.sh now runs all three
# gates over planted movements, but its subject is AGREEMENT between three
# gates, not this gate's own behaviour in depth. This is that.
#
# WHAT IS MEASURED, AND AGAINST WHAT.
#   served artefact   platform's own committed computed-semver/evidence/
#                     <version>.json[.bundle] at the tag THIS repository
#                     pins, read out of a real clone of platform.
#   operation         .github/scripts/adopter-gate.py's own `compose`
#                     subcommand, in the shape .github/workflows/
#                     shift-left.yml spells it (--adopter-dir/--base-ref/
#                     --head-ref, the ADR-0011 composed-member-set path),
#                     with the real `cosign` binary and this repository's
#                     own EXPECTED_PLATFORM_IDENTITY_REGEXP.
# Only the MOVEMENT is planted -- which versions this institution's composed
# member set names before and after -- because that is the thing a Renovate
# pull request changes. No evidence, no bundle, no certificate and no
# signature is fabricated anywhere in this file.
#
# Exit 0 true, 3 could-not-look (reason on the last line), other false.
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GATE="$HERE/.github/scripts/adopter-gate.py"
scratch="$(mktemp -d)"
trap 'rm -rf "$scratch"' EXIT

fail() { echo "FAIL: $*"; exit 1; }
skip() { echo "SKIP: $*"; exit 3; }
say() { echo; echo "== $* =="; }

command -v cosign > /dev/null \
  || skip "cosign is not installed, and every scenario here turns on the real binary verifying platform's real published bundles"
python3 -c 'import yaml' 2>/dev/null \
  || skip "python3 has no pyyaml, which adopter-gate.py needs to read the platform pin"

platform_repo="${PLATFORM_REPO:-$HERE/../platform}"
[ -d "$platform_repo/.git" ] \
  || skip "no clone of platform at $platform_repo (set PLATFORM_REPO=) -- this harness verifies platform's real published evidence and there is nothing to read"

git_t() { git -C "$1" -c user.email=t@example.invalid -c user.name=t \
             -c commit.gpgsign=false -c tag.gpgsign=false "${@:2}"; }

# ---------------------------------------------------------------------------
say "setup: a real clone of platform at the tag this repository pins"
# ---------------------------------------------------------------------------
pinned_tag=$(python3 - "$HERE/gitops/platform/platform-pin.yaml" <<'PY'
import sys, yaml
for doc in yaml.safe_load_all(open(sys.argv[1])):
    if isinstance(doc, dict) and doc.get("kind") == "GitRepository":
        print((doc.get("spec") or {}).get("ref", {}).get("tag", ""))
        break
PY
)
[ -n "$pinned_tag" ] || fail "could not read the pinned platform tag out of this repository's own gitops/platform/platform-pin.yaml"
echo "this repository pins platform $pinned_tag"

platform="$scratch/platform"
git clone --local --quiet "$platform_repo" "$platform"
git -C "$platform" config advice.detachedHead false
git -C "$platform" rev-parse -q --verify "refs/tags/${pinned_tag}^{commit}" > /dev/null \
  || skip "the clone of platform at $platform_repo carries no tag object for ${pinned_tag}, the tag this repository pins -- it is behind the estate"
pinned_commit=$(git -C "$platform" rev-parse "refs/tags/${pinned_tag}^{commit}")
git -C "$platform" -c advice.detachedHead=false checkout --quiet "$pinned_tag"

# The version whose real signed evidence every scenario below turns on:
# published by platform at this tag, with a committed bundle, and with its
# OWN computed bump below major -- so a real ACCEPT can be observed as an
# accept rather than through a designed composed-major refusal. Chosen from
# the tag's own tree on every run, never hard-coded.
version=$(python3 - "$platform" <<'PY'
import json, pathlib, sys
root = pathlib.Path(sys.argv[1]) / "computed-semver" / "evidence"
for doc in sorted(root.glob("*.json")):
    if not doc.with_suffix(".json.bundle").exists():
        continue
    try:
        computed = json.loads(doc.read_text())["bump"]["computed"]
    except Exception:
        continue
    if computed in ("none", "patch", "minor"):
        print(doc.name[:-5])
        break
PY
)
[ -n "$version" ] || skip "platform at ${pinned_tag} publishes no evidence document with a committed bundle whose own computed bump is none/patch/minor, so an ACCEPT here could not be told apart from the designed composed-major refusal"
evidence="$platform/computed-semver/evidence/${version}.json"
bundle="${evidence}.bundle"
[ -s "$bundle" ] || fail "no committed bundle at $bundle"
shape=$(python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print("legacy" if "base64Signature" in d else ("new" if "mediaType" in d else "unknown"))' "$bundle")
computed=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["bump"]["computed"])' "$evidence")
echo "the served artefact: platform's own evidence for policy ${version} at ${pinned_tag}"
echo "  bundle shape ${shape}; the publisher's own computed bump for it is '${computed}'"

# The planted movement lives in a throwaway copy of THIS repository's own
# composed artefact -- members only, which is all versions_from_composed_
# evidence() reads.
plant_adopter() {  # $1 dir, $2 base members (space separated), $3 head members
  local dir="$1"
  mkdir -p "$dir/composed" && git -C "$dir" init -q -b main
  members() { python3 -c '
import json, sys
print(json.dumps({"members": [{"name": "m-" + v, "version": v} for v in sys.argv[1:]]}, indent=1))
' $1; }
  members "$2" > "$dir/composed/evidence.json"
  git_t "$dir" add -A; git_t "$dir" commit -q -m "the composed member set before the pull request"
  members "$3" > "$dir/composed/evidence.json"
  git_t "$dir" add -A; git_t "$dir" commit -q --allow-empty -m "the composed member set this pull request proposes"
}

gate_compose() {  # $1 platform dir, $2 adopter dir, $3 out prefix -> exit code on stdout
  set +e
  python3 "$GATE" compose "$1" "$pinned_tag" "$pinned_tag" \
    --adopter-dir "$2" --base-ref HEAD~1 --head-ref HEAD \
    --out "$scratch/$3.json" --markdown-out "$scratch/$3.md" > "$scratch/$3.out" 2>&1
  local code=$?
  set -e
  echo "$code"
}

# ---------------------------------------------------------------------------
say "A: ADR-0001's pin is load-bearing -- verify-commit refuses a pin naming the wrong commit"
# ---------------------------------------------------------------------------
set +e
python3 "$GATE" verify-commit "$platform" "cccccccccccccccccccccccccccccccccccccccc" > "$scratch/a.out" 2>&1
a_code=$?
set -e
cat "$scratch/a.out"
[ "$a_code" -ne 0 ] || fail "A: a pin naming the wrong commit must be refused, got exit 0"
grep -q "$pinned_commit" "$scratch/a.out" || fail "A: the refusal does not name the commit platform actually resolves to"
python3 "$GATE" verify-commit "$platform" "$pinned_commit" > /dev/null 2>&1 \
  || fail "A: the REAL resolved commit must be accepted"
echo "OK  A: the real resolved commit is accepted and a wrong one is refused, naming both"

# ---------------------------------------------------------------------------
say "B: a pull request that moves nothing composes 'none' and reads no evidence at all"
# ---------------------------------------------------------------------------
b_adopter="$scratch/driftwood-b"
plant_adopter "$b_adopter" "4.0.0" "4.0.0"
b_code=$(gate_compose "$platform" "$b_adopter" b)
tail -5 "$scratch/b.out"
[ "$b_code" -eq 0 ] || fail "B: a movement of nothing must compose 'none' and pass, got exit $b_code"
grep -q "OK: composed bump is 'none'" "$scratch/b.out" || fail "B: the gate did not compose 'none'"
python3 - "$scratch/b.json" <<'PY' || fail "B: the gate read some version's evidence on a pull request that moved nothing"
import json, sys
doc = json.load(open(sys.argv[1]))
assert doc["evidence"] == {}, doc["evidence"]
PY
echo "OK  B: nothing moved, nothing was verified, composed 'none', exit 0"

# ---------------------------------------------------------------------------
say "C: the REAL ACCEPT -- policy ${version} arrives, and real cosign verifies platform's own published signature"
# ---------------------------------------------------------------------------
c_adopter="$scratch/driftwood-c"
plant_adopter "$c_adopter" "4.0.0" "4.0.0 ${version}"
c_code=$(gate_compose "$platform" "$c_adopter" c)
grep -vE '^\s*"' "$scratch/c.out" | tail -8
[ "$c_code" -eq 0 ] || fail "C: the gate did not accept platform's real published evidence for ${version} (exit $c_code): $(tail -2 "$scratch/c.out")"
grep -q "OK: composed bump is '${computed}'" "$scratch/c.out" \
  || fail "C: the composed bump is not the publisher's own signed '${computed}' for ${version}"
python3 - "$scratch/c.json" "$version" <<'PY' || fail "C: the run's own evidence output does not record a verified reading of the version that arrived"
import json, sys
doc = json.load(open(sys.argv[1]))
assert sys.argv[2] in doc["evidence"], sorted(doc["evidence"])
PY
echo "OK  C: real cosign ACCEPTED platform's own published signature for policy ${version} at ${pinned_tag}, under this repository's own identity constant, and the gate composed the publisher's own '${computed}'"

# ---------------------------------------------------------------------------
say "D: the REAL REFUSE -- the same real bundle with one signature byte changed"
# ---------------------------------------------------------------------------
d_platform="$scratch/platform-d"
cp -r "$platform" "$d_platform"
python3 - "$d_platform/computed-semver/evidence/${version}.json.bundle" <<'PY'
import json, sys
doc = json.load(open(sys.argv[1]))
if "base64Signature" in doc:
    s = doc["base64Signature"]
    doc["base64Signature"] = ("B" if s[0] != "B" else "C") + s[1:]
else:
    s = doc["messageSignature"]["signature"]
    doc["messageSignature"]["signature"] = ("B" if s[0] != "B" else "C") + s[1:]
json.dump(doc, open(sys.argv[1], "w"))
PY
d_code=$(gate_compose "$d_platform" "$c_adopter" d)
tail -3 "$scratch/d.out"
[ "$d_code" -ne 0 ] || fail "D: a tampered signature on platform's real bundle must refuse, got exit 0"
grep -qi "cosign verify-blob refused evidence for ${version}" "$scratch/d.out" \
  || fail "D: the refusal does not name cosign's own refusal for ${version}"
grep -qi "signature in bundle does not match\|invalid signature" "$scratch/d.out" \
  || fail "D: the refusal is not about the signature: $(tail -1 "$scratch/d.out")"
echo "OK  D: real cosign REFUSED the same real bundle with one signature byte changed, and the gate propagated it as a refusal about the SIGNATURE"

# ---------------------------------------------------------------------------
say "E: the identity constant is load-bearing against a real Fulcio certificate, not just against a string"
# ---------------------------------------------------------------------------
# `compose` has no identity flag -- the constant is held in the module, which
# is the point (spec.md: "the party being checked does not supply the
# identity it is trusted by"). So this calls the module's own
# verify_evidence directly, with a foreign publisher's identity, against the
# same real, valid, untampered bundle.
set +e
python3 - "$GATE" "$platform" "$version" > "$scratch/e.out" 2>&1 <<'PY'
import importlib.util, sys, pathlib
spec = importlib.util.spec_from_file_location("gate", sys.argv[1])
gate = importlib.util.module_from_spec(spec); spec.loader.exec_module(gate)
try:
    gate.verify_evidence(
        pathlib.Path(sys.argv[2]), sys.argv[3],
        identity_regexp=r"^https://github\.com/evil-org/platform/\.github/workflows/cut-release\.yml@refs/heads/main$")
except gate.RefusalError as exc:
    print(f"REFUSED: {exc}")
    sys.exit(1)
print("ACCEPTED -- a foreign identity constant verified platform's evidence")
PY
e_code=$?
set -e
tail -2 "$scratch/e.out"
[ "$e_code" -ne 0 ] || fail "E: a foreign identity constant must refuse platform's real evidence"
grep -qi "none of the expected identities matched" "$scratch/e.out" \
  || fail "E: the refusal does not name an identity mismatch -- it may have failed for another reason"
echo "OK  E: the same real, valid bundle is REFUSED when the identity constant names a foreign publisher -- the certificate is really being read"

# ---------------------------------------------------------------------------
say "F: a retirement is a forced major, and a composed major refuses the pull request"
# ---------------------------------------------------------------------------
f_adopter="$scratch/driftwood-f"
plant_adopter "$f_adopter" "4.0.0 ${version}" "4.0.0"
f_code=$(gate_compose "$platform" "$f_adopter" f)
tail -3 "$scratch/f.out"
[ "$f_code" -ne 0 ] || fail "F: a retirement composes major and must refuse, got exit 0"
grep -q "REFUSED: composed bump is major" "$scratch/f.out" || fail "F: the refusal does not name the composed major"
echo "OK  F: retiring policy ${version} composed major with no evidence lookup at all, and refused"

# ---------------------------------------------------------------------------
say "G: how offline this gate actually is -- measured on this run, not claimed"
# ---------------------------------------------------------------------------
# This gate's own docstring says it verifies "offline". Measured 2026-09-06,
# that is true only on a machine whose ~/.sigstore TUF cache is already warm:
# this gate passes cosign no trust root, so on a COLD cache it fetches one
# from Sigstore's TUF CDN. A GitHub Actions runner is cold on every run, so
# every real shift-left run of this gate has a live network dependency in its
# signature check. ludlow's gate does not (eco-system ticket 101 pins the
# trust material there); extending that pin to this repository is charted as
# eco-system ticket 103.
#
# This scenario RECORDS the number rather than asserting a sentence about it,
# because a sentence is exactly what went stale last time: it prints the exit
# code either way and only fails if the gate stops being able to verify at
# all. When ticket 103 lands, the number moves from 1 to 0 here and the
# paragraph above is contradicted by the run itself.
mkdir -p "$scratch/cold-home" "$scratch/cold-tuf"
set +e
cold_out=$(HOME="$scratch/cold-home" TUF_ROOT="$scratch/cold-tuf" \
  HTTPS_PROXY="http://127.0.0.1:1" HTTP_PROXY="http://127.0.0.1:1" ALL_PROXY="socks5://127.0.0.1:1" \
  timeout 60 cosign verify-blob --bundle="$bundle" \
  --certificate-identity-regexp="$(python3 -c 'import re,sys
src = open(sys.argv[1]).read()
m = re.search(r"EXPECTED_PLATFORM_IDENTITY_REGEXP = \(\n(.*?)\n\)", src, re.S)
print("".join(eval(l.strip()) for l in m.group(1).splitlines()))' "$GATE")" \
  --certificate-oidc-issuer="https://token.actions.githubusercontent.com" "$evidence" 2>&1)
cold_code=$?
set -e
echo "cold TUF cache + every proxy pointed at a closed port: exit ${cold_code}"
echo "$cold_out" | tail -2
if [ "$cold_code" -eq 0 ]; then
  echo "ok  G: this gate's verification of platform's real published bundle needs NO network (exit 0 on a cold cache with egress blocked) -- ticket 103 has landed, or was never needed"
else
  echo "$cold_out" | grep -qiE "tuf|dial tcp|connection refused" \
    || fail "G: the cold-cache run failed for a reason that is not the network, so this measurement no longer measures what it says: $(echo "$cold_out" | tail -1)"
  echo "ok  G: measured, not claimed -- with a cold TUF cache and egress blocked this gate's own cosign invocation cannot verify platform's real bundle (exit ${cold_code}, a TUF fetch). Scenario C above therefore ran with the network available, exactly as a real shift-left run does. Eco-system ticket 103 is the pin that closes it"
fi

# ---------------------------------------------------------------------------
say "H: the gate's own selfcheck -- its pure logic, on planted inputs"
# ---------------------------------------------------------------------------
set +e
python3 "$GATE" --selfcheck > "$scratch/h.out" 2>&1
h_code=$?
set -e
tail -3 "$scratch/h.out"
[ "$h_code" -eq 0 ] || fail "H: adopter-gate.py --selfcheck failed: $(tail -1 "$scratch/h.out")"
echo "OK  H: adopter-gate.py --selfcheck passed"

echo
echo "PASS: driftwood's adopter gate, against platform's REAL PUBLISHED evidence for policy ${version} at ${pinned_tag} --"
echo "      the pin is load-bearing (A), a movement of nothing composes 'none' and verifies nothing (B), real"
echo "      cosign ACCEPTS platform's own signature and the gate composes the publisher's own '${computed}' (C),"
echo "      real cosign REFUSES the same bundle with one signature byte changed (D), the same valid bundle is"
echo "      REFUSED under a foreign identity constant (E), a retirement is a forced major that refuses (F), and"
echo "      the gate's own selfcheck passes (H). How offline the signature check is is measured on every run and"
echo "      printed as an exit code (G), never asserted as a sentence."
