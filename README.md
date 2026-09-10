# policy-as-versioned-driftwood

**GitHub org:** [`policy-as-versioned-driftwood`](https://github.com/policy-as-versioned-driftwood) ·
**Role:** institution — risk-bearer, adopter · **Licence:** [Apache-2.0](LICENSE)

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.*

Part of the *Policy as Versioned Code* estate: a shared platform, two regulators, three regulated
institutions, each its own independent GitHub organisation, exchanging signed, versioned
dependencies. Full thesis, design decisions (ADRs) and the other five parties:
[policy-as-versioned-flux](https://github.com/policy-as-versioned-flux/policy-as-versioned-flux).

**Institution — e-comm, PCI + GDPR, the teaching default.** Audit-heavy (loosest
£ — short-life cart data). Owns its own KinD cluster; this is the **provenance
base** the whole talk stacks on: Flux reconciling a pinned, signed
`GitRepository` at admission.

## Bring-up (idempotent, offline-safe, resettable — the touring requirement)

```sh
scripts/up.sh          # KinD -> Flux -> in-cluster git source -> reconcile healthy
verify-reconcile.sh    # asserts the beat (exits non-zero if it would fail on stage)
scripts/reset.sh       # delete the cluster (or: reset.sh soft = re-seed only)
```

`up.sh` is safe to re-run: it skips the cluster/Flux if already up and re-seeds
the source. Everything after the first controller-image pull is offline.

## How the source works

For the tour there is no network luck: `up.sh` seeds the [`gitops/`](gitops/)
tree into a git repo, tags it `v1.0.0`, bakes it into a tiny
[`git-server/`](git-server/) image (busybox-httpd smart-HTTP CGI over
`git-http-backend`), `kind load`s it, and points a `GitRepository` **pinned to
that tag + commit SHA** at the in-cluster service. Git is the only way cluster
state changes; the revision is immutable.

The committed [`gitops/flux-system/gotk-sync.yaml`](gitops/flux-system/gotk-sync.yaml)
is the canonical form pointed at the real `policy-as-versioned-driftwood` GitHub
remote — where the `v1.0.0` tag is **gitsign-signed** (keyless → Rekor) and
verified in the provenance beat (ticket 24). Flux's `GitRepository.spec.verify`
only speaks OpenPGP, so the gitsign signature is verified out-of-band by
`git verify-tag` / Rekor rather than mis-declared as a PGP block; the pin + the
signed tag are the provenance.

## Pinned regulator dependency (`nist`)

`gitops/flux-system/gotk-sync-nist.yaml` pins a specific signed tag+commit of
the real `nist` 800-53 OSCAL catalog (`estate/nist`) as a Flux `GitRepository`
— the same in-cluster git server driftwood's own source uses, serving both
bare repos. `driftwood-nist-pin` (`gitops/apps/nist-pin-configmap.yaml`) is
the human/audit-readable mirror of that pin. `verify-reconcile.sh` asserts
both reconcile Ready and pinned.

A regulator version bump arrives as a reviewable PR:
`scripts/bump-nist-pin.sh v1.1.0` edits the pin on a branch and prints the
diff — propose only, a human merges. (Ticket 17's cage-tier proposer,
`.github/workflows/propose-tier.yml`, is the one exception in this repo: it
actually commits, pushes and opens — see
[`platform`'s `wargamer/README.md`](https://github.com/policy-as-versioned-platform/platform/blob/main/wargamer/README.md)
for the safety property that stays the same either way.)

## Pinned platform dependency (the config-base pattern)

`gitops/platform/platform-pin.yaml` pins a specific signed tag+commit of
`platform` and reconciles its `./distribution` — flux-operator fans the version
array out into this cluster (per-version policies + orphan-guard). driftwood
consumes the discipline; it never authors it. Opt-in (not in the Phase-0 `apps`
reconcile) and needs Kyverno + flux-operator installed first — see
[`platform`'s `distribution/README.md`](https://github.com/policy-as-versioned-platform/platform/blob/main/distribution/README.md).
A platform bump arrives as a reviewed PR editing `.spec.ref.tag` here.

## What's here now vs later

Phase 0 (this ticket): cluster + Flux + one reconciled version marker. Later
tickets add the Kyverno CEL policy set (fanned out from platform's `ResourceSet`
version array), the `ico` pin, and the risk skin.

## Compiler tools and accepted implementations

`.github/platform-tools-pin.yaml` pins the compiler software independently of
`gitops/platform/platform-pin.yaml` and `party.yaml`'s implementation inheritance.
The compiler is currently `v3.0.0`; the accepted implementation stays `v2.0.1`
(policy members `{4.0.0}`). Updating tools does not accept a new policy window.
The existing adopter gate still refuses additions classified as major.

PR composition, release replay, tier proposals and Renovate completion use the
same verified tools runner. It checks the tool tag's commit and the exact platform
`cut-release.yml` signing identity before executing it. Missing pins/verifiers,
moved tags and wrong identities fail closed. The tools pin is outside GitOps and
is never deployed. Local runners need Python with PyYAML and gitsign 0.17.1. The shared
installer provisions the checksum-pinned verifier before CI and Renovate run,
under `RUNNER_TEMP`; it leaves the observed checkout untouched.

For local composition, keep all five parent clones at this adopter's exact
GitRepository pins under `$estate_dir`, including `platform` at the implementation
pin. Separately check out the tools tag at `$estate_dir/platform-tools` with full
history and tags. From this adopter checkout:

```bash
python3 .github/scripts/platform-tools.py --tools-dir "$estate_dir/platform-tools" check
python3 .github/scripts/verify-pinned-checkouts.py \
  gitops/platform/platform-pin.yaml "$estate_dir/platform" \
  gitops/flux-system/gotk-sync-nist.yaml "$estate_dir/nist" \
  gitops/flux-system/gotk-sync-ico.yaml "$estate_dir/ico" \
  gitops/flux-system/gotk-sync-feeds.yaml "$estate_dir/feeds" \
  gitops/flux-system/gotk-sync-insurer.yaml "$estate_dir/insurer"
python3 .github/scripts/platform-tools.py --tools-dir "$estate_dir/platform-tools" \
  compose . --estate-clone "$estate_dir" --out .
python3 .github/scripts/platform-tools.py --tools-dir "$estate_dir/platform-tools" \
  verify . --estate-clone "$estate_dir"
python3 -m unittest discover -s tests -p 'test_platform_tools.py'
```

Delegated architectural decision (ADR-0025, 2026-09-10): use the composer's existing
separate executable and `--estate-clone` inputs instead of changing party schema
or filtering inherited policies. This makes software maintenance possible without
making the owner's policy acceptance decision. Fresh provenance records publisher
observations as observed, including an explicit inability to price newer feed
majors absent from the pinned publisher checkout. Money, appetite, original dates,
and enacted deployment pins are unchanged.
