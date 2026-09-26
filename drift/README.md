# Flux drift measurement — two instruments, one cluster

Build tickets 64 and 78 of `.scratch/twin/`, from spec story 85. **Run the test rather than assume
the answer.**

The spec claims policy-as-code needs *continuous* proof-of-force. Drift between deploys is the
candidate justification: a control silently removed after deployment is exactly the case a
point-in-time attestation misses and reconciliation catches. That must be demonstrated. If
controls do not drift, a deploy-time attestation suffices, Flux is a convenience rather than an
enabler, and the spec is amended.

This directory is the **instrument** — both of them. Neither reaches a conclusion. Build ticket
64's window waits on organic behaviour and answers a *base-rate* question: does a control drift
without anyone intending it? Build ticket 78's campaign forces four named actions and answers a
*mechanism* question instead: when a plausible change happens, do Flux and the probe catch it, and
how fast? The two never merge — build ticket 78's own pre-registration states in the file itself
that its events are not evidence for build ticket 64's tally — and build ticket 65 reads only the
first.

Build ticket 64's window is started near the front of the build on purpose: it needs elapsed
calendar time and nothing from the twin, so starting it at its natural dependency position would
delay the answer by a whole measurement window on top of everything else. Build ticket 78's
campaign carries no such wait — it runs once, in hours, because forcing the action is exactly what
lets it skip the wait.

## The files

| file | what it is |
|---|---|
| [`window.yaml`](window.yaml) | Build ticket 64's **pre-registration**. The question, both window bounds, the cadence, the subjects, what counts as a drift event, and what outcome would falsify the spec. |
| [`preconditions.yaml`](preconditions.yaml) | Open preconditions with named owners. Today: the org-level "Actions may create pull requests" toggle is off, which blocks build ticket 66. |
| [`probe.sh`](probe.sh) | One sample of control state, appended to `samples.jsonl`. A fact, never a verdict. Called by both instruments — build ticket 78's campaign never forks or edits it. |
| `samples.jsonl` | Build ticket 64's organic log. Untracked — machine-local measurement output, and committing it would put a growing binary-shaped blob in a repository whose other artefacts are all reproducible. |
| [`forced-campaign.yaml`](forced-campaign.yaml) | Build ticket 78's **pre-registration**. The four named trials, each with its action and its pre-recorded undo, the sampling resolution, and the guardrails that keep it walled off from ticket 64's log. |
| [`forced-campaign.sh`](forced-campaign.sh) | Runs the four trials in sequence: verify baseline, act, sample every 15s for 30 minutes, undo, verify baseline again. |
| `forced-campaign-samples.jsonl` | Build ticket 78's log. Untracked, same reason as `samples.jsonl` — and deliberately a *different file*, so the two can never be conflated on disk. |

The reduction lives in [`twin/drift.py`](../../../twin/drift.py) — `Window` for build ticket 64,
`ForcedCampaign` for build ticket 78 — because build ticket 65 builds its verdict on top of the
first and the twin's test suite is where a wrong number gets caught.

## Run it

```sh
estate/driftwood/scripts/up.sh          # the cluster this measures
estate/driftwood/drift/probe.sh         # one sample
./bin/twin drift                        # the measurement so far: coverage, events, no verdict
```

On a cadence, on the machine holding the cluster:

```
0 * * * * cd <repo> && estate/driftwood/drift/probe.sh >> estate/driftwood/drift/probe.log 2>&1
```

Not a hosted CI runner. The cluster is local KinD and a hosted runner cannot reach it, so a
scheduled workflow would record an unreachable cluster every hour and prove nothing.

## Two properties worth stating

**The window was declared before the data arrived, and that is checked rather than claimed.** The
harness guard `drift_window_was_declared_before_it_was_measured` reads `window.yaml`'s git history
and fails if any sample predates its first commit. Retuning the window once the results looked
inconvenient fails the suite. `twin/drift.py` also refuses a window that names no falsifying
outcome and one that names no operator.

**A probe that cannot reach the cluster still writes a sample.** An instrument whose silence
reads as stability is worse than no instrument, so an outage appears as a coverage hole rather
than as a quiet stretch of no drift. `twin drift` reports what fraction of the declared window was
actually observed, and every gap wider than the declared cadence — including the one a stopped
cron leaves at the end. "No drift in 91 days" and "no drift in the hours we were looking" are
different claims, and only one of them is falsifiable.

## The known ceiling

The interval between deploy and divergence is an **upper bound**. The probe samples hourly, so a
divergence began somewhere in the hour before the sample that caught it. A watch on the Kubernetes
API would give the moment rather than the bound; it also needs a process that stays up, which is a
different reliability claim from a cron job that writes a gap when it fails. The bound is enough
to answer the question the window asks — *does it drift between deploys at all* — and the artefact
says so rather than presenting the figure as the moment.

## A third instrument, added 2026-08-28: the five-fact sample

Ecosystem ticket 40, from ticket 16 answer items Q1, Q2, Q3 and Q5, under ADR-0023 (D1, D3). It
answers a different question from either of the two above. Build ticket 64 asks *does a control
drift between deploys*; build ticket 78 asks *when a change happens, is it caught*. This one asks:
**is driftwood's composed policy set in force at all, and did every byte of it arrive through a
source whose signed tag was verified at the boundary?**

| file | what it is |
|---|---|
| [`window.yaml`](window.yaml), section `five_fact_sample` | The **pre-registration**: the five facts, the three falsifiers, the coverage floor, the cadence and the runner. Committed before the first sample, and `verify-reconcile.sh` refuses to grade any sample PASS unless all three falsifier ids are still declared there — ticket 40's own rule that a sample passing with a falsifier undeclared is a fail. |
| [`five-facts.py`](five-facts.py) | `sample` takes one record **per source**; `grade` reads the latest and returns the verify contract (0 / 3 / 1). |
| [`../scripts/render_composed.py`](../scripts/render_composed.py) | The **offline render** of `composed/`, read-only over that tree, so fact 4 compares the cluster to git rather than to itself. |
| [`../.github/workflows/drift-sample.yml`](../.github/workflows/drift-sample.yml) | The clock: a scheduled ephemeral KinD in Actions, reconciling from the **real remotes**, appending the sample. |
| [`../verify-reconcile.sh`](../verify-reconcile.sh) | Section 6 grades the latest sample under the hub's `talk/verify-all.sh`. |

**It shares `samples.jsonl` and it does not share its data.** ADR-0023's observation lane names
that one path and no other, so a clock may write nothing else. Every five-fact record carries
`"kind": "flux.five-facts/v1"`, which no probe sample carries, and a record taken on any cluster
other than `kind-driftwood` carries `"reachable": false` with a reason saying so — because build
ticket 64's three subjects were not sampled by that run at all. A CI run on an ephemeral cluster
therefore leaves a coverage hole in build ticket 64's window rather than inflating it, which is the
same rule the probe follows when it cannot reach the cluster.

**Why it does not run against `kind-driftwood`.** `scripts/up.sh` seeds a throwaway repo into an
in-cluster git server and repoints Flux at it, so on that cluster fact 1 — Ready at the pinned
`{tag, commit}` from the publisher's **real remote** — is observed false by construction. A sample
there proves nothing about an org boundary, and a hand-run sample is a rehearsal that is never
appended or cited (ADR-0023, D4).

## Facts 6 and 7, added 2026-09-10 and registered again 2026-09-26: the cage, on the same sample

Ecosystem ticket 86, from ticket 75 Q8 (the owner's answer, delegated: the lane branch), registered
again by ecosystem ticket 152 (delegated, 2026-09-25) and built by ticket 161. Pre-registered in
[`window.yaml`](window.yaml) under `cage_behaviour_sample`, and taken by the same scheduled run, on
the same cluster, in the same record as the five.

The estate's most distinctive claim is that **nothing is denied**: a workload that does not fit its
cage runs on a tighter rung, and the bottom rung runs and reaches nothing. That claim had never been
graded PASS on a citable run. The instrument that observes it — platform's `graded/verify-graded.sh`
live tail — needs a persistent KinD cluster the scheduled truth runner has never created, so it has
exited 3 on every run since run 15; the runs that *do* observe the cage are presenter runs on a
laptop, and NORTH-STAR §5 forbids citing those. This lane already brings up a real cluster per run.
So the claim is graded here.

| Fact | What it observes |
|---|---|
| 6 | The workload the cage places on its **own bottom rung** is admitted by the API server and reaches Running. A refusal is quoted verbatim; a pod admitted and never started is observed false, because a cage that does not run the workload is a refusal with extra steps. |
| 7 | That workload completes **neither** a TCP connection to the API server **nor** one outside the cluster, and its rung is the ladder's bottom by its priority and by a reach policy with no rules, while a **reference workload** that the cage does not select completes both. A connection, never a read of the NetworkPolicy's own YAML. |

**The rung is the cage's answer, not the instrument's.** Two namespaces are created, and neither
names a tier. One is `governed` with no tier, so the cage's own fall-closed rule decides where its
pod lands. The instrument then checks that the landing place is the ladder's **bottom**, from what
the cluster serves and not from a name typed here: the pod's priority is the lowest of the `cage-`
PriorityClasses on the cluster, and the NetworkPolicy that selects it has no ingress rule, no
egress rule, and declares both policy types. If either check fails, facts 6 and 7 both read
could-not-look, because each names the bottom rung and a TRUE would name a rung the cage did not
use. Nothing here types the word `isolated`.

**The reference workload is outside the cage.** The other Namespace carries no governed label and
no tier, and its pod claims no policy version, so the cage does not select it (ecosystem 119,
decision 2). It runs the same image and the same two connects, and it is read **before and after**
the bottom-rung pod, so a working network brackets the silence. Until 2026-09-26 the comparison pod
was a "control" that claimed a version in an ungoverned Namespace; under 5.0.0 the cage put it on
`isolated` beside the fall-closed pod, and fact 7 read null on every sample (ticket 152). A pod on a
looser rung that the sampler declared at run time was considered and refused: it would buy a cage
no signed declaration chose, which ADR-0022 calls an exemption. In this estate a **control** is a
catalogue control, so the word is not used for this pod.

**The reference is what stops a false green.** A pod that reaches nothing because the cluster is
broken must not read the same as a pod that reaches nothing because the cage holds. So a run where
the reference reaches nothing either is recorded UNMEASURED — a declared falsifier, never a pass.
Same for a cage that selects the reference: a tier or caged label on it, or a NetworkPolicy that
selects it, and the reference is not a reference.

**A null that never clears is a fall.** A cage fact that is null on each of the three newest samples
taken since the registration fires `the_cage_facts_stay_unmeasured`, and `grade` reports FAIL naming
the fact and its reason. A null that clears on the next sample stays a could-not-look. Samples from
before the registration do not count, so the rule can first fire on the third sample after it.
`grade`'s SKIP line names every null fact and its reason.

**The sidecar is a stand-in and the fact says so.** The cage injects `ghcr.io/acme/coraza-waf:cage`
at every hardened rung and that image exists in no registry. The workflow builds platform's own
`graded/waf-placeholder` — out of the tree already checked out at the tag this repo pins — under
that name and loads it into the node. A sleeping busybox is not a WAF: fact 6 proves the caged
workload *runs* with what the cage added, not that anything inspected traffic.

**Pre-registration is measured, not asserted.** `grade` walks first-parent history on the served
ref and reads the newest commit that changed the entire `cage_behaviour_sample` section in
`window.yaml`, including its question, facts, falsifiers, ceilings and comments. A sample taken
before that change reads could-not-look on facts 6 and 7, on a line that names the commit: a
question not yet asked is never a pass, and a sample from before a re-registration never prints
PASS on five facts (ticket 152 Q4). A branch commit registers nothing. Rewriting the section
re-registers it, and scores against the previous wording stop counting (ticket 93); changes outside
the section do not re-register these facts.

**The served documents are proven offline too.** [`../verify-cage-probe.sh`](../verify-cage-probe.sh)
runs `five-facts.py selfcheck`, checks the kyverno CLI against the engine this repository declares
(`gitops/engine/kyverno.yaml`, or `KYVERNO_VERSION` in `drift-sample.yml` until that file exists),
proves the CLI reads Namespace labels, and runs the sampler's own probe objects against the served
composed set at the pinned tag and at HEAD: the fall-closed pod must land on the bottom (lowest
`cage-` PriorityClass, a selecting NetworkPolicy with no rules and both types), nothing may select
the reference pod, and every PriorityClass a mutation names must be served. Its PASS is about the
documents; the lane's facts are about the cluster, and the two do not conflict. It runs on every
pull request (`shift-left.yml`) and in the hub's gate.
