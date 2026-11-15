# driftwood

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.*

Driftwood is the adopter: the organisation that is caged. A loop prices its exposure in pounds a year, adds the running cost of the cage, compares the sum with the tolerance, and moves the cage one notch at a time. The loop's code is in [platform](https://github.com/policy-as-versioned-platform/platform). The numbers come from [ico](https://github.com/policy-as-versioned-ico/ico) and [feeds](https://github.com/policy-as-versioned-feeds/feeds). `LOOP.md` in the [hub](https://github.com/policy-as-versioned-flux/policy-as-versioned-flux) says what the loop is, and `CONTEXT.md` there defines the terms.

The loop follows ico and feeds by itself. The platform pin moves only by a pull request, whose own cycle runs the new platform on a cluster before it lands.

## Where things are

| Path | What it holds |
|---|---|
| `party.json` | Turnover, tolerance, margin, dwell and mode. The three pins are signed tags of platform, ico and feeds, each with its commit. |
| `gitops/apps/namespace.yaml` | The governed Namespace and the one rung line. A notch changes that line and nothing else. |
| `gitops/apps/` | The three workloads, as bare Pods. `pod.yaml` is the probe pod. |
| `.github/workflows/loop.yml` | The cycle. It runs once a day, on dispatch, on each pull request but the loop's own (those start no jobs, because the workflow's own token opened them), and after each push to `main` that changes `party.json` or `gitops/apps/`. |
| `.github/pins.sh` | Checks out the three pins and verifies them. |
| `renovate.json` | Tells the hosted Renovate app what to watch here: the images in `gitops/apps/` and the gitsign download. The pins in `party.json` are the loop's, not Renovate's. |

## How to read the ledger

The ledger is `loop.jsonl` on the branch `ledger`. It is not on `main`. Each cycle on `main` appends one JSON line. A pull request's cycle, and a run that refuses an input or cannot check out its pins, append none. Skip a line with no `verdict`.

```sh
git fetch origin refs/heads/ledger:refs/remotes/origin/ledger
git show refs/remotes/origin/ledger:loop.jsonl | tail -n 1 | python3 -m json.tool
```

- `figure` is the compared number: `exposure` plus `cost`, the running cost of the current rung in pounds a year. It is compared with `tolerance`.
- `verdict` is the judgement. `within` and `within-partial` hold. `tighten` and `release` move one notch, to `rung_to`. `saturated` and `cage-ineffective` are red. `could-not-look` means the loop could not measure, so it moves nothing.
- `rung` is the rung line in git. `rung_set_by` is the author of the last change to it.
- `looked` says whether the cluster was measured. When it is false, `capabilities` and `serving` are `null` and `why` says what failed. If no probe ran (the cluster could not be built), `why` reads `no probe result` and the run's log says what failed. A `cage-ineffective` line has `looked` true, and `why` names the capability measured open. On both kinds of line every row counts as open: `exposure` is the sum of all priced rows and `figure` is that sum plus `cost`. Neither is a measurement of what the cage closes.
- `rows` lists each way a loss happens: its amount, whether it is open, `bound` (`upper` when the amount is an upper bound because a penalty rate is missing or a tier is not cited, else `estimate`) and `needs` (the capabilities, any one of which closes it). `unpriced` names the rows with a missing number.
- `sourced_share` is the share of the figure that rests on sourced numbers. `weakest_basis` names the weakest basis in it. `tolerance_basis` and `cost_basis` say where those two numbers come from.
- `pins`, `commit`, `run` and `cause` say which commits the cycle used and what started it.
- `ts` is the UTC time of the cycle. `party` is whose line it is. `mode` is the party file's mode, `measure` or `act`. `cluster` says what was measured: `throwaway`, the kind cluster each run builds.
- `capabilities` is what the probe measured, `egress` and `inbound`, each `open` or `closed`. `serving` is how many governed pods that declare a port took a connection from the reference, as `ok` of `total`. `pods` lists the governed pods, each with whether it is Ready and the rung it carries. `reference` says whether the reference could connect before and after the tests.
- `goal` is the loosest rung whose predicted figure is within `tolerance`, or the rung with the lowest prediction if none is. `unreachable` is how many pounds a year the lowest prediction on the ladder is over `tolerance`, or 0. `release_ready` is true when `goal`, worked out against `tolerance` × (1 − `margin`), is looser than `rung`. A release needs every row priced and `release_ready` on each line, without a break, for `dwell_days`; the loop reads `ts` and `release_ready` of the earlier lines to count that run, and it skips `could-not-look` lines.

The `verdict` job of a run is red when the verdict is `saturated`, `cage-ineffective` or `could-not-look`. On `main` the line is written all the same.
