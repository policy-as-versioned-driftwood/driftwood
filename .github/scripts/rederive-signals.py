#!/usr/bin/env python3
"""Re-derive twin/signals.yaml's pin rows from party.yaml's inherits[] (eco-system ticket 72).

The signal lookup is a table the clock cannot argue with (ticket 29): every pin on party.yaml
resolves to exactly one dated signal, keyed by the pin as inherits[] spells it. When Renovate
moves a pin, the row keyed on the OLD version stops resolving and the new pin has no row --
`verify-twin-scenarios.sh` check 8 went red that way on the first real feed bump (ticket 61,
driftwood PR #20, threat-register v1 -> v2), and would go red the same way on every bump after.

This script is the mechanical half of the file's own upgrade path ("when renovate-run.yml moves
a pin it edits this file's version in the same PR, and the row's signal.at becomes the merge
date"). For each subscription (party, kind, name) it matches the row to the pin and, when the
version differs, rewrites three things and nothing else:

  * `pin.version`             -> the version party.yaml now pins
  * the version token in `id` -> the same (`feeds-threat-register-v1-...` -> `...-v2-...`)
  * `signal.at`               -> the date the row was re-derived (--at, default today UTC):
                                 the dated fact is "subscribed to that version since then"

`scenario` and `what` are never touched: which standing question a subscription moves is a
human's binding, and a version bump does not change it.

What it REFUSES, because each is a judgement and not a rewrite (exit 2, `REFUSED: ...` last):

  * a pin with no row for its (party, kind, name) -- a NEW subscription needs a human-authored row
  * a row for a subscription party.yaml no longer carries -- dropping it may leave a scenario
    unbound, and declaring it unbound with a reason is a human's line to write
  * two rows for one subscription, or an `id` that carries no `-<version>-` token to rewrite

The file is edited as TEXT, line by line, so its comments and block scalars survive; a yaml
round-trip would flatten both. Runs on python3 + pyyaml, nothing else, from anywhere:

    python3 .github/scripts/rederive-signals.py            # rewrite in place, say what moved
    python3 .github/scripts/rederive-signals.py --check    # exit 1 if a rewrite is pending
    python3 .github/scripts/rederive-signals.py selfcheck  # planted fixtures, exit 0 when they bite
"""
from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]
PARTY = REPO / "party.yaml"
LOOKUP = REPO / "twin" / "signals.yaml"

ROW_START = re.compile(r"^  - pin:\s*\{")
BLOCK_END = re.compile(r"^\S")  # a top-level key or comment ends the last row


class Refused(Exception):
    pass


def key3(d: dict) -> tuple[str, str, str]:
    return (str(d.get("party")), str(d.get("kind")), str(d.get("name") or ""))


def _row_blocks(lines: list[str]) -> list[tuple[int, int]]:
    """(start, end) line spans of each `  - pin:` row, in file order."""
    starts = [i for i, line in enumerate(lines) if ROW_START.match(line)]
    spans = []
    for n, start in enumerate(starts):
        end = starts[n + 1] if n + 1 < len(starts) else len(lines)
        for j in range(start + 1, end):
            if BLOCK_END.match(lines[j]):
                end = j
                break
        spans.append((start, end))
    return spans


def _sub_once(pattern: str, repl: str, text: str, what: str) -> str:
    new, n = re.subn(pattern, repl, text, count=2)
    if n != 1:
        raise Refused(f"{what}: expected exactly one match for {pattern!r}, found {n}")
    return new


def rederive(party_text: str, lookup_text: str, at: str) -> tuple[str, list[str]]:
    """Return (new lookup text, one line per rewritten row). Raise Refused on a hole."""
    party = yaml.safe_load(party_text) or {}
    lookup = yaml.safe_load(lookup_text) or {}
    pins = {}
    for pin in party.get("inherits") or []:
        k = key3(pin)
        if k in pins:
            raise Refused(f"party.yaml pins {'/'.join(k)} twice")
        pins[k] = str(pin.get("version"))
    rows = lookup.get("signals") or []
    lines = lookup_text.splitlines(keepends=True)
    spans = _row_blocks(lines)
    if len(spans) != len(rows):
        raise Refused(f"signals.yaml parses to {len(rows)} rows but {len(spans)} `  - pin:` "
                      f"lines were found; the rows must be inline-mapping pins, one per row")

    seen: dict[tuple[str, str, str], int] = {}
    for i, row in enumerate(rows):
        k = key3(row.get("pin") or {})
        if k in seen:
            raise Refused(f"two rows for {'/'.join(k)} (rows {seen[k] + 1} and {i + 1}); the "
                          f"table binds each subscription once")
        seen[k] = i
    missing = sorted("/".join(k) for k in pins if k not in seen)
    if missing:
        raise Refused(f"no row for {', '.join(missing)}: a new subscription needs a "
                      f"human-authored row binding it to a standing scenario")
    orphan = sorted("/".join(k) for k in seen if k not in pins)
    if orphan:
        raise Refused(f"row(s) for {', '.join(orphan)}, which party.yaml no longer pins: a "
                      f"dropped subscription is a human's call (declare the scenario unbound "
                      f"with a reason, or remove the row)")

    changes = []
    for i, row in enumerate(rows):
        k = key3(row["pin"])
        old, new = str(row["pin"].get("version")), pins[k]
        if old == new:
            continue
        sid = str((row.get("signal") or {}).get("id") or "")
        if f"-{old}-" not in sid:
            raise Refused(f"row {'/'.join(k)}: id {sid!r} carries no -{old}- token, so the "
                          f"version cannot be rewritten mechanically; rename the id by hand")
        start, end = spans[i]
        block = "".join(lines[start:end])
        block = _sub_once(r"(version:\s*['\"]?)" + re.escape(old) + r"(['\"]?\s*\})",
                          r"\g<1>" + new + r"\g<2>", block, f"row {'/'.join(k)} pin.version")
        block = _sub_once(r"(\bid:\s*\S*?-)" + re.escape(old) + r"(-\S*)",
                          r"\g<1>" + new + r"\g<2>", block, f"row {'/'.join(k)} signal.id")
        block = _sub_once(r"(\bat:\s*)['\"]?[0-9]{4}-[0-9]{2}-[0-9]{2}['\"]?",
                          r"\g<1>'" + at + "'", block, f"row {'/'.join(k)} signal.at")
        lines[start:end] = [block]
        changes.append(f"{'/'.join(k)}: {old} -> {new}, at {at}")

    out = "".join(lines)
    # Re-read what was written: the pins must now resolve, version and all, or the rewrite
    # itself is refused rather than left half-done.
    check = {key3(r["pin"]): str(r["pin"].get("version"))
             for r in (yaml.safe_load(out) or {}).get("signals") or []}
    if check != pins:
        raise Refused(f"after the rewrite the rows {check} still do not equal the pins {pins}")
    return out, changes


def today() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("mode", nargs="?", choices=["rederive", "selfcheck"], default="rederive")
    ap.add_argument("--check", action="store_true",
                    help="do not write; exit 1 if the table is not what party.yaml's pins derive")
    ap.add_argument("--at", default=None, help="signal.at for rewritten rows (default: today, UTC)")
    args = ap.parse_args(argv)
    if args.mode == "selfcheck":
        return selfcheck()
    try:
        new, changes = rederive(PARTY.read_text(), LOOKUP.read_text(), args.at or today())
    except Refused as e:
        print(f"REFUSED: {e}")
        return 2
    rel = LOOKUP.relative_to(REPO)
    if not changes:
        print(f"ok  {rel}: every pin on party.yaml resolves to its row at the pinned version")
        return 0
    if args.check:
        print(f"FAIL: {rel} is not what party.yaml's pins derive: " + "; ".join(changes))
        return 1
    LOOKUP.write_text(new)
    for c in changes:
        print(f"rewrote {rel}: {c}")
    return 0


# --- selfcheck: planted fixtures, each bites for the reason planted ------------------------

_PARTY = """party: t
inherits:
  - { party: platform, kind: implementations, version: "2.0.1", since: '2026-08-28' }
  - { party: feeds,    kind: feed, name: threat-register,   version: "v2", since: '2026-08-28' }
"""

_LOOKUP = """# header comment survives
schema: twin.signal-lookup/v1
version: 2

signals:
  - pin: { party: platform, kind: implementations, version: '2.0.1' }
    signal:
      id: platform-implementations-2.0.1-is-the-pinned-release
      at: '2026-08-31'
      scenario: eol-date-passes-2026
      what: >-
        two lines of prose,
        kept verbatim.

  - pin: { party: feeds, kind: feed, name: threat-register, version: v1 }
    signal:
      id: feeds-threat-register-v1-names-t
      at: '2026-08-28'
      scenario: rival-reads-my-holes-2026
      what: >-
        untouched by a bump.

# a trailing comment
unbound_scenarios:
  - scenario: key-person-2026
    why: >-
      internal.
"""


def selfcheck() -> int:
    fails = []

    def expect(label, cond):
        print(("ok  " if cond else "FAIL ") + label)
        if not cond:
            fails.append(label)

    def refused(label, party, lookup, why):
        try:
            rederive(party, lookup, "2026-09-03")
            expect(f"{label} -> was NOT refused", False)
        except Refused as e:
            expect(f"{label} -> refused: {str(e)[:70]}", why in str(e))

    # 1. the planted stale row is rewritten, and only the three fields move
    out, changes = rederive(_PARTY, _LOOKUP, "2026-09-03")
    expect("stale v1 row rewritten to v2", changes == ["feeds/feed/threat-register: v1 -> v2, at 2026-09-03"])
    expect("pin.version, id token and at moved",
           "version: v2 }" in out and "feeds-threat-register-v2-names-t" in out and "at: '2026-09-03'" in out)
    expect("scenario, what, comments and the unbound block are verbatim",
           all(s in out for s in ("# header comment survives", "untouched by a bump.", "# a trailing comment",
                                  "rival-reads-my-holes-2026", "two lines of prose,\n        kept verbatim.")))
    expect("the fresh row is untouched", "at: '2026-08-31'" in out and "platform-implementations-2.0.1-" in out)
    expect("the rewrite is one line short of nothing: only the stale row's block differs",
           sum(a != b for a, b in zip(out.splitlines(), _LOOKUP.splitlines())) == 3
           and len(out.splitlines()) == len(_LOOKUP.splitlines()))
    # 2. idempotent: re-deriving the rewritten table changes nothing
    again, changes2 = rederive(_PARTY, out, "2099-01-01")
    expect("re-deriving a derived table is a no-op", again == out and changes2 == [])
    # 3. the refusals bite, each for its own reason
    refused("planted pin with no row",
            _PARTY + "  - { party: ico, kind: feed, name: penalty-schema, version: \"v3\" }\n",
            _LOOKUP, "no row for ico/feed/penalty-schema")
    refused("planted orphan row (pin dropped from party.yaml)",
            _PARTY.replace("  - { party: feeds,    kind: feed, name: threat-register,   version: \"v2\", since: '2026-08-28' }\n", ""),
            _LOOKUP, "which party.yaml no longer pins")
    refused("planted doubled row", _PARTY,
            _LOOKUP.replace("unbound_scenarios:", _LOOKUP[_LOOKUP.index("  - pin: { party: feeds"):_LOOKUP.index("# a trailing")] + "unbound_scenarios:"),
            "two rows for feeds/feed/threat-register")
    refused("planted id without a version token", _PARTY,
            _LOOKUP.replace("feeds-threat-register-v1-names-t", "feeds-threat-register-names-t"),
            "carries no -v1- token")
    print("TOTAL: %d planted case(s) failed" % len(fails))
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
