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
| Source commit | `ad6bc78d49c27b09ef66be385fa5c220d5bca153` |
| Source path | `twin/fixtures.py`, the `WORLD_FILES` mapping |
| Files | 9: `world/meta.yaml`, 4 components, 2 propositions, 2 world models |
| Copied | byte-for-byte, verbatim, no edits |

The hub has no signed semver tag yet, so the commit above is the only pin available; when `twin`
self-versions (ticket 11 answer item 1) this table names the tag instead and Renovate can bump it.

Re-vendoring is a two-line job:

```sh
.venv/bin/python -c 'import pathlib; from twin.fixtures import WORLD_FILES; [ (pathlib.Path(".estate-clone/driftwood/twin")/r).write_text(b, encoding="utf-8", newline="\n") for r,b in WORLD_FILES.items() ]'
.venv/bin/python .estate-clone/driftwood/twin/emit-forward-intel.py   # refuses until world_ref is re-pinned
```

The emitter refuses rather than adapts: `orgs/driftwood/meta.yaml`'s `world_ref` must equal the
commit the vendored bytes stage to, and a pin that does not describe the bytes beside it is not a
pin.

**Known gap, named rather than papered over.** The hub's only world layer is the twin's fixture
one, whose components and propositions are Netflix/Intel-flavoured. `cloud-compute` is the only
world component this overlay uses. Neither vendored proposition fits a UK retailer, so this
overlay declares **no scenarios** -- ticket 11 answer item 4's standing library of six scenarios
per adopter needs world propositions that do not exist yet, and inventing driftwood-shaped ones
inside a *shared* layer would be the direction violation the loader refuses. That library belongs
to the twin build ticket, with a driftwood-shaped world layer published first.

## `forward-intel/payload.schema.json`

The canonical home is `platform/feeds/forward-intel.payload.schema.json`, and the copy here is a
byte-for-byte vendoring of it. It is vendored beside the feed for two reasons:

1. a feed envelope's `payload_schema` is resolved **inside the publishing repository**
   (`verify/feed-contract/feed_contract.py`), so a path into another repo cannot validate; and
2. a departing adopter must be able to re-derive its prices offline from this checkout alone
   (spec.md, "A departing adopter").

`verify-twin-overlay.sh` byte-compares the two copies whenever the platform one is present, and
says it could not look when it is not. It never treats absence as agreement.
