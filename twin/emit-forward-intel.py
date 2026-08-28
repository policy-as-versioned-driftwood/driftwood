#!/usr/bin/env python3
"""Render driftwood's forward-intel feed from driftwood's own twin overlay.

ADR-0019 (the envelope), ADR-0021 (the seam). The twin emits a **scenario**; the estate
annualises it with `fair.py` and a versioned selection policy picks the tier. So this script
carries no frequency, no *selected* tier and -- ever -- no recommended action. It prices every
rung of the ladder and picks none of them; the payload schema beside it is closed, and
`verify-twin-overlay.sh` greps the emitted bytes for an action-shaped key as well.

Deterministic. The same overlay in gives byte-identical output, on any machine and at any time:

* `version` and `published_at` are the publisher's own declaration (the constants below), bumped
  by the release PR that also writes `bump.yaml`. Nothing here reads a wall clock.
* the overlay and world pins in `derived_from` come from a **staging mirror**: `world/` and
  `orgs/` are copied into a throwaway git repository committed with the twin fixtures' fixed
  identity and date, so the pins are content-addressed and identical everywhere. That is also
  what lets this run against an uncommitted working tree -- `twin.repo.ModelRepo` reads through
  a tree object and refuses a dirty one, and the mirror is never dirty.

  The mirror stages `world/` and `orgs/` and nothing else, deliberately: editing this script, or
  the payload schema, or anything else in the repository must not move the feed's bytes.

Run it (needs the hub's `twin` package and pyyaml):

    .venv/bin/python .estate-clone/driftwood/twin/emit-forward-intel.py           # write
    .venv/bin/python .estate-clone/driftwood/twin/emit-forward-intel.py --check   # compare only
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
ORG = "driftwood"

# The publisher's own declaration. A release bumps these two lines and `forward-intel/bump.yaml`
# in the same PR a human merges -- they are not derived from the overlay, which is exactly why a
# re-emit at any hour of any day produces the same bytes.
VERSION = "1.0.0"
PUBLISHED_AT = "2026-08-28T00:00:00Z"
HORIZON = 1  # years; ticket 08: "horizon is one year and is stated in the payload"

# The publisher's own declaration of what a claim off this scenario covers, keyed the way the
# insurer's exclusions are (regime names, or `source:id` control keys). Declared rather than
# derived: only driftwood can say what it is claiming, and an unstated scope is an unbounded one.
# Reviewed in the release PR beside VERSION.
CLAIM_INCLUDED = ["uk-gdpr"]
CLAIM_EXCLUDED = ["pci-dss"]
CLAIM_NOTE = (
    "The shock is an exfiltration of customer records, priced under the one regime this party "
    "subscribes to a pricing feed for. Card-scheme penalties are carved out: no publisher in this "
    "party's inherits[] prices pci-dss, so a number here would have no instrument behind it."
)

FEED_DIR = HERE / "forward-intel"
FEED_FILE = FEED_DIR / f"v{VERSION.split('.')[0]}" / "feed.json"
PAYLOAD_SCHEMA = "twin/forward-intel/payload.schema.json"

# The cage rungs this overlay prices, read from this repo's own versioned selection policy rather
# than spelled a second time here: the curve's accounts and the tiers the policy can select must
# be the same list, and a second spelling is a list that silently stops matching.
POLICY_DIR = REPO / "selection-policy"
RESPONSE_ID = "run-the-checkout-at-%s"


def hub() -> Path:
    """The checkout that carries the `twin` package.

    ponytail: located by walking up, because `twin` does not self-version yet -- the hub has no
    signed semver tag, so there is nothing for this repo to pin (ticket 11 answer item 1). When it
    cuts one, this becomes an ordinary pinned dependency and this function goes.
    """
    for parent in [HERE, *HERE.parents]:
        if (parent / "twin" / "repo.py").is_file() and (parent / "clone-estate.sh").is_file():
            return parent
    sys.exit(
        "REFUSED: no checkout of the `twin` package above %s. This overlay is rendered by the "
        "hub's twin loader; without it there is nothing to load the overlay with." % HERE
    )


sys.path.insert(0, str(hub()))
import yaml  # noqa: E402
from twin import evidence, fixtures  # noqa: E402
from twin.model import Overlay  # noqa: E402
from twin.repo import ModelRepo  # noqa: E402
from twin.schema import CAUSAL_EDGE  # noqa: E402


def policy():
    """This repo's own selection-policy package, at the version PIN.yaml pins."""
    import importlib.util

    pinned = str(yaml.safe_load((POLICY_DIR / "PIN.yaml").read_text())["policy_version"])
    spec = importlib.util.spec_from_file_location("selection_policy", POLICY_DIR / "selection_policy.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if module.VERSION != pinned:
        sys.exit("REFUSED: selection-policy/PIN.yaml pins %s and selection_policy.py is %s. A pin that does "
                 "not describe the code beside it is not a pin." % (pinned, module.VERSION))
    return module


def stage(dest: Path) -> Path:
    """Copy `world/` and `orgs/` into a deterministic two-commit git mirror and return it.

    Two commits, in this order, for the reason `twin.fixtures.build` does it: the world layer
    lands first so the overlay can pin the world commit it resolves against.
    """
    for unit in ("world", "orgs"):
        shutil.copytree(HERE / unit, dest / unit)
    fixtures.git(dest, "init", "-q", "-b", "main", "--object-format=sha1")
    fixtures.git(dest, "add", "-A", "world")
    fixtures.git(dest, "commit", "-q", "-m", "vendored world layer")
    world_commit = fixtures.git(dest, "rev-parse", "HEAD").strip()
    declared = str(yaml.safe_load((HERE / "orgs" / ORG / "meta.yaml").read_text())["world_ref"])
    if declared != world_commit:
        sys.exit(
            "REFUSED: orgs/%s/meta.yaml pins world_ref %s, and the vendored world layer stages to "
            "%s. A pin that does not describe the bytes beside it is not a pin." % (ORG, declared, world_commit)
        )
    fixtures.git(dest, "add", "-A")
    fixtures.git(dest, "commit", "-q", "-m", "driftwood overlay")
    return dest


def cash_flow_edge(graph, cash_flow: str):
    """The one graded causal edge that carries an impact into this perspective's currency."""
    hits = [e for e in graph.edges if e.type == CAUSAL_EDGE and e.target == cash_flow]
    if len(hits) != 1:
        sys.exit(
            "REFUSED: %d causal edges reach the declared cash flow %r; this payload prices one "
            "shock, so the overlay must carry exactly one." % (len(hits), cash_flow)
        )
    edge = hits[0]
    if not evidence.may_price(edge.grade):
        sys.exit(
            "REFUSED: causal edge %r is grade %d, outside the pricing threshold of %d. An impact "
            "that may not price cannot leave as a number." % (edge.id, edge.grade, evidence.threshold())
        )
    return edge


def money(amount: float) -> float:
    """Two decimal places. Rounded here rather than at the reader, so every consumer of this feed
    reads the same bytes; the underlying multiplication is IEEE-754 and portable either way."""
    return round(float(amount), 2)


def curve(overlay: Overlay, ladder, impact: float) -> list[dict]:
    """What one shock costs under each rung of the cage ladder: what is left of the impact after
    that rung's graded mitigation claim, plus what the rung itself costs to run.

    Each rung is an authored `response` in the overlay, with its own cost triple and its own
    graded `mitigates` claim -- so tightening a rung earns nothing on its own, and a rung that
    claims a reduction has to carry the evidence for it like any other causal claim.

    The figures are per shock, in `currency`, and are NOT annualised: `lef` is null, and the
    estate multiplies the frequency in from the subscribed pricing feed. The selection policy
    reads the estate's annualised residuals, never these.
    """
    out = []
    for tier in ladder:
        response = overlay.responses.get(RESPONSE_ID % tier)
        if response is None:
            sys.exit(
                "REFUSED: the ladder has a %r rung and this overlay prices no response for it. A "
                "curve missing a rung reads as a rung nobody would choose, which is a different "
                "claim from one nobody priced." % tier
            )
        reduction = float(response["mitigates"]["reduction"]["mode"])
        cost = float(response["cost"]["mode"])
        out.append({"account": tier, "net_cost_of_risk": money(impact * (1.0 - reduction) + cost)})
    return out


def payload(overlay: Overlay, currency: str, party: dict) -> dict:
    perspective = overlay.perspectives[ORG]
    cash_flow = str(perspective["cash_flow"][0])
    values = perspective["values"]
    priced = {c: v for c, v in sorted(values.items()) if "amount" in v}
    if cash_flow not in priced:
        sys.exit("REFUSED: perspective %r declares %r as its cash flow and puts no priced valuation "
                 "on it, so nothing can cross into the currency." % (ORG, cash_flow))
    base = float(priced[cash_flow]["amount"])
    edge = cash_flow_edge(overlay.graph(), cash_flow)
    elasticity = edge.causal["elasticity"]

    # One magnitude claim, from this overlay's own numbers: the share of the declared cash flow the
    # graded edge says one shock takes. ponytail: a bounded triple, so `fair.py` reports
    # tail=bounded-pert. The lognormal-GPD spec the schema also admits (ticket 08 decision 7)
    # needs a fitted tail, and this overlay carries no own-data observations and no world-layer
    # prior to fit one from; publish those first, then emit the spec here.
    lm = [money(base * float(elasticity[k])) for k in ("min", "mode", "max")]

    # Every pinned input, in the same shape as inherits[] so provenance reads the same way on both
    # sides of the seam, plus this overlay's own ref. The overlay commit's tree carries the
    # vendored world layer too, so one ref pins both.
    derived_from = [
        {k: str(i[k]) for k in ("party", "kind", "name", "version") if k in i}
        for i in party.get("inherits") or []
    ]
    for entry in derived_from:
        entry["version"] = entry["version"].lstrip("v")
    derived_from.append({
        "party": ORG, "kind": "feed", "name": "forward-intel", "version": VERSION,
        "ref": overlay.ref.commit,
    })

    return {
        "perspective": ORG,
        "shock": str(overlay.edges[edge.id]["note"]).strip(),
        "horizon": HORIZON,
        # Null: this twin has no frequency. The subscribed pricing feed supplies it, and that
        # subscription is in derived_from above rather than asserted here.
        "lef": None,
        "lm": lm,
        "currency": currency,
        "curve": curve(overlay, policy().LADDER, base * float(elasticity["mode"])),
        # Empty, and that is a real answer: this overlay names no control it leaves unpriced. It
        # stays empty until one is named, because the tier a register entry takes is the tier the
        # priced hits selected -- and the twin does not select tiers.
        "register": [],
        "claim_scope": {"included": CLAIM_INCLUDED, "excluded": CLAIM_EXCLUDED, "note": CLAIM_NOTE},
        "derived_from": derived_from,
    }


def envelope(body: dict) -> dict:
    return {
        "kind": "feed",
        "name": "forward-intel",
        "version": VERSION,
        "published_by": ORG,
        "published_at": PUBLISHED_AT,
        "payload_schema": PAYLOAD_SCHEMA,
        "payload": body,
    }


def render() -> str:
    party = yaml.safe_load((REPO / "party.yaml").read_text())
    reporting = str(party.get("reporting_currency", "USD"))  # ADR-0020: the default is USD
    declared = yaml.safe_load((HERE / "currency.yaml").read_text())["perspectives"]
    currency = str(declared[ORG])
    if currency != reporting:
        sys.exit(
            "REFUSED: perspective %r values in %s and party.yaml reports in %s. Restating one in "
            "the other needs an FX rate from the signed fx feed for this price's date, and a "
            "missing rate is a missing instrument (ADR-0020)." % (ORG, currency, reporting)
        )
    with tempfile.TemporaryDirectory() as tmp:
        repo = ModelRepo.open(stage(Path(tmp) / "mirror"))
        overlay = Overlay.load(repo, ORG)
        return json.dumps(envelope(payload(overlay, currency, party)), indent=2, ensure_ascii=False) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the file on disk is not what this run renders")
    args = ap.parse_args(argv)
    rendered = render()
    if args.check:
        on_disk = FEED_FILE.read_text() if FEED_FILE.is_file() else None
        if on_disk != rendered:
            print("FAIL: %s is not what the overlay renders" % FEED_FILE.relative_to(REPO))
            return 1
        print("ok  %s is byte-identical to a fresh render of the overlay" % FEED_FILE.relative_to(REPO))
        return 0
    FEED_FILE.parent.mkdir(parents=True, exist_ok=True)
    FEED_FILE.write_text(rendered)
    print("wrote %s (%d bytes)" % (FEED_FILE.relative_to(REPO), len(rendered)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
