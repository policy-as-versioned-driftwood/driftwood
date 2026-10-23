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
| Signed source tag | `twin/v0.1.0`, published 2026-10-23; exact source and verification below |
| Source path | `twin/fixtures.py`, the `LIBRARY_WORLD_FILES` mapping |
| Files | 30: `world/meta.yaml`, 15 components, 13 propositions, 1 world model |
| Copied | byte-for-byte, verbatim, no edits |
| Stages to | `world_ref: c2d07330a778ed547b60cfbb87217bcf9813181f` in `orgs/driftwood/meta.yaml` |

Two pins, and they check each other. `PIN.yaml`'s `twin_version` must equal the hub's
`twin/VERSION` or `emit-forward-intel.py` refuses -- the release these bytes came from cannot
silently move underneath them. `world_ref` must equal the commit the vendored bytes stage to in
the emitter's deterministic mirror, or it refuses again: a pin that does not describe the bytes
beside it is not a pin.

**The tag.** `twin/v0.1.0` is prefixed because the hub repository also carries
other packages. The owner's hosted cut workflow signed annotated object
`b0d6140154d3619d6eff9ef499d837f8a8444300`, resolving to source commit
`0e353029f7f5b497a2fe19ef2874846119376d6e`.
The [published source release](https://github.com/policy-as-versioned-flux/policy-as-versioned-flux/releases/tag/twin/v0.1.0)
was published on 2026-10-23 at 15:56:21 UTC (release 422033887;
cut run 39982451070, publication run 39982502887). Production verification
accepted the canonical main `cut-release.yml` identity and GitHub OIDC issuer
and rejected a different identity. `PIN.yaml` therefore carries `tag_cut: true`.
Its full `hub_commit` remains an independent integrity anchor; `world_ref` pins
the unchanged vendored world bytes. Later code updates require a reviewed pin
and the same release checks. See `twin/RELEASE.md` in the hub.

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

This is the adopter's owned schema for its forward-intel envelope. Its base is the
immutable `platform/feeds/forward-intel.payload.schema.json` at authenticated tools
v5.0.0 (`703eff6aee959843c4160aa54fd03413f62858cc`). It preserves every canonical
property, requirement and type. Ticket 144 adds exactly two optional declarations:
`rests_on_grade` (integer grades 1–3) and `valuation` (the native amount/currency,
party fact, reporting amount/currency and nullable dated FX record). No inherited
constraint is removed and the closed property set remains closed.

The active schema is an owned extension, not a byte-for-byte vendored copy. It lives
inside this publishing repository because the envelope resolves `payload_schema`
here, and the feed can be validated offline from these self-contained bytes.
`verify-twin-overlay.sh` checks the complete canonical base semantically and the
exact two optional additions against the materialized authentic platform schema.
It reports could-not-look if that parent is absent; absence never proves agreement.

## First tagged code adoption

The signed `twin/v0.1.0` source package is published and its canonical cut-workflow
identity and issuer have been authenticated. The workflow requires `tag_cut: true`,
the literal initial tag and version, an annotated tag object, the exact full
`hub_commit` and checkout HEAD, and matching `twin/VERSION`. It verifies the tag
offline with the consumer-owned canonical main identity before executing hub code.
The emitter still checks the independent vendored `world_ref`.

This release publishes versioned source only. It establishes no actor attestation,
measured forecast, calibration, financial credit or production outcome. Historical
hub coverage remains unmeasured and its CI invariant remains red. No world,
overlay, financial or forward-intel bytes are replaced by this code pin.
