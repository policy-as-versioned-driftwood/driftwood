#!/usr/bin/env python3
"""driftwood's own selection policy, version 1. The curve never picks; this does.

ADR-0021: the twin emits a scenario, `fair.py` annualises it, and a **versioned package the
adopter publishes and pins** turns the priced residuals into one cage tier. It lives here, in the
adopter's own repository, because whose money is at risk decides how much of it to carry -- and
because a rule that lives in an unversioned place cannot be pinned, reviewed or rolled back.

The rule, version 1:

    pick the loosest tier whose caged residual is under this party's own appetite tolerance;
    then clamp up to the party's declared overlay floor.

Two refusals, both missing instruments (ADR-0020): a residual in a currency the tolerance is not
stated in, and a tier name that is not on the ladder. Everything else is priced, never refused --
including "nothing is under tolerance", which fails closed to `isolated` rather than erroring.

Stdlib only, no imports from this repository or any other, so a consumer can vendor this one file
and re-derive a tier offline.

    python3 selection-policy/selection_policy.py        # the self-check
"""
from __future__ import annotations

import hashlib
import json

VERSION = "1.0.0"

# Loosest first (ADR-0022). `infra` is deliberately absent: only a platform-role party declares
# infra, and it declares it on a Namespace manifest, never through a price.
LADDER = ("baseline", "restricted", "quarantine", "isolated")
FAIL_CLOSED = LADDER[-1]


class MissingInstrument(ValueError):
    """No price in the tolerance's currency, or no such tier. The gate cannot read, so it must
    not emit a number (ADR-0020)."""


def curve_hash(curve):
    """The hash the proposal PR carries beside the policy version.

    Over the curve exactly as the feed published it, canonicalised (sorted keys, no whitespace) so
    the same curve hashes the same whatever wrote the JSON. A changed hash resets the rejection
    ledger, so it has to move when and only when the curve does.
    """
    canonical = json.dumps(curve, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def select(residuals, tolerance, floor=None):
    """One tier, and why.

    residuals: {tier: {"amount": float, "currency": "GBP"}} -- the caged residual under each tier,
               from the estate's own pricing. Tiers absent from the mapping are not candidates.
    tolerance: {"amount": float, "currency": "GBP"} -- party.yaml's signed `appetite.tolerance`.
    floor:     party.yaml's `overlay.floor`, or None. Tighten-only: the selection clamps up to it
               and never below it.

    Returns {tier, policy_version, basis, clamped}.
    """
    if not isinstance(tolerance, dict) or "amount" not in tolerance or "currency" not in tolerance:
        raise MissingInstrument(
            "no signed appetite.tolerance for this party: whose money is at risk is the party's "
            "own declaration, and there is no fixture to fall back to"
        )
    currency = str(tolerance["currency"])
    limit = float(tolerance["amount"])

    priced = {}
    for tier, price in residuals.items():
        if tier not in LADDER:
            raise MissingInstrument(
                "%r is not on the ladder %s; an unknown tier cannot be selected, and guessing "
                "which rung it meant would be a loosening nobody signed" % (tier, list(LADDER))
            )
        if str(price["currency"]) != currency:
            raise MissingInstrument(
                "residual for %r is in %s and the tolerance is in %s. Restating one in the other "
                "needs an FX rate from the signed fx feed for this price's date; without it there "
                "is no comparison to make (ADR-0020)" % (tier, price["currency"], currency)
            )
        priced[tier] = float(price["amount"])

    # `<=`, not `<`: a residual that lands exactly ON the band still fits inside it, and
    # this has to agree with the estate's own engine (platform/graded/cage.py:select_tier)
    # to the boundary -- verify/pound-seam runs both over the same residuals and refuses a
    # disagreement. A band is a limit you may reach, not one you must stay under.
    under = [t for t in LADDER if t in priced and priced[t] <= limit]
    if under:
        chosen = under[0]
        basis = "loosest tier whose caged residual (%.2f %s) is within the tolerance (%.2f %s)" % (
            priced[chosen], currency, limit, currency)
    else:
        chosen = FAIL_CLOSED
        basis = "no priced tier is under the tolerance (%.2f %s), so the selection fails closed" % (
            limit, currency)

    clamped = False
    if floor is not None:
        if floor not in LADDER:
            raise MissingInstrument(
                "declared floor %r is not on the ladder %s" % (floor, list(LADDER)))
        if LADDER.index(chosen) < LADDER.index(floor):
            chosen, clamped = floor, True
            basis += "; clamped up to the party's declared floor %r" % floor

    return {"tier": chosen, "policy_version": VERSION, "basis": basis, "clamped": clamped}


def _selfcheck():
    gbp = lambda a: {"amount": a, "currency": "GBP"}  # noqa: E731
    tol = gbp(40000)
    residuals = {"baseline": gbp(90000), "restricted": gbp(38000), "quarantine": gbp(12000),
                 "isolated": gbp(4000)}

    # the loosest tier under tolerance, not the cheapest one
    assert select(residuals, tol)["tier"] == "restricted"

    # the floor is tighten-only: it clamps up and never down
    assert select(residuals, tol, floor="quarantine")["tier"] == "quarantine"
    assert select(residuals, tol, floor="quarantine")["clamped"] is True
    assert select(residuals, tol, floor="baseline")["tier"] == "restricted"

    # nothing under tolerance fails closed rather than erroring
    assert select({"baseline": gbp(90000)}, tol)["tier"] == "isolated"

    # a tighter tolerance selects a tighter tier -- the £ moves the cage
    assert select(residuals, gbp(10000))["tier"] == "isolated"

    # the boundary: a residual exactly ON the band is inside it, same as the estate's
    # engine. This is the case the two implementations used to disagree about.
    assert select(residuals, gbp(38000))["tier"] == "restricted"

    # two missing instruments
    for bad, why in (
        (lambda: select({"baseline": {"amount": 1, "currency": "USD"}}, tol), "mixed currency"),
        (lambda: select({"paranoid": gbp(1)}, tol), "tier off the ladder"),
    ):
        try:
            bad()
        except MissingInstrument:
            pass
        else:
            raise AssertionError("%s was not refused" % why)
    try:
        select(residuals, {"amount": 1})
    except MissingInstrument:
        pass
    else:
        raise AssertionError("a tolerance with no currency was not refused")

    # the hash is stable under key order and whitespace, and moves when the curve does
    curve = [{"account": "driftwood-base-case", "net_cost_of_risk": 384000.0},
             {"account": "loss-lands-as-chargebacks", "net_cost_of_risk": 160000.0}]
    assert curve_hash(curve) == curve_hash(json.loads(json.dumps(curve, indent=4)))
    assert curve_hash(curve) != curve_hash(curve[:1])

    print("ok  selection-policy v%s: %d asserts" % (VERSION, 13))


if __name__ == "__main__":
    _selfcheck()
