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
    adopter-gate.py splice-body --current-body FILE --section FILE --out-body FILE
    adopter-gate.py wrap-section --in FILE --out FILE
    adopter-gate.py --selfcheck
"""
from __future__ import annotations

import argparse
import json
import re
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

# Ticket cs-29: HTML-comment markers shift-left.yml greps out of the pull
# request's own CURRENT body to find (and replace) the span this gate owns,
# or append it if this is the first run on this PR. An earlier draft posted
# this evidence as a PR COMMENT instead; a reviewer correctly flagged that
# as not satisfying the ticket's own title and first acceptance-criterion
# line ("the pull request body carries the evidence document"). This now
# edits the body for real -- safe against Renovate's own re-runs because
# shift-left.yml is triggered BY a `pull_request` event, which only fires
# after Renovate has already pushed and settled its own body content for
# that push; the splice step below always reads and appends onto text
# Renovate already finished writing, never races it.
SECTION_START = "<!-- cs-29:adopter-gate:start -->"
SECTION_END = "<!-- cs-29:adopter-gate:end -->"
SECTION_PATTERN = re.compile(re.escape(SECTION_START) + r".*?" + re.escape(SECTION_END), re.DOTALL)


def wrap_section(markdown: str) -> str:
    return f"{SECTION_START}\n{markdown.rstrip()}\n{SECTION_END}\n"


def splice_body(current_body: str, section: str) -> str:
    """`section` is already wrap_section()'d output. Replaces a prior span
    between the markers in place (a re-run on the same pull request), or
    appends the whole marked section after whatever's there (the first run
    -- typically Renovate's own body)."""
    if SECTION_PATTERN.search(current_body):
        return SECTION_PATTERN.sub(section.rstrip(), current_body)
    sep = "\n\n" if current_body.strip() else ""
    return current_body.rstrip() + sep + section


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


def versions_from_composed_evidence(adopter_dir: Path, ref: str) -> set[str]:
    """ADR-0011: 'the adopter gate reads the composed artefact as its
    subject.' The set of live policy versions THIS institution's own signed
    composed/evidence.json records as members, at `ref` (a commit-ish in
    this adopter's own repo -- ticket 18's compose-check job keeps that file
    fresh and byte-verified on every pull request, so it is never stale by
    more than the PR under review). `ref` must already be fetched (a plain
    `git show` against an unfetched commit fails the same way an unfetched
    tag does in `read_policy_array_at`). A platform-machinery member (the
    orphan guard, the governed-namespace guard) carries no `version` --
    excluded, same as `distribution/versions.yaml`'s own array never lists
    it either."""
    proc = subprocess.run(
        ["git", "-C", str(adopter_dir), "show", f"{ref}:composed/evidence.json"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise RefusalError(
            f"could not read composed/evidence.json at {ref!r}: {proc.stderr.strip()}"
        )
    doc = json.loads(proc.stdout)
    return {m["version"] for m in doc["members"] if m.get("version") is not None}


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
    # Ticket 43 (18 Answers 1 and 2): `degraded` is a published outcome, not a
    # refusal. The publisher's declared bump was weaker than the computed one,
    # so it published under a prerelease suffix at tier quarantine. The
    # publisher's tier is a signed FACT here, never a floor this institution
    # must take: refusing it would be a gate under another name, and the
    # publisher would be setting a cage inside this repository. It is carried
    # through and priced under this institution's own perspective.
    #   ponytail: carried, named, and NOT yet priced -- the priced hole in
    #   composed prices[] is ticket 25's single prices[] pass. Until that
    #   lands, a degraded parent is a recorded, visible fact in this gate's
    #   own output, which is strictly more than the refusal it replaces.
    if doc.get("outcome", {}).get("result") not in ("passed", "degraded"):
        raise RefusalError(
            f"evidence for {version} records outcome {doc.get('outcome')!r}, not passed or degraded"
        )
    if doc.get("outcome", {}).get("result") == "degraded":
        print(f"note: {version} was published DEGRADED at tier "
              f"{doc.get('degraded', {}).get('tier')} -- declared "
              f"{doc['bump']['declared']!r} < computed {doc['bump']['computed']!r}. A signed fact "
              f"this institution prices; not a floor the publisher sets here.")
    # A degraded publish's tag carries a prerelease suffix while `declared`
    # keeps the untouched base number, so the field that must match the
    # version this evidence is filed under is `published_as` when present.
    published = doc.get("published_as", doc.get("declared"))
    if published != version:
        raise RefusalError(
            f"evidence published {published!r} but is filed under version {version!r}"
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


def run_compose(platform_dir: Path, old_tag: str, new_tag: str,
                 adopter_dir: Path | None = None, base_ref: str | None = None,
                 head_ref: str | None = None) -> tuple[dict, dict[str, dict]]:
    """ADR-0011: the composed bump is computed after composition. When
    `adopter_dir`/`base_ref`/`head_ref` are given, added/retired come from
    diffing THIS institution's own composed/evidence.json member sets at
    those two commits (versions_from_composed_evidence) -- a version
    retired from the composed set classifies major with no separate
    policy-diff case, because it simply stops appearing as a member,
    exactly like any other retirement. Falls back to platform's raw
    distribution/versions.yaml array (read_policy_array_at) when those
    three are omitted -- the pre-ADR-0011 shape, kept for `--selfcheck`'s
    own narrower fixtures and any caller not yet passing them. Evidence
    verification (identity-pinned, against platform_dir) is unchanged
    either way -- ADR-0011 already settled that the adopter gate verifies,
    never recomputes, the publisher's own answer."""
    if adopter_dir is not None and base_ref is not None and head_ref is not None:
        # No platform tag fetch needed: verify_evidence() below reads
        # computed-semver/evidence/ from whatever platform_dir already has
        # checked out (the pull request's head_tag, in real CI) -- old_tag/
        # new_tag are unused in this branch entirely.
        old_versions = versions_from_composed_evidence(adopter_dir, base_ref)
        new_versions = versions_from_composed_evidence(adopter_dir, head_ref)
        added = sorted(new_versions - old_versions)
        retired = sorted(old_versions - new_versions)
    else:
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

PARTY = "driftwood"

# --------------------------------------------------------------------------
# Ticket 43 (ticket 18 Answer 4): the per-institution matrix row, computed
# HERE, by the adopter.
#
# The publisher's `matrix` is empty and says so: NORTH-STAR §2 forbids
# platform reading this repository, and a hub-maintained pins file is the
# central catalogue ticket 04 refused. So the row about driftwood's own pin is
# computed by driftwood, running platform's PUBLISHED computed-semver package
# against driftwood's OWN claimed policy versions, with driftwood's OWN workloads
# added to the generated corpus, and lands in driftwood's own composed
# evidence.
#
# This is not "recomputing the publisher's answer" (ADR-0011 still holds):
# the publisher's number is the strictest band across its whole window, and
# this is the band for ONE pin -- the one this institution is actually
# running. Two different questions, and only the adopter can ask the second,
# because only the adopter knows what it claims and what it runs.
# --------------------------------------------------------------------------
CLAIM_LABEL = "policy-as-versioned.dev/policy-version"
GOVERNED_LABEL = "policy-as-versioned.dev/governed"


def _docs(path: Path) -> list[dict]:
    try:
        return [d for d in yaml.safe_load_all(path.read_text()) if isinstance(d, dict)]
    except (yaml.YAMLError, UnicodeDecodeError):
        return []


def claimed_versions(adopter_dir: Path) -> dict[str, list[Path]]:
    """Every policy version THIS repository's own manifests claim, and the
    workload files claiming it. Read here, never from the publisher: the row
    is about what this institution actually runs. `composed/` is skipped --
    those are the rendered policy bodies, not workloads."""
    claims: dict[str, list[Path]] = {}
    for path in sorted(adopter_dir.rglob("*.yaml")):
        if ".git" in path.parts or "composed" in path.parts:
            continue
        for doc in _docs(path):
            if doc.get("kind") != "Pod":
                continue
            version = ((doc.get("metadata") or {}).get("labels") or {}).get(CLAIM_LABEL)
            if version:
                claims.setdefault(str(version), []).append(path)
    return claims


def governed_namespace(adopter_dir: Path) -> dict | None:
    """This institution's own governed Namespace manifest -- the object that
    declares the cage tier (ADR-0022). It rides beside every extra corpus
    entry as the `.ns.yaml` sibling cage_engine.namespace_for reads, so the
    workload is classified in the cage it really runs in, not in the
    unlabelled default."""
    for path in sorted(adopter_dir.rglob("*.yaml")):
        if ".git" in path.parts:
            continue
        for doc in _docs(path):
            if doc.get("kind") == "Namespace" and \
                    ((doc.get("metadata") or {}).get("labels") or {}).get(GOVERNED_LABEL) == "true":
                return doc
    return None


def matrix_row(platform_dir: Path, adopter_dir: Path, party: str = PARTY) -> dict:
    """One row per policy version this institution claims: the bump IT takes
    moving from its own pin to the version the publisher's array now
    declares, computed with the published package over the published corpus
    plus this institution's own workloads."""
    sys.path.insert(0, str(Path(platform_dir) / "computed-semver"))
    import comparison_window          # noqa: E402  -- the PUBLISHED package
    import corpus_generator           # noqa: E402

    dist = Path(platform_dir) / "distribution"
    array = [str(e["version"])
             for e in corpus_generator._orphan_guard.elements(dist / "versions.yaml")]
    if not array:
        raise SystemExit("FAIL: platform's versions.yaml declares no versions")
    declared = max(array, key=comparison_window.parse_semver)
    tree_for = lambda v: dist / "policies" / f"v{v}"          # noqa: E731
    ns = governed_namespace(Path(adopter_dir))

    rows: dict[str, dict] = {}
    for version, workloads in sorted(claimed_versions(Path(adopter_dir)).items(),
                                      key=lambda kv: comparison_window.parse_semver(kv[0])):
        relative = [str(w.relative_to(adopter_dir)) for w in workloads]
        if version not in array:
            rows[version] = {
                "pinned_version": version, "computed_bump": None, "movement": [],
                "extra_corpus_entries": relative,
                "note": (f"{version} is not in the publisher's declared version array "
                         f"({', '.join(array)}) -- it is retired or was never published, so there "
                         f"is no line to classify. This institution is claiming a version nothing "
                         f"serves; that is the row, not a missing row."),
            }
            continue
        if comparison_window.parse_semver(version) >= comparison_window.parse_semver(declared):
            rows[version] = {
                "pinned_version": version, "computed_bump": "none", "movement": [],
                "extra_corpus_entries": relative,
                "note": f"already on the newest declared version ({declared}) -- nothing to move to",
            }
            continue

        corpus_dir = Path(tempfile.mkdtemp(prefix=f"matrix-{party}-{version}-"))
        manifest = corpus_generator.build_manifest(
            tree_for(version), tree_for(declared), inside_pin=declared, out_dir=corpus_dir)
        pods = [corpus_dir / rec["file"]
                for rec in manifest["populations"]["generated-spine"]["entries"]]
        # This institution's OWN workloads, added to the generated corpus as
        # extra entries -- each beside a copy of its real governed Namespace,
        # so the cage that classifies it is the cage it actually runs in.
        for i, workload in enumerate(workloads):
            for j, doc in enumerate(d for d in _docs(workload) if d.get("kind") == "Pod"):
                own = corpus_dir / f"own-{i}-{j}.yaml"
                own.write_text(yaml.safe_dump(doc, sort_keys=True))
                if ns is not None:
                    own.with_name(own.stem + ".ns.yaml").write_text(yaml.safe_dump(ns, sort_keys=True))
                pods.append(own)

        window = comparison_window.ComparisonWindow(
            old_window=[version], new_window=array, subject_tree_for=tree_for,
            institution_pins={party: version})
        outcome = comparison_window.evaluate(window, declared, tree_for(declared), pods)
        if outcome.pairing_failure is not None:
            rows[version] = {"pinned_version": version, "computed_bump": None, "movement": [],
                             "extra_corpus_entries": relative,
                             "note": f"pairing failure: {outcome.pairing_failure}"}
            continue
        row = dict(outcome.matrix[party])
        row["extra_corpus_entries"] = relative
        row["corpus_checksum"] = manifest["populations"]["generated-spine"]["checksum"]
        rows[version] = row

    return {
        "party": party,
        "declared_by_publisher": declared,
        "computed_by": "the adopter, with platform's published computed-semver package "
                       "(ticket 18 Answer 4) -- the publisher's own matrix is empty on purpose",
        "generator_version": corpus_generator.GENERATOR_VERSION,
        "rows": rows,
    }


def write_matrix_row(platform_dir: Path, adopter_dir: Path, party: str = PARTY) -> dict:
    """Compute the row and land it in this institution's own composed
    evidence, under `semver_matrix`.
      ponytail: composition.py rewrites composed/evidence.json wholesale on a
      re-compose, so this is re-run after one (shift-left.yml runs it after
      the compose step). Upgrade path: composition carries the key through.
    """
    row = matrix_row(platform_dir, adopter_dir, party)
    evidence_path = Path(adopter_dir) / "composed" / "evidence.json"
    document = json.loads(evidence_path.read_text()) if evidence_path.exists() else {}
    document["semver_matrix"] = row
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_text(json.dumps(document, indent=2))
    return row


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
    cp.add_argument("--adopter-dir", help="ADR-0011: read added/retired from this institution's own "
                                           "composed/evidence.json member set, not platform's raw array")
    cp.add_argument("--base-ref", help="commit-ish for composed/evidence.json 'before' (with --adopter-dir)")
    cp.add_argument("--head-ref", help="commit-ish for composed/evidence.json 'after' (with --adopter-dir)")

    mr = sub.add_parser("matrix-row", help="ticket 43 (18 Answer 4): compute THIS institution's "
                                            "per-institution matrix row with platform's published "
                                            "computed-semver package, over its own claimed versions "
                                            "and its own workloads, and land it in composed/evidence.json")
    mr.add_argument("platform_dir")
    mr.add_argument("--adopter-dir", dest="mr_adopter_dir", default=".")
    mr.add_argument("--print-only", action="store_true",
                     help="compute and print the row without writing composed/evidence.json")

    sb = sub.add_parser("splice-body", help="ticket cs-29: merge --section (already "
                                             "wrap_section()'d) into --current-body between the "
                                             "SECTION_START/SECTION_END markers, write --out-body")
    sb.add_argument("--current-body", required=True)
    sb.add_argument("--section", required=True)
    sb.add_argument("--out-body", required=True)

    ws = sub.add_parser("wrap-section", help="ticket cs-29: wrap --in (raw markdown, e.g. a "
                                              "shell-built refusal message) between the "
                                              "SECTION_START/SECTION_END markers, write --out -- "
                                              "for the one caller that doesn't already have "
                                              "adopter-gate.py's own pre-wrapped --markdown-out")
    ws.add_argument("--in", dest="in_path", required=True)
    ws.add_argument("--out", dest="out_path", required=True)

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

        if args.cmd == "matrix-row":
            if args.print_only:
                row = matrix_row(Path(args.platform_dir), Path(args.mr_adopter_dir))
            else:
                row = write_matrix_row(Path(args.platform_dir), Path(args.mr_adopter_dir))
            print(json.dumps(row, indent=2))
            return 0

        if args.cmd == "compose":
            adopter_dir = Path(args.adopter_dir) if args.adopter_dir else None
            result, evidence_by_version = run_compose(
                Path(args.platform_dir), args.old_tag, args.new_tag,
                adopter_dir=adopter_dir, base_ref=args.base_ref, head_ref=args.head_ref)
            print(json.dumps(result, indent=2))
            for reason in result["reasons"]:
                print(f"  - {reason}")
            if args.out:
                Path(args.out).write_text(json.dumps(
                    {"result": result, "evidence": evidence_by_version}, indent=2))
            if args.markdown_out:
                # Raw, UNwrapped markdown -- shift-left.yml embeds this under its own
                # header, then wraps the whole section once via `wrap-section` before
                # splicing. Pre-wrapping here would nest a second SECTION_START/END
                # pair inside the outer one.
                Path(args.markdown_out).write_text(render_markdown(result, evidence_by_version))
            if result["composed_bump"] == "major":
                print("REFUSED: composed bump is major", file=sys.stderr)
                return 1
            print(f"OK: composed bump is {result['composed_bump']!r}")
            return 0

        if args.cmd == "splice-body":
            current = Path(args.current_body).read_text()
            section = Path(args.section).read_text()
            Path(args.out_body).write_text(splice_body(current, section))
            return 0

        if args.cmd == "wrap-section":
            Path(args.out_path).write_text(wrap_section(Path(args.in_path).read_text()))
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

    # ---- ADR-0011: versions_from_composed_evidence + run_compose(adopter_dir=...) --
    # a REAL adopter repo, two REAL commits, no policy diff anywhere (party.yaml
    # and every rendered member are identical at both commits) -- only the
    # composed evidence document's own member set changes, exactly the shape
    # a retired platform version produces (composition.py's load_implementations
    # simply stops emitting that version's members; nothing in the adopter's
    # own repo names the retirement directly). ----
    adopter = Path(tempfile.mkdtemp(prefix="adopter-gate-adopter-"))
    _git(adopter, "init", "-q")
    (adopter / "composed").mkdir()

    def _write_evidence(members_versions: list[str]) -> None:
        doc = {"members": [{"name": f"member-{v}", "version": v} for v in members_versions]
                          + [{"name": "policy-version-orphan-guard", "version": None}]}
        (adopter / "composed" / "evidence.json").write_text(json.dumps(doc))

    _write_evidence(["2.0.0", "3.0.0"])
    _git(adopter, "add", "-A")
    _git(adopter, "commit", "-q", "-m", "base: 2.0.0, 3.0.0 live")
    base_sha = _git(adopter, "rev-parse", "HEAD").stdout.strip()

    _write_evidence(["3.0.0"])  # 2.0.0 retired from the composed set, nothing added
    _git(adopter, "add", "-A")
    _git(adopter, "commit", "-q", "-m", "head: 2.0.0 retired, no policy diff")
    head_sha = _git(adopter, "rev-parse", "HEAD").stdout.strip()

    old_v = versions_from_composed_evidence(adopter, base_sha)
    new_v = versions_from_composed_evidence(adopter, head_sha)
    assert old_v == {"2.0.0", "3.0.0"}, old_v
    assert new_v == {"3.0.0"}, new_v
    print("OK versions_from_composed_evidence: reads the real member set at a real commit, "
          "the platform-machinery guard (version: null) excluded")

    result, evidence_by_version = run_compose(
        platform, "v2.0.0", "v3.0.0",  # unused in this branch -- see run_compose's own docstring
        adopter_dir=adopter, base_ref=base_sha, head_ref=head_sha,
    )
    assert result["retired"] == ["2.0.0"], result
    assert result["added"] == [], result
    assert result["composed_bump"] == "major", result
    assert evidence_by_version == {}, evidence_by_version  # nothing added -- nothing to verify
    print("OK run_compose(adopter_dir=...): a version retired from the composed artefact's own "
          "member set classifies major, with no policy diff anywhere in the adopter's own repo "
          "-- ADR-0011's 'the composed bump is computed after composition', proved end to end")

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

    # ---- splice_body: ticket cs-29's actual delivery mechanism -- the PR
    # BODY itself, not a comment. First run appends after whatever's already
    # there (Renovate's own body); a re-run replaces only this gate's own
    # marked span, leaving the rest of the body (Renovate's content) intact.
    renovate_body = "This PR bumps `platform-pin.yaml` from v1.0.0 to v2.0.0.\n\n---\n\n - [ ] <!-- rebase-check -->"
    section1 = wrap_section("**Composed bump: `minor`**\n\nrun 1 evidence")
    spliced1 = splice_body(renovate_body, section1)
    assert renovate_body in spliced1, spliced1  # Renovate's own content survives
    assert section1.rstrip() in spliced1, spliced1
    assert spliced1.count(SECTION_START) == 1, spliced1
    print("OK splice_body: first run appends the marked section after Renovate's own body, untouched")

    section2 = wrap_section("**Composed bump: `major`**\n\nrun 2 evidence, supersedes run 1")
    spliced2 = splice_body(spliced1, section2)
    assert renovate_body in spliced2, spliced2  # still untouched
    assert "run 1 evidence" not in spliced2, spliced2  # old span is GONE, not appended alongside
    assert "run 2 evidence" in spliced2, spliced2
    assert spliced2.count(SECTION_START) == 1, spliced2  # replaced in place, never duplicated
    print("OK splice_body: a re-run replaces the prior span in place, never duplicates it")

    empty_first = splice_body("", section1)
    assert empty_first.startswith(SECTION_START), empty_first  # no spurious leading blank lines/separator
    print("OK splice_body: an empty starting body gets no leading separator")

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
