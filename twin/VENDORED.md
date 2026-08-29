# What is vendored here, and at which ref

## `world/` -- the twin's shared world layer

An overlay may reference the world layer and the world layer may never reference an overlay, and
`twin/model.py Overlay.load` resolves `world_ref` on the **same** `ModelRepo`. So an overlay that
lives in an adopter's own repository must carry the world layer in the same git tree, or the
loader would have to learn a second repository (ticket 11 answer item 1). It is vendored, not
imported.

| | |
|---|---|
| Source repository | `policy-as-versioned-flux` (the hub) |
| Source release | `twin` **0.1.0** (`twin/VERSION`), pinned machine-readably in `PIN.yaml` |
| Tag the owner must cut | `twin/v0.1.0` -- **not cut yet**, see below |
| Source path | `twin/fixtures.py`, the `LIBRARY_WORLD_FILES` mapping |
| Files | 30: `world/meta.yaml`, 15 components, 13 propositions, 1 world model |
| Copied | byte-for-byte, verbatim, no edits |
| Stages to | `world_ref: c2d07330a778ed547b60cfbb87217bcf9813181f` in `orgs/driftwood/meta.yaml` |

Two pins, and they check each other. `PIN.yaml`'s `twin_version` must equal the hub's
`twin/VERSION` or `emit-forward-intel.py` refuses -- the release these bytes came from cannot
silently move underneath them. `world_ref` must equal the commit the vendored bytes stage to in
the emitter's deterministic mirror, or it refuses again: a pin that does not describe the bytes
beside it is not a pin.

**The tag.** `twin/v0.1.0` is prefixed because the hub repository is not only the twin. It does
not exist yet: a signed tag is cut by a release workflow with gitsign, never on a laptop, so until
the owner merges and that workflow runs, `world_ref` is the only pin with bytes behind it and
`PIN.yaml` carries `tag_cut: false`. When the tag lands, Renovate's `git-refs` datasource bumps
`twin_version` and `twin_tag` together the way `gitops/platform/platform-pin.yaml` is bumped
today. See `twin/RELEASE.md` in the hub.

Re-vendoring is a two-line job:

```sh
.venv/bin/python -c 'import pathlib; from twin.fixtures import LIBRARY_WORLD_FILES as W; [ (pathlib.Path(".estate-clone/driftwood/twin")/r).write_text(b, encoding="utf-8", newline="\n") for r,b in W.items() ]'
.venv/bin/python .estate-clone/driftwood/twin/emit-forward-intel.py   # refuses until world_ref is re-pinned
```

**What changed at ticket 29.** This directory used to vendor the hub's *default* world layer
(`WORLD_FILES`), whose components and propositions are Netflix/Intel-flavoured, and the gap was
recorded here: no proposition in it fitted a UK retailer, so the overlay declared no scenarios. It
now vendors the **standing-library** world layer instead -- the one that is generic by
construction, names no tenant, and carries one proposition per committed scenario class. That is
what lets `orgs/driftwood/scenarios/` hold the six standing scenarios (ticket 11 answer item 4)
without inventing driftwood-shaped propositions inside a *shared* layer, which is the direction
violation the loader refuses. `cloud-compute`, which `cart-checkout-service` needs, is in that
layer as the same bytes as the default layer's copy rather than a second spelling of it.

### The priors in `world/world_models/reference-map.yaml` are AUTHORED, not measured

Every causal edge in this estate carries an `evidence_grade` and a written basis. The prior
beliefs in the reference map carry neither, because the `world_models` schema has no grade field:
they are floats typed into `twin/fixtures.py` by whoever added the scenario class. Four of them
arrived with ecosystem ticket 29 --
`a-pinned-dependency-passes-its-published-end-of-life-date` 0.45,
`a-regulator-publishes-a-penalty-under-a-regime-in-force` 0.5,
`a-rival-reads-the-published-exposure-and-acts-on-it` 0.25,
`a-publisher-withdraws-a-feed-the-organisation-pins` 0.1 -- and vendoring put them inside
driftwood's own signed tree, where they read like measured facts.

They reach no price today: `emit-forward-intel.py` prices off the graded cash-flow edge and loads
neither scenarios nor world models, so no premium and no exposure figure depends on any of them.
The exposure is the path, not the present state. **If a later ticket wires scenario execution into
the pound, these are grade 5 -- asserted, not measured -- and the `path_admission_threshold` must
refuse them until the `world_models` schema carries a grade and each belief carries a basis.**
Until then, read every number in that file as an authored prior, and `verify-twin-scenarios.sh`
check 6 as a presence check on the map, never a provenance check on its contents.

## `forward-intel/payload.schema.json`

The canonical home is `platform/feeds/forward-intel.payload.schema.json`, and the copy here is a
byte-for-byte vendoring of it. It is vendored beside the feed for two reasons:

1. a feed envelope's `payload_schema` is resolved **inside the publishing repository**
   (`verify/feed-contract/feed_contract.py`), so a path into another repo cannot validate; and
2. a departing adopter must be able to re-derive its prices offline from this checkout alone
   (spec.md, "A departing adopter").

`verify-twin-overlay.sh` byte-compares the two copies whenever the platform one is present, and
says it could not look when it is not. It never treats absence as agreement.
