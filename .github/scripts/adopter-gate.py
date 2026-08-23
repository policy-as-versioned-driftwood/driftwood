#!/usr/bin/env python3
"""adopter-gate.py -- ticket cs-28: driftwood's own adopter gate.

Runs inside shift-left.yml, on the Renovate bump pull request that moves
gitops/platform/platform-pin.yaml's pinned platform tag. Does NOT recompute
the publisher's bump -- "a second answer to the same question has no
tie-breaker" (spec.md) -- it verifies platform's own cs-27 signed evidence
against an identity driftwood holds itself, then composes driftwood's own
bump across the one policy-bearing party it pins.

Four things, in order:

  1. `verify_pinned_commit` -- platform's checked-out HEAD commit must equal
     platform-pin.yaml's pinned `commit` field. ADR-0001's pin, made
     load-bearing (spec.md's "Two live bugs", bug #2).
  2. `read_policy_array_at` + `diff_arrays` -- distribution/versions.yaml's
     policy-version array, read from the OLD tag (what driftwood is
     currently pinned to) and the NEW tag (what this pull request proposes)
     -- finds every version added and every version retired.
  3. `verify_evidence` -- every ADDED version's signed evidence
     (computed-semver/evidence/<version>.json + .bundle, committed in
     platform's own tree) verifies with `cosign verify-blob`,
     identity-pinned to EXPECTED_PLATFORM_IDENTITY_REGEXP -- a literal
     constant driftwood holds itself, never read from platform. "The party
     being checked does not supply the identity it is trusted by."
  4. `compose` -- folds retirements (always major, spec.md: "a retirement
     classify as major with no special case") and each added version's own
     recorded `computed_bump` into driftwood's own composed bump. Never
     recomputes a bump -- every per-version number here is read straight out
     of the verified evidence document.

Single-party note (spec.md's "Out of Scope", and .scratch/policy-composition/
map.md): driftwood's gitops/ pins two GitRepository objects -- `platform`
(the one policy-bearing party, this gate's subject) and `nist` (a regulator
OSCAL controls catalog with no gate.py/evidence mechanism at all -- it is not
a second policy-bearing party). Cross-party composition is out of scope; with
one policy-bearing party pinned, "driftwood's own composed bump" reduces to
platform's own bump, re-verified -- not general N-party composition
machinery. If a future institution ever pins a second policy-bearing party,
this module's `compose()` needs to change; it does not attempt that today.

Usage:
    adopter-gate.py read-pin <pin-yaml-path>
    adopter-gate.py verify-commit <platform-dir> <pinned-commit>
    adopter-gate.py compose <platform-dir> <old-tag> <new-tag> [--out FILE] [--markdown-out FILE]
    adopter-gate.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

# --------------------------------------------------------------------------
# The institution's own expected-identity constant (spec.md, "Signing and
# verification": "The adopter verifies identity-pinned, reusing the offline
# pattern the release workflow already runs"; Further Notes: "their own
# expected-identity constant"). This is a LITERAL, independently-typed copy
# of the value platform/.github/workflows/release.yml pins for its OWN
# cut-release.yml identity -- not read from platform at verification time,
# not discovered, not trusted because platform's own repo states it. A
# platform workflow rename changes the identity string a real Fulcio cert
# would carry (`.../.github/workflows/<name>.yml@...`) and this regexp,
# anchored to the literal path `cut-release.yml`, then no longer matches --
# verification breaks, on purpose (cs-28 acceptance criterion).
# --------------------------------------------------------------------------
EXPECTED_PLATFORM_IDENTITY_REGEXP = (
    r"^https://github\.com/policy-as-versioned-platform/platform/"
    r"\.github/workflows/cut-release\.yml@refs/heads/(main|release/[0-9]+\.[0-9]+\.x)$"
)
EXPECTED_PLATFORM_ISSUER = "https://token.actions.githubusercontent.com"

# Matches rederive_bumps.RANK exactly (platform's own module) -- the values
# ranked here are always doc["computed_bump"]/doc["bump"]["declared"], which
# are one of "major"/"minor"/"patch"/comparison_window.NO_PREDECESSOR; a
# retirement is folded into "major" by compose() itself below, never
# represented as the string "removed" at this level (that value only ever
# appears inside a movement entry's own `verdict`, which compose() does not
# rank).
RANK = {"none": 0, "patch": 1, "minor": 2, "major": 3}


class RefusalError(Exception):
    """Raised for any reason this gate refuses. main() turns it into a
    non-zero exit and a printed reason -- never a silent pass."""


# --------------------------------------------------------------------------
# 1. the pin, and the commit it must resolve to
# --------------------------------------------------------------------------

def read_pin(pin_yaml_text: str) -> tuple[str, str]:
    """gitops/platform/platform-pin.yaml's spec.ref.tag/commit -- the exact
    two fields the Renovate customManager (git-refs datasource) bumps
    together (renovate.json). The real file is a multi-document YAML stream
    (the GitRepository, then a Kustomization) -- reads every document and
    picks the one whose `kind` is GitRepository, rather than assuming the
    first document in the stream is it."""
    docs = [d for d in yaml.safe_load_all(pin_yaml_text) if d]
    matches = [d for d in docs if d.get("kind") == "GitRepository"]
    if not matches:
        raise RefusalError("no GitRepository document found in the platform pin YAML")
    ref = matches[0]["spec"]["ref"]
    return ref["tag"], ref["commit"]


def verify_pinned_commit(platform_dir: Path, pinned_commit: str) -> None:
    """Refuses unless platform's checked-out HEAD is exactly the commit
    platform-pin.yaml pins -- the pin is load-bearing, not decorative
    (spec.md's bug #2)."""
    proc = subprocess.run(
        ["git", "-C", str(platform_dir), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RefusalError(f"could not read platform's checked-out HEAD: {proc.stderr.strip()}")
    resolved = proc.stdout.strip()
    if resolved != pinned_commit:
        raise RefusalError(
            f"platform-pin.yaml pins commit {pinned_commit}, but the checked-out tag "
            f"resolves to {resolved} -- refusing, the pin is not decorative"
        )


# --------------------------------------------------------------------------
# 2. the policy-version array, old and new
# --------------------------------------------------------------------------

def read_policy_array_at(platform_dir: Path, ref: str) -> dict[str, dict]:
    """distribution/versions.yaml's spec.inputs[0].versions array at `ref`
    (a tag, or a commit-ish), keyed by version string. `ref` must already be
    fetched into platform_dir's object store (the caller's job -- see
    `fetch_tag`)."""
    proc = subprocess.run(
        ["git", "-C", str(platform_dir), "show", f"{ref}:distribution/versions.yaml"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RefusalError(
            f"could not read distribution/versions.yaml at {ref!r}: {proc.stderr.strip()}"
        )
    doc = yaml.safe_load(proc.stdout)
    elements = doc["spec"]["inputs"][0]["versions"]
    return {e["version"]: e for e in elements}


def fetch_tag(platform_dir: Path, tag: str) -> None:
    proc = subprocess.run(
        ["git", "-C", str(platform_dir), "fetch", "origin", f"refs/tags/{tag}:refs/tags/{tag}", "--force"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RefusalError(f"could not fetch tag {tag!r} from platform's origin: {proc.stderr.strip()}")


def diff_arrays(old: dict, new: dict) -> tuple[list[str], list[str]]:
    """Every version present in `new` but not `old` (added), and every
    version present in `old` but not `new` (retired). Composition inputs
    come from these two arrays alone -- no discovery endpoint."""
    added = sorted(v for v in new if v not in old)
    retired = sorted(v for v in old if v not in new)
    return added, retired


# --------------------------------------------------------------------------
# 3. the publisher's signed evidence, verified
# --------------------------------------------------------------------------

def verify_evidence(
    platform_dir: Path,
    version: str,
    *,
    identity_regexp: str = EXPECTED_PLATFORM_IDENTITY_REGEXP,
    issuer: str = EXPECTED_PLATFORM_ISSUER,
) -> dict:
    """Locates computed-semver/evidence/<version>.json + .bundle in
    platform's checked-out tree, verifies the bundle's cosign signature
    offline against this institution's own identity constant, then checks
    the evidence document's own content (outcome passed, declared ==
    version -- the same two fields release.yml's own cheaper check reads).
    Refuses -- never passes silently -- on any missing file, bad signature,
    wrong identity, or content mismatch."""
    evidence_path = platform_dir / "computed-semver" / "evidence" / f"{version}.json"
    bundle_path = evidence_path.with_name(evidence_path.name + ".bundle")
    if not evidence_path.exists():
        raise RefusalError(f"no evidence committed for version {version} at {evidence_path}")
    if not bundle_path.exists():
        raise RefusalError(f"no cosign bundle committed for version {version} at {bundle_path}")

    proc = subprocess.run(
        [
            "cosign", "verify-blob",
            f"--bundle={bundle_path}",
            f"--certificate-identity-regexp={identity_regexp}",
            f"--certificate-oidc-issuer={issuer}",
            str(evidence_path),
        ],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RefusalError(
            f"cosign verify-blob refused evidence for {version} against the institution's own "
            f"identity constant -- {proc.stderr.strip() or proc.stdout.strip()}"
        )

    doc = json.loads(evidence_path.read_text())
    if doc.get("outcome", {}).get("result") != "passed":
        raise RefusalError(
            f"evidence for {version} records outcome {doc.get('outcome')!r}, not passed"
        )
    if doc.get("declared") != version:
        raise RefusalError(
            f"evidence declared {doc.get('declared')!r} but is filed under version {version!r}"
        )
    return doc


# --------------------------------------------------------------------------
# 4. composition -- a single policy-bearing party, re-verified
# --------------------------------------------------------------------------

def compose(added: list[str], retired: list[str], evidence_by_version: dict[str, dict]) -> dict:
    """Folds retirements (always major) and each added version's own
    recorded computed_bump into one composed result. `evidence_by_version`
    must already have passed `verify_evidence` for every version in
    `added` -- this function reads fields, it does not verify anything."""
    reasons: list[str] = []
    composed = "none"
    if retired:
        composed = "major"
        reasons.append(
            f"retired from the supported window: {', '.join(retired)} "
            f"(a retired version reaches the institution as a major)"
        )
    declared_worst = "none"
    for v in added:
        doc = evidence_by_version[v]
        computed = doc["computed_bump"]
        declared = doc["bump"]["declared"]
        reasons.append(f"{v}: publisher declared {declared!r}, computed {computed!r}")
        if RANK.get(computed, 0) > RANK.get(composed, 0):
            composed = computed
        if RANK.get(declared, 0) > RANK.get(declared_worst, 0):
            declared_worst = declared

    weaker_than_declared = RANK.get(composed, 0) < RANK.get(declared_worst, 0)
    if weaker_than_declared:
        reasons.append(
            f"composed bump {composed!r} is weaker than the publisher's declared {declared_worst!r} "
            f"-- printed, never lowers what this institution treats as the obligation"
        )

    return {
        "composed_bump": composed,
        "declared_bump": declared_worst,
        "added": added,
        "retired": retired,
        "reasons": reasons,
        "weaker_than_declared": weaker_than_declared,
    }


def run_compose(platform_dir: Path, old_tag: str, new_tag: str) -> tuple[dict, dict[str, dict]]:
    fetch_tag(platform_dir, old_tag)
    fetch_tag(platform_dir, new_tag)
    old_array = read_policy_array_at(platform_dir, old_tag)
    new_array = read_policy_array_at(platform_dir, new_tag)
    added, retired = diff_arrays(old_array, new_array)
    evidence_by_version = {v: verify_evidence(platform_dir, v) for v in added}
    return compose(added, retired, evidence_by_version), evidence_by_version


# --------------------------------------------------------------------------
# rendering -- ticket cs-29 reuses this evidence for the pull request comment
# --------------------------------------------------------------------------

def render_markdown(result: dict, evidence_by_version: dict[str, dict]) -> str:
    lines: list[str] = []
    lines.append(f"**Composed bump: `{result['composed_bump']}`** "
                 f"(publisher declared: `{result['declared_bump']}`)")
    lines.append("")
    if result["retired"]:
        lines.append(f"- retired from the supported window: {', '.join(result['retired'])}")
    if result["added"]:
        lines.append(f"- added to the supported window: {', '.join(result['added'])}")
    if not result["retired"] and not result["added"]:
        lines.append("- no change to the supported policy-version window")
    lines.append("")

    for v in result["added"]:
        doc = evidence_by_version[v]
        lines.append(f"### `{v}`")
        lines.append("")
        lines.append(f"| declared | computed | outcome |")
        lines.append(f"| --- | --- | --- |")
        lines.append(f"| `{doc['bump']['declared']}` | `{doc['computed_bump']}` | {doc['outcome']['result']} |")
        lines.append("")

        movement = doc.get("movement") or []
        if movement:
            lines.append("**Verdict movement**")
            lines.append("")
            lines.append("| policy | verdict | entries | expressions |")
            lines.append("| --- | --- | --- | --- |")
            for m in movement:
                entries = ", ".join(m.get("entries") or []) or "(structural, no fixture moved)"
                exprs = "; ".join(m.get("expressions") or []) or "n/a"
                lines.append(f"| {m['policy']} | {m['verdict']} | {entries} | `{exprs}` |")
            lines.append("")

        counts = doc.get("counts") or {}
        lines.append(f"**Counts:** old={counts.get('old')} new={counts.get('new')} union={counts.get('union')}")
        lines.append("")

        not_looked_at = doc.get("not_looked_at") or []
        lines.append(f"**Not looked at ({len(not_looked_at)}):**")
        if not_looked_at:
            lines.append("")
            lines.append("| id | tier | status |")
            lines.append("| --- | --- | --- |")
            for h in not_looked_at:
                lines.append(f"| `{h.get('id')}` | {h.get('tier')} | {h.get('status')} |")
        lines.append("")

        limits = doc.get("limits") or []
        if limits:
            lines.append("**Derived limits**")
            lines.append("")
            lines.append("| name | status | count |")
            lines.append("| --- | --- | --- |")
            for lim in limits:
                lines.append(f"| {lim['name']} | {lim['status']} | {lim['count']} |")
            lines.append("")

        matrix = doc.get("matrix") or {}
        if matrix:
            lines.append("**Per-institution matrix**")
            lines.append("")
            lines.append("| institution | pinned version | computed bump |")
            lines.append("| --- | --- | --- |")
            for inst in sorted(matrix):
                cell = matrix[inst]
                lines.append(f"| {inst} | {cell.get('pinned_version')} | {cell.get('computed_bump')} |")
            lines.append("")

        lines.append(
            f"**Corpus checksum:** `{doc.get('corpus_checksum')}` &nbsp; "
            f"**Generator version:** `{doc.get('generator_version')}`"
        )
        lines.append("")

    for reason in result["reasons"]:
        lines.append(f"- {reason}")

    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def main(argv: list[str]) -> int:
    if len(argv) > 1 and argv[1] == "--selfcheck":
        selfcheck()
        return 0

    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    rp = sub.add_parser("read-pin")
    rp.add_argument("pin_yaml_path")

    vc = sub.add_parser("verify-commit")
    vc.add_argument("platform_dir")
    vc.add_argument("pinned_commit")

    cp = sub.add_parser("compose")
    cp.add_argument("platform_dir")
    cp.add_argument("old_tag")
    cp.add_argument("new_tag")
    cp.add_argument("--out", help="write the composed result + evidence as JSON here")
    cp.add_argument("--markdown-out", help="write a human-rendered markdown summary here")

    args = p.parse_args(argv[1:])

    try:
        if args.cmd == "read-pin":
            tag, commit = read_pin(Path(args.pin_yaml_path).read_text())
            print(f"tag={tag}")
            print(f"commit={commit}")
            return 0

        if args.cmd == "verify-commit":
            verify_pinned_commit(Path(args.platform_dir), args.pinned_commit)
            print(f"OK: platform's checked-out HEAD matches platform-pin.yaml's pinned commit {args.pinned_commit}")
            return 0

        if args.cmd == "compose":
            result, evidence_by_version = run_compose(Path(args.platform_dir), args.old_tag, args.new_tag)
            print(json.dumps(result, indent=2))
            for reason in result["reasons"]:
                print(f"  - {reason}")
            if args.out:
                Path(args.out).write_text(json.dumps(
                    {"result": result, "evidence": evidence_by_version}, indent=2))
            if args.markdown_out:
                Path(args.markdown_out).write_text(render_markdown(result, evidence_by_version))
            if result["composed_bump"] == "major":
                print("REFUSED: composed bump is major", file=sys.stderr)
                return 1
            print(f"OK: composed bump is {result['composed_bump']!r}")
            return 0
    except RefusalError as e:
        print(f"REFUSED: {e}", file=sys.stderr)
        return 1

    return 2


# --------------------------------------------------------------------------
# selfcheck -- real git, real cosign, real refusals proven, not assumed.
#
# Honest limit, matching cs-13's and cs-27's own disclosures: a REAL
# keyless-signed cosign bundle (a Fulcio certificate bound to a live GitHub
# Actions OIDC identity) cannot be minted outside a real Actions run -- there
# is no ambient credential and no interactive browser to complete a keyless
# signing flow here. What IS proven for real below: (a) the real cosign
# binary genuinely refuses a bundle that carries no certificate at all when
# --certificate-identity-regexp is demanded of it -- the exact failure mode
# a forged or wrongly-signed evidence file would hit; (b) the real cosign
# binary genuinely refuses a corrupted/garbage bundle; (c) every pure-logic
# function (pin parsing, commit comparison, array diffing, composition,
# rendering) against real git repositories built with real `git` commands,
# including the identity-regexp itself proven to reject a renamed platform
# workflow path, the same technique scripts/verify-identity-regexp.sh
# already established for gitsign.
# --------------------------------------------------------------------------

def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=check,
        env={
            "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
            "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
            "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin",
        },
    )


def _versions_yaml(elements: list[dict]) -> str:
    doc = {"spec": {"inputs": [{"versions": elements}]}}
    return yaml.safe_dump(doc, sort_keys=False)


def _evidence_doc(version: str, declared: str, computed: str, result: str = "passed") -> dict:
    return {
        "declared": version,
        "outcome": {"result": result, "reason": None},
        "bump": {"declared": declared, "computed": computed},
        "computed_bump": computed,
        "movement": [{"policy": "cage-tier", "verdict": computed, "entries": ["fixture-a"],
                      "expressions": ["dial >= 2"], "detail": ""}],
        "counts": {"old": 10, "new": 12, "union": 14},
        "generator_version": "cs-19.0",
        "corpus_checksum": "deadbeef",
        "not_looked_at": [{"id": "hole-1", "tier": "declared_hole", "status": "carried_over"}],
        "limits": [{"name": "cage-ratchet-one-way", "description": "d", "count": 3, "status": "open"}],
        "matrix": {"driftwood": {"pinned_version": version, "computed_bump": computed, "movement": []}},
    }


def selfcheck() -> None:
    # ---- read_pin: parses the real shape platform-pin.yaml uses ----
    pin_text = (
        "apiVersion: source.toolkit.fluxcd.io/v1\n"
        "kind: GitRepository\n"
        "spec:\n"
        "  ref:\n"
        "    tag: v0.2.0\n"
        "    commit: aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa\n"
    )
    tag, commit = read_pin(pin_text)
    assert (tag, commit) == ("v0.2.0", "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"), (tag, commit)

    # the real platform-pin.yaml is a MULTI-DOCUMENT stream (GitRepository,
    # then a Kustomization) -- read_pin must pick the GitRepository doc, not
    # assume the first document in the stream is it (a real bug this
    # selfcheck caught against the real file before this guard existed).
    multi_doc_text = pin_text + "---\napiVersion: kustomize.toolkit.fluxcd.io/v1\nkind: Kustomization\nspec:\n  path: ./x\n"
    tag2, commit2 = read_pin(multi_doc_text)
    assert (tag2, commit2) == (tag, commit), (tag2, commit2)
    print("OK read_pin: picks the GitRepository document out of a multi-document stream")

    # ---- verify_pinned_commit: REAL git repo, REAL tag, real match + real mismatch ----
    platform = Path(tempfile.mkdtemp(prefix="adopter-gate-platform-"))
    _git(platform, "init", "-q")
    (platform / "distribution").mkdir()
    (platform / "distribution" / "versions.yaml").write_text(_versions_yaml(
        [{"version": "2.0.0", "tag": "policy/v2.0.0", "commit": "c1"}]
    ))
    (platform / "computed-semver").mkdir()
    (platform / "computed-semver" / "evidence").mkdir()
    _git(platform, "add", "-A")
    _git(platform, "commit", "-q", "-m", "v1")
    _git(platform, "tag", "v1.0.0")
    v1_sha = _git(platform, "rev-parse", "HEAD").stdout.strip()

    verify_pinned_commit(platform, v1_sha)  # no raise -> pass
    try:
        verify_pinned_commit(platform, "0" * 40)
        raise AssertionError("verify_pinned_commit did not refuse a wrong commit")
    except RefusalError as e:
        assert v1_sha in str(e) and "0" * 40 in str(e), e
    print("OK verify_pinned_commit: matches for real, refuses a real mismatch")

    # ---- read_policy_array_at / diff_arrays / fetch_tag: REAL git tags, an add, a retirement ----
    (platform / "distribution" / "versions.yaml").write_text(_versions_yaml([
        {"version": "2.0.0", "tag": "policy/v2.0.0", "commit": "c1"},
        {"version": "3.0.0", "tag": "policy/v3.0.0", "commit": "c2"},
    ]))
    _git(platform, "add", "-A")
    _git(platform, "commit", "-q", "-m", "v2 adds 3.0.0")
    _git(platform, "tag", "v2.0.0")

    (platform / "distribution" / "versions.yaml").write_text(_versions_yaml([
        {"version": "3.0.0", "tag": "policy/v3.0.0", "commit": "c2"},
        {"version": "4.0.0", "tag": "policy/v4.0.0", "commit": "c3"},
    ]))
    _git(platform, "add", "-A")
    _git(platform, "commit", "-q", "-m", "v3 retires 2.0.0, adds 4.0.0")
    _git(platform, "tag", "v3.0.0")

    old_array = read_policy_array_at(platform, "v2.0.0")
    new_array = read_policy_array_at(platform, "v3.0.0")
    assert set(old_array) == {"2.0.0", "3.0.0"}, old_array
    assert set(new_array) == {"3.0.0", "4.0.0"}, new_array
    added, retired = diff_arrays(old_array, new_array)
    assert added == ["4.0.0"], added
    assert retired == ["2.0.0"], retired
    print("OK read_policy_array_at + diff_arrays: real git tags, add and retirement both detected")

    # fetch_tag against a real clone-of-a-clone (origin/local), proving the network path shape works
    clone = Path(tempfile.mkdtemp(prefix="adopter-gate-clone-"))
    _git(Path("/"), "clone", "-q", str(platform), str(clone))
    # the clone by default only has tags reachable from the fetched branch history;
    # simulate "old tag not yet present locally" by deleting it, then fetch it back
    _git(clone, "tag", "-d", "v1.0.0")
    try:
        read_policy_array_at(clone, "v1.0.0")
        raise AssertionError("expected read_policy_array_at to fail before fetch_tag")
    except RefusalError:
        pass
    fetch_tag(clone, "v1.0.0")
    got = read_policy_array_at(clone, "v1.0.0")
    assert set(got) == {"2.0.0"}, got
    print("OK fetch_tag: a tag missing from the local clone is fetched from origin for real, then reads")

    # ---- verify_evidence: missing file, bad JSON content, and the real-cosign refusal ----
    ev_dir = platform / "computed-semver" / "evidence"
    try:
        verify_evidence(platform, "9.9.9")
        raise AssertionError("verify_evidence did not refuse a missing evidence file")
    except RefusalError as e:
        assert "9.9.9" in str(e), e
    print("OK verify_evidence refuses a missing evidence file")

    (ev_dir / "4.0.0.json").write_text(json.dumps(_evidence_doc("4.0.0", "minor", "minor")))
    (ev_dir / "4.0.0.json.bundle").write_text("not a real cosign bundle, deliberately garbage")
    try:
        verify_evidence(platform, "4.0.0")
        raise AssertionError("verify_evidence did not refuse a garbage bundle")
    except RefusalError as e:
        assert "4.0.0" in str(e), e
    print("OK verify_evidence refuses a garbage bundle (real cosign verify-blob call, real non-zero exit)")

    # A real, valid cosign signature (local key pair -- no live GH Actions OIDC identity
    # is reachable here; see the module docstring) is real proof that verify_evidence's
    # cosign subprocess plumbing works end to end for a signature that DOES verify, and
    # that demanding --certificate-identity-regexp of a bundle carrying no certificate at
    # all -- which is exactly what a key-signed bundle is -- is refused for real, not
    # assumed. This is the strongest offline-testable proof of the identity-pinning path
    # available without a live Actions run.
    key_ok = subprocess.run(["cosign", "generate-key-pair"], cwd=ev_dir, input="\n",
                             capture_output=True, text=True,
                             env={"COSIGN_PASSWORD": "", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})
    if key_ok.returncode == 0:
        (ev_dir / "5.0.0.json").write_text(json.dumps(_evidence_doc("5.0.0", "patch", "patch")))
        sign = subprocess.run(
            ["cosign", "sign-blob", "--key", str(ev_dir / "cosign.key"), "--yes",
             "--use-signing-config=false", "--tlog-upload=false",
             f"--bundle={ev_dir / '5.0.0.json.bundle'}", str(ev_dir / "5.0.0.json")],
            capture_output=True, text=True,
            env={"COSIGN_PASSWORD": "", "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
        )
        if sign.returncode == 0:
            verify_ok = subprocess.run(
                ["cosign", "verify-blob", "--key", str(ev_dir / "cosign.pub"),
                 f"--bundle={ev_dir / '5.0.0.json.bundle'}", "--insecure-ignore-tlog=true",
                 str(ev_dir / "5.0.0.json")],
                capture_output=True, text=True,
            )
            assert verify_ok.returncode == 0, verify_ok.stderr
            print("OK real cosign: a real key-signed bundle verifies for real with its real public key")

            try:
                verify_evidence(platform, "5.0.0")
                raise AssertionError(
                    "verify_evidence passed a key-signed bundle against --certificate-identity-regexp "
                    "-- a key-signed bundle carries no certificate, this must refuse"
                )
            except RefusalError:
                print(
                    "OK verify_evidence refuses a real, validly-signed-but-non-keyless bundle when "
                    "identity-pinned verification is demanded (real cosign verify-blob call)"
                )
        else:
            print(f"SKIP real-signature refusal proof: cosign sign-blob unavailable offline here "
                  f"({sign.stderr.strip()[:200]})")
    else:
        print(f"SKIP real-signature refusal proof: cosign generate-key-pair unavailable offline here "
              f"({key_ok.stderr.strip()[:200]})")

    # ---- the identity constant itself: proven anchored, same technique as
    #      scripts/verify-identity-regexp.sh's synthetic RE2-equivalent shapes ----
    import re
    rx = re.compile(EXPECTED_PLATFORM_IDENTITY_REGEXP)
    assert rx.match(
        "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/main"
    )
    assert rx.match(
        "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release.yml@refs/heads/release/1.2.x"
    )
    # a platform workflow rename must break verification (cs-28 acceptance criterion)
    assert not rx.match(
        "https://github.com/policy-as-versioned-platform/platform/.github/workflows/cut-release-v2.yml@refs/heads/main"
    )
    assert not rx.match(
        "https://github.com/policy-as-versioned-platform/platform/.github/workflows/release.yml@refs/heads/main"
    )
    # a foreign org/repo must not match either
    assert not rx.match(
        "https://github.com/policy-as-versioned-driftwood/driftwood/.github/workflows/cut-release.yml@refs/heads/main"
    )
    print("OK EXPECTED_PLATFORM_IDENTITY_REGEXP: matches platform's real identity shapes, "
          "refuses a renamed workflow path and a foreign org/repo")

    # ---- compose(): every acceptance criterion, as a pure function ----
    ev = {
        "4.0.0": {"declared": "4.0.0", "bump": {"declared": "minor"}, "computed_bump": "minor"},
    }
    r = compose(added=["4.0.0"], retired=[], evidence_by_version=ev)
    assert r["composed_bump"] == "minor" and not r["weaker_than_declared"], r
    print("OK compose: a clean minor addition composes to minor")

    r_major = compose(added=[], retired=["2.0.0"], evidence_by_version={})
    assert r_major["composed_bump"] == "major", r_major
    print("OK compose: a retirement alone composes to major")

    ev_weaker = {"4.0.0": {"declared": "4.0.0", "bump": {"declared": "major"}, "computed_bump": "patch"}}
    r_weaker = compose(added=["4.0.0"], retired=[], evidence_by_version=ev_weaker)
    assert r_weaker["composed_bump"] == "patch" and r_weaker["declared_bump"] == "major"
    assert r_weaker["weaker_than_declared"] is True
    assert r_weaker["composed_bump"] != r_weaker["declared_bump"]  # printed, never raised to match
    print("OK compose: a computed bump weaker than declared is reported, never raised (or lowered)")

    ev_both = {
        "4.0.0": {"declared": "4.0.0", "bump": {"declared": "minor"}, "computed_bump": "minor"},
    }
    r_both = compose(added=["4.0.0"], retired=["2.0.0"], evidence_by_version=ev_both)
    assert r_both["composed_bump"] == "major", r_both  # retirement outranks a minor addition
    print("OK compose: a retirement outranks a same-PR minor addition -- strictest wins")

    # ---- render_markdown: no percentage, ever ----
    md = render_markdown(r_both, ev_both | {"4.0.0": _evidence_doc("4.0.0", "minor", "minor")})
    assert "%" not in md, "render_markdown emitted a percentage -- forbidden by spec.md and ticket cs-29"
    for needed in ("declared", "computed", "not looked at", "corpus checksum".title(), "generator version".title()):
        assert needed.lower() in md.lower(), f"render_markdown missing {needed!r}"
    print("OK render_markdown: no percentage anywhere, every required section present")

    print(
        "\nselfcheck ok: read_pin parses the real pin shape; verify_pinned_commit matches and refuses "
        "for real against a real git repo; read_policy_array_at/diff_arrays/fetch_tag detect an add and "
        "a retirement against real git tags, fetching a tag missing from a real clone for real; "
        "verify_evidence refuses a missing file, a garbage bundle (real cosign call), and -- where a "
        "local cosign signing flow is reachable offline -- a real, validly key-signed bundle presented "
        "to identity-pinned verification (real cosign call, real refusal, since a key-signed bundle "
        "carries no certificate); EXPECTED_PLATFORM_IDENTITY_REGEXP matches real identity shapes and "
        "refuses a renamed workflow path; compose() satisfies every acceptance criterion as a pure "
        "function; render_markdown never emits a percentage. NOT provable outside a live GitHub Actions "
        "run: a real Fulcio-certificate keyless signature bound to platform's own ambient OIDC identity "
        "-- no ambient credential and no interactive browser login exist in this sandbox (same class of "
        "limit cs-13 and cs-27 already disclosed for their own signing steps)."
    )


if __name__ == "__main__":
    sys.exit(main(sys.argv))
