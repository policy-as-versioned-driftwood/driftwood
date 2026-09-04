#!/usr/bin/env bash
# Beat: "the twin sweep's moved path is a branch that has run, not a branch that reads well."
#
# Ticket 72. The sweep step of twin-sweep.yml ran under GitHub's `bash -e` with a body that never
# lifted it, so the exit 1 meaning "the feed moved" aborted the step before rc=$? and the moved
# branch had never executed (run 33627910027, 2026-09-02). Two halves, graded separately:
#
#   1. offline, always: the sweep step's OWN `run:` shell -- read out of the workflow YAML, never
#      re-typed here -- executed under `bash -e` exactly as GitHub executes it, on a planted copy
#      of this repository, says moved=true for a stale feed, moved=true for a stale signal lookup,
#      and moved=false for a fresh copy. A step that passes only the fresh case proves nothing.
#   2. evidence: observations/twin-sweep.jsonl carries at least one line with "moved": true --
#      the moved path has FIRED, live, on the clock, and the observation says which run. Until it
#      has, this half is a could-not-look, not a pass: a branch that has never run is not proven.
#
# Three outcomes only:
#   PASS (exit 0)  every assertion observed true
#   FAIL (exit 1)  an assertion observed false
#   SKIP (exit 3)  could not look, with the reason on the last line
set -uo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$HERE")"

skip() { echo "SKIP: $*"; exit 3; }

# The emitter needs the hub's `twin` package above it (it walks up; ticket 29 owns the pin).
HUB=""
d="$HERE"
while [ "$d" != "/" ]; do
  [ -f "$d/twin/repo.py" ] && [ -f "$d/clone-estate.sh" ] && { HUB="$d"; break; }
  d="$(dirname "$d")"
done
[ -n "$HUB" ] || skip "no checkout of the twin package above $HERE; the sweep step cannot be exercised"

PY="$HUB/.venv/bin/python"
if [ ! -x "$PY" ]; then
  PY=python3
  "$PY" -c 'import yaml' 2>/dev/null || skip "no $HUB/.venv and python3 lacks pyyaml"
fi
command -v git >/dev/null 2>&1 || skip "git is needed to stage the overlay's deterministic mirror"

WORKFLOW="$REPO/.github/workflows/twin-sweep.yml"
[ -f "$WORKFLOW" ] || skip "no .github/workflows/twin-sweep.yml to read the sweep step from"

log="$(mktemp)"; trap 'rm -f "$log"' EXIT
HUB="$HUB" REPO="$REPO" PY="$PY" WORKFLOW="$WORKFLOW" "$PY" - >"$log" 2>&1 <<'PY'
import json, os, re, shutil, stat, subprocess, sys, tempfile
from pathlib import Path

HUB, REPO, PY, WORKFLOW = (Path(os.environ[k]) for k in ("HUB", "REPO", "PY", "WORKFLOW"))
sys.path.insert(0, str(HUB))
import yaml

LINES = []
def out(status, msg):
    LINES.append(status)
    print("%s: %s" % (status, msg))

# --- 1. the step, as GitHub runs it -------------------------------------------------------
doc = yaml.safe_load(WORKFLOW.read_text())
steps = ((doc.get("jobs") or {}).get("sweep") or {}).get("steps") or []
step = next((s for s in steps if s.get("id") == "sweep"), None)
if step is None or not step.get("run"):
    out("FAIL", "twin-sweep.yml job `sweep` has no step with id `sweep` carrying a run: shell")
    print("TOTAL: %d pass, %d fail, %d could-not-look" % (LINES.count("PASS"), LINES.count("FAIL"), LINES.count("SKIP")))
    sys.exit(1)
script = str(step["run"])

# Planted under the hub, not /tmp, because the emitter finds the twin package by walking up;
# directly under the hub rather than .estate-clone/ so no estate-wide glob sees it.
plant_root = Path(tempfile.mkdtemp(prefix=".plant-", dir=str(HUB)))
try:
    # `pip install --quiet pyyaml` is the one line of the step that reaches for a network; here
    # python3 is the interpreter this check already runs under, so pip is shimmed to a no-op.
    shim = plant_root / "shim"
    shim.mkdir()
    (shim / "pip").write_text("#!/bin/sh\nexit 0\n")
    (shim / "pip").chmod((shim / "pip").stat().st_mode | stat.S_IEXEC)
    os.symlink(str(PY), str(shim / "python3"))

    def run_step(label, mutate):
        """A fresh copy of the repository's overlay inputs, one mutation, the step's own shell
        under `bash -e` with GITHUB_OUTPUT captured. Returns (exit code, output-file lines)."""
        plant = plant_root / "driftwood"
        shutil.rmtree(plant, ignore_errors=True)
        plant.mkdir()
        for item in ("twin", "selection-policy", "party.yaml", ".github"):
            src, dst = REPO / item, plant / item
            (shutil.copytree if src.is_dir() else shutil.copy2)(src, dst)
        mutate(plant)
        gh_out = plant_root / (label.replace(" ", "-") + ".out")
        gh_out.write_text("")
        env = dict(os.environ, PATH=str(shim) + os.pathsep + os.environ.get("PATH", ""),
                   GITHUB_OUTPUT=str(gh_out))
        p = subprocess.run(["bash", "-e", "-c", script], cwd=str(plant), env=env,
                           capture_output=True, text=True)
        return p.returncode, gh_out.read_text().splitlines(), (p.stdout + p.stderr).strip()

    def stale_lookup(p):
        """The threat-register row one version behind the pin -- pin.version and the id token
        together, the way a real pre-bump row looks, so the deriver reads it as stale rather
        than refusing it as malformed."""
        f = p / "twin" / "signals.yaml"
        text = f.read_text()
        cur = re.search(r"name: threat-register, version: (v\d+) \}", text).group(1)
        f.write_text(text.replace("name: threat-register, version: %s }" % cur,
                                  "name: threat-register, version: v0 }")
                         .replace("feeds-threat-register-%s-" % cur, "feeds-threat-register-v0-"))

    cases = [
        ("a fresh copy", lambda p: None, "moved=false"),
        ("a stale feed", lambda p: (p / "twin" / "forward-intel" / "v1" / "feed.json").open("a").write("\n"),
         "moved=true"),
        ("a stale signal lookup", stale_lookup, "moved=true"),
    ]
    for label, mutate, want in cases:
        rc, outputs, said = run_step(label, mutate)
        ok = rc == 0 and want in outputs and any(o.startswith("swept_at=") for o in outputs)
        out("PASS" if ok else "FAIL",
            "the sweep step under `bash -e` on %s exits %d and writes %s"
            % (label, rc, ", ".join(outputs) or "nothing")
            + ("" if ok else " -- wanted exit 0 and %s; step said: %s" % (want, said[-200:].replace("\n", " | "))))
finally:
    shutil.rmtree(plant_root, ignore_errors=True)

# --- 2. the evidence: the moved path has fired, live -----------------------------------------
series = REPO / "observations" / "twin-sweep.jsonl"
fired = []
if series.is_file():
    for n, line in enumerate(series.read_text().splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            out("FAIL", "observations/twin-sweep.jsonl line %d is not JSON" % n)
            continue
        if rec.get("moved") is True:
            fired.append(rec)
if fired:
    first = fired[0]
    out("PASS", "the moved path has fired live %d time(s); first at %s, run %s, proposal %r"
        % (len(fired), first.get("swept_at"), first.get("run") or "?", first.get("proposal") or ""))
else:
    out("SKIP", "the moved path has not fired live yet: %s (the step is proven offline above; "
                "the live firing is the half only the clock can supply, once the overlay or a "
                "pin moves under it)"
        % ("observations/twin-sweep.jsonl carries no line with \"moved\": true" if series.is_file()
           else "no observations/twin-sweep.jsonl exists yet"))

code = 1 if "FAIL" in LINES else 3 if "SKIP" in LINES else 0
print("TOTAL: %d pass, %d fail, %d could-not-look"
      % (LINES.count("PASS"), LINES.count("FAIL"), LINES.count("SKIP")))
sys.exit(code)
PY
rc=$?
cat "$log"
case $rc in
  0) echo "PASS: the twin sweep's moved path runs under bash -e and has fired live at least once";;
  3) echo "SKIP: $(grep '^SKIP:' "$log" | head -1 | cut -c7-)";;
  *) echo "FAIL: $(grep -c '^FAIL:' "$log") twin-sweep moved-path check(s) observed false";;
esac
exit "$rc"
