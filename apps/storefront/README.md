# storefront — driftwood's own application

Lifted into driftwood by eco-system ticket 33 from `policy-as-versioned-flux/storefront` at commit
`a97344e4ba767564192240278492456ef76b8b2d`. Ticket 13's resolution put it here: driftwood is the
e-commerce institution, and a storefront is a retailer's application.

**This is driftwood's artefact now.** It is versioned by driftwood's own tags, its served workload
manifest is `gitops/apps/storefront.yaml` (rendered by `gitops/apps/kustomization.yaml`, which is
what this repository's Flux Kustomization reconciles at `path: ./gitops/apps`), it is graded by
driftwood's own `shift-left` job against driftwood's own composed policy set, and its dependency
tree is bumped by driftwood's own `renovate.json`. Nothing outside this repository reads it.

The tree below is the incumbent repository's tree, unchanged except for the four things a lift
changes: its `k8s/` manifest is removed (superseded by the served manifest above, re-labelled
and re-namespaced), its own `renovate.json` stub is removed (superseded by this repository's),
its release workflow is removed (see the residual below), and this README is rewritten -- the
incumbent's described a repository, this one describes a lift. Every other file is
byte-identical, so that a reader can `git diff` the tree against
`policy-as-versioned-flux/storefront` at that commit and see the whole of the move: `diff -rq`
against the incumbent reports `Only in incumbent: .github, k8s, renovate.json` and
`README.md differ`, and nothing else.

## The point of this app

A real, resolvable, deliberately stale npm tree — Angular 9, early 2020 — behind nginx. The
served page is hand-written static HTML; there is no `ng build`. The dependency staleness is the
signal, and the image ships the resolved `node_modules` so an image-mode scanner can see the real
tree rather than only a lockfile.

This is NOT the same workload as `deploy/pod.yaml` / `gitops/apps/pod.yaml`'s `checkout-svc`,
which is a bare `nginx` with no dependency tree at all and stays exactly as it is. This one is
driftwood's real front end.

## The residual: who builds the image

`gitops/apps/storefront.yaml` pins
`ghcr.io/policy-as-versioned-flux/storefront@sha256:ef53f41d380af4f56aa3e1f1e4ad922fa64e8f47361a41e83822fa8ace0f96bc`
— the digest the incumbent repository's own manifest pinned, built and published by the incumbent
org. The source moved and the build did not. Moving the build needs a new workflow job in this
repository and a container registry under `policy-as-versioned-driftwood`; both are on ticket 33's
`## Waits on the owner`. The hub's `verify/lifted-apps/` check counts the lifted apps whose image
is still published by the incumbent org and prints that count on every run, so this paragraph
cannot quietly stop being true without the gate saying so.
