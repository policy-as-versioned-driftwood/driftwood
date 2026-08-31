#!/usr/bin/env bash
# Beat: "driftwood's twin emits one forward-intel feed from driftwood's own overlay, and it says
# whose money, in which currency, under which policy version -- and never what to do."
#
# Offline. Ticket 25, ADR-0019/0020/0021; overlay floor from ticket 11 answer item 2.
# Three outcomes only:
#   PASS (exit 0)  every assertion observed true
#   FAIL (exit 1)  an assertion observed false
#   SKIP (exit 3)  could not look, with the reason on the last line
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# The same contract as scripts/lib.sh: absence is never a pass.
skip() { echo "SKIP: $*"; exit 3; }

# The `twin` package renders the overlay and is not vendored: it does not self-version yet, so
# there is no tag for this repo to pin (ticket 11 answer item 1). Find the checkout that has it.
HUB=""
d="$HERE"
while [ "$d" != "/" ]; do
  [ -f "$d/twin/repo.py" ] && [ -f "$d/clone-estate.sh" ] && { HUB="$d"; break; }
  d="$(dirname "$d")"
done
[ -n "$HUB" ] || skip "no checkout of the twin package above $HERE; the overlay cannot be rendered"

PY="$HUB/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY=python3
  "$PY" -c 'import jsonschema, yaml' 2>/dev/null \
    || skip "no $HUB/.venv and python3 lacks jsonschema/pyyaml"
fi

command -v git >/dev/null 2>&1 || skip "git is needed to stage the overlay's deterministic mirror"

log="$(mktemp)"
HUB="$HUB" HERE="$HERE" "$PY" - >"$log" 2>&1 <<'PY'
import json, os, re, subprocess, sys

HUB, HERE = os.environ["HUB"], os.environ["HERE"]
sys.path.insert(0, HUB)
import yaml
from jsonschema import Draft7Validator

LINES = []
def out(status, msg):
    LINES.append(status)
    print("%s: %s" % (status, msg))

EMIT = os.path.join(HERE, "twin", "emit-forward-intel.py")
FEED = os.path.join(HERE, "twin", "forward-intel", "v1", "feed.json")
VENDORED = os.path.join(HERE, "twin", "forward-intel", "payload.schema.json")
CANONICAL = os.path.join(HERE, "..", "platform", "feeds", "forward-intel.payload.schema.json")

# 1. the overlay loads, and re-emitting it is byte-identical
r = subprocess.run([sys.executable, EMIT, "--check"], capture_output=True, text=True)
if r.returncode == 0:
    out("PASS", "the overlay loads and re-renders twin/forward-intel/v1/feed.json byte-identically")
else:
    out("FAIL", "emit-forward-intel.py --check: " + (r.stdout + r.stderr).strip().replace("\n", " | "))
    print("TOTAL: could not read the feed; nothing further was observed")
    sys.exit(1)

feed = json.load(open(FEED))
payload = feed["payload"]

# 2. the payload validates against the schema the envelope names
schema = json.load(open(VENDORED))
errs = [e.message for e in Draft7Validator(schema).iter_errors(payload)]
out("FAIL" if errs else "PASS",
    "payload vs %s%s" % (feed["payload_schema"], "; ".join([""] + errs) if errs else ""))

# 3. the vendored schema is the platform's canonical one, byte for byte
if os.path.isfile(CANONICAL):
    same = open(CANONICAL, "rb").read() == open(VENDORED, "rb").read()
    out("PASS" if same else "FAIL",
        "vendored payload schema %s platform/feeds/forward-intel.payload.schema.json"
        % ("is byte-identical to" if same else "DIFFERS from"))
else:
    out("SKIP", "platform/feeds/forward-intel.payload.schema.json is not in this estate yet, so "
                "the vendored copy could not be compared to its canonical home")

# 4. whose money, in which currency -- checked against the signed party artefact, not the payload
party = yaml.safe_load(open(os.path.join(HERE, "party.yaml")))
reporting = str(party.get("reporting_currency", "USD"))
declared = yaml.safe_load(open(os.path.join(HERE, "twin", "currency.yaml")))["perspectives"]
pid = str(payload["perspective"])
persp = yaml.safe_load(open(os.path.join(HERE, "twin", "orgs", "driftwood", "perspectives", pid + ".yaml")))

out("PASS" if persp.get("party") == "employer" else "FAIL",
    "perspective %r is party=%r (the overlay floor needs one employer seat)" % (pid, persp.get("party")))
ok = declared.get(pid) == reporting == payload["currency"]
out("PASS" if ok else "FAIL",
    "perspective currency %r, payload currency %r, party.yaml reporting_currency %r"
    % (declared.get(pid), payload["currency"], reporting))
out("PASS" if payload["perspective"] == party["party"] else "FAIL",
    "payload perspective %r names the party whose balance sheet this is (%r)"
    % (payload["perspective"], party["party"]))

# 5. the overlay floor: a caged workload, a pinned policy line, regulated data, roles, and one
#    graded causal edge that reaches the declared cash flow
comp_dir = os.path.join(HERE, "twin", "orgs", "driftwood", "components")
comps = {yaml.safe_load(open(os.path.join(comp_dir, f)))["id"]: yaml.safe_load(open(os.path.join(comp_dir, f)))
         for f in sorted(os.listdir(comp_dir))}
floor = {"cart-checkout-service": "the caged workload", "cage-policy-line": "the pinned policy line",
         "cart-pii": "the regulated data", "checkout-revenue": "the declared cash flow"}
missing = [f"{c} ({w})" for c, w in sorted(floor.items())
           if c not in comps or "evolution" not in comps[c] or "visibility" not in comps[c]]
out("FAIL" if missing else "PASS",
    "overlay floor: 4 positioned components" + ("; missing or unpositioned: " + ", ".join(missing) if missing else ""))

people = sorted(os.listdir(os.path.join(HERE, "twin", "orgs", "driftwood", "people")))
out("PASS" if people else "FAIL", "overlay floor: %d role(s) declared as people" % len(people))

edge_dir = os.path.join(HERE, "twin", "orgs", "driftwood", "edges")
edges = [yaml.safe_load(open(os.path.join(edge_dir, f))) for f in sorted(os.listdir(edge_dir))]
from twin import evidence  # the published ladder, not a number copied into this script
admits = evidence.admission_threshold()
graded = [e for e in edges if e.get("type") == "influences"
          and e["to"] == persp["cash_flow"][0]
          and int(e["evidence_grade"]) <= admits]
out("PASS" if len(graded) == 1 else "FAIL",
    "overlay floor: %d graded causal edge(s) reaching the declared cash flow %r at or inside the "
    "admission threshold (%d)" % (len(graded), persp["cash_flow"][0], admits))

# 6. the twin never picks: no action-shaped key anywhere in the payload, at any depth.
#    `tier` is deliberately NOT here -- a register entry is required to carry one (it takes the
#    tier the priced hits selected), and that is a stamped consequence, not a choice.
ACTION = re.compile(r"recommend|advice|advis|action|verdict|remediat|next.?step|should", re.I)
def keys(node, path="payload"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield path + "." + str(k), str(k)
            yield from keys(v, path + "." + str(k))
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from keys(v, "%s[%d]" % (path, i))
offenders = sorted(p for p, k in keys(payload) if ACTION.search(k))
out("FAIL" if offenders else "PASS",
    "no action-shaped key anywhere in the payload" + ("; found " + ", ".join(offenders) if offenders else ""))
raw = open(FEED, "rb").read().decode("utf-8")
hit = re.search(r'"[^"]*recommend[^"]*"\s*:', raw, re.I)
out("FAIL" if hit else "PASS",
    "no recommended-action field in the emitted bytes" + ("; found %s" % hit.group(0) if hit else ""))
# A null frequency means a subscribed pricing feed supplies it, so one has to be pinned.
lef = payload["lef"]
feeds = [d for d in payload["derived_from"] if d.get("kind") == "feed" and d["party"] != party["party"]]
out("PASS" if (lef is not None or feeds) else "FAIL",
    "the twin carries no frequency it does not have: lef=%r, and derived_from pins %d subscribed "
    "feed(s) to supply it" % (lef, len(feeds)))

# 6b. the register prices nothing, and the claim scope is stated rather than left unbounded
bad = [e for e in payload["register"] if "amount" in e or "net_cost_of_risk" in e]
out("FAIL" if bad else "PASS",
    "register carries %d entry/entries and no amount on any of them" % len(payload["register"]))
scope = payload["claim_scope"]
out("PASS" if isinstance(scope.get("included"), list) and isinstance(scope.get("excluded"), list) else "FAIL",
    "claim_scope states what is covered (%s) and what is carved out (%s)"
    % (scope.get("included"), scope.get("excluded")))

# 6c. the curve's accounts are exactly the rungs this repo's own selection policy can select
import importlib.util  # by file location: the package directory never joins sys.path
_spec = importlib.util.spec_from_file_location("sp", os.path.join(HERE, "selection-policy", "selection_policy.py"))
_sp = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sp)
accounts = tuple(e["account"] for e in payload["curve"])
out("PASS" if accounts == _sp.LADDER else "FAIL",
    "curve accounts %s are the selection policy's ladder %s" % (list(accounts), list(_sp.LADDER)))

# 7. the selection policy is versioned, pinned and its own self-check passes
sp = os.path.join(HERE, "selection-policy")
version = open(os.path.join(sp, "VERSION")).read().strip()
pin = yaml.safe_load(open(os.path.join(sp, "PIN.yaml")))["policy_version"]
module = re.search(r'^VERSION = "([^"]+)"', open(os.path.join(sp, "selection_policy.py")).read(), re.M).group(1)
agree = version == str(pin) == module
out("PASS" if agree else "FAIL",
    "selection-policy version: VERSION=%s PIN.yaml=%s selection_policy.py=%s" % (version, pin, module))
r = subprocess.run([sys.executable, os.path.join(sp, "selection_policy.py")], capture_output=True, text=True)
out("PASS" if r.returncode == 0 else "FAIL",
    "selection-policy self-check: " + (r.stdout + r.stderr).strip().replace("\n", " | "))

# 8. the feed is discoverable: publishes[] says where it is, and it is there
entry = next((e for e in party.get("publishes") or []
              if e.get("kind") == "feed" and e.get("name") == "forward-intel"), None)
if entry is None:
    out("FAIL", "party.yaml declares no publishes[] record for feed/forward-intel")
else:
    problems = []
    if "publisher" not in (party.get("roles") or []):
        problems.append("roles do not include publisher")
    if os.path.relpath(FEED, HERE) != os.path.join(entry["path"], "v1", "feed.json"):
        problems.append("path %r does not hold the emitted feed" % entry["path"])
    if entry.get("payload_schema") != feed["payload_schema"]:
        problems.append("payload_schema %r != the envelope's %r" % (entry.get("payload_schema"), feed["payload_schema"]))
    for side in ("rule.yaml", "bump.yaml"):
        if not os.path.isfile(os.path.join(HERE, entry["path"], side)):
            problems.append("%s/%s missing" % (entry["path"], side))
    out("FAIL" if problems else "PASS",
        "publishes[] feed/forward-intel at %s%s" % (entry["path"], "; " + "; ".join(problems) if problems else ""))

# 9. the refusals actually bite. Planted in a throwaway copy, never against the real files. It is
#    planted under the hub rather than in /tmp because the emitter finds the twin package by
#    walking up, and a plant that refused for the wrong reason would prove nothing. The copy sits
#    directly under the hub, not under .estate-clone/, so no estate-wide glob ever sees it.
import shutil, tempfile
plant_root = tempfile.mkdtemp(prefix=".plant-", dir=HUB)
try:
    def planted(label, mutate, expect):
        """One violation, in isolation, in a fresh copy -- and it must be refused for the reason
        planted, not for a leftover from the previous plant."""
        plant = os.path.join(plant_root, "driftwood")
        shutil.rmtree(plant, ignore_errors=True)
        os.makedirs(plant)
        for item in ("twin", "selection-policy", "party.yaml"):
            src, dst = os.path.join(HERE, item), os.path.join(plant, item)
            (shutil.copytree if os.path.isdir(src) else shutil.copy2)(src, dst)
        mutate(plant)
        p = subprocess.run([sys.executable, os.path.join(plant, "twin", "emit-forward-intel.py")],
                           capture_output=True, text=True)
        said = (p.stdout + p.stderr).strip().splitlines()
        why = said[-1] if said else ""
        ok = p.returncode != 0 and why.startswith("REFUSED") and expect in why
        out("PASS" if ok else "FAIL",
            "planted %s -> %s" % (label, why[:120] or "was NOT refused"))

    planted("a perspective valuing in a currency the party does not report in",
            lambda p: open(os.path.join(p, "twin", "currency.yaml"), "a").write(
                "\n# planted\nperspectives: {driftwood: USD}\n"),
            "values in USD and party.yaml reports in GBP")

    planted("a world_ref that no longer describes the vendored bytes",
            lambda p: open(os.path.join(p, "twin", "world", "meta.yaml"), "a").write(
                "description: planted, so the vendored bytes no longer stage to this pin\n"),
            "does not describe the bytes beside it")

    planted("a ladder rung the overlay prices no response for",
            lambda p: os.remove(os.path.join(p, "twin", "orgs", "driftwood", "responses",
                                             "run-the-checkout-at-quarantine.yaml")),
            "the ladder has a 'quarantine' rung")

    planted("a selection-policy version PIN.yaml does not pin",
            lambda p: open(os.path.join(p, "selection-policy", "PIN.yaml"), "a").write(
                "\npolicy_version: 9.9.9\n"),
            "PIN.yaml pins 9.9.9")
finally:
    shutil.rmtree(plant_root, ignore_errors=True)

code = 1 if "FAIL" in LINES else 3 if "SKIP" in LINES else 0
print("TOTAL: %d pass, %d fail, %d could-not-look"
      % (LINES.count("PASS"), LINES.count("FAIL"), LINES.count("SKIP")))
sys.exit(code)
PY
rc=$?
cat "$log"
case $rc in
  0) echo "PASS: driftwood's twin emits one forward-intel feed from its own overlay, labelled and unpicked";;
  3) echo "SKIP: $(grep '^SKIP:' "$log" | head -1 | cut -c7-)";;
  *) echo "FAIL: $(grep -c '^FAIL:' "$log") twin-overlay check(s) observed false";;
esac
rm -f "$log"
exit "$rc"
