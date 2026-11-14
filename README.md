# driftwood

*A demonstration party, not affiliated with, endorsed by or speaking for any real authority it names.*

Driftwood is the adopter: the organisation that is caged. A loop prices its exposure in pounds a year, adds the running cost of the cage, compares the sum with the tolerance, and moves the cage one notch at a time. The loop's code is in [platform](https://github.com/policy-as-versioned-platform/platform). The numbers come from [ico](https://github.com/policy-as-versioned-ico/ico) and [feeds](https://github.com/policy-as-versioned-feeds/feeds). `LOOP.md` in the [hub](https://github.com/policy-as-versioned-flux/policy-as-versioned-flux) says what the loop is, and `CONTEXT.md` there defines the terms.

## Where things are

| Path | What it holds |
|---|---|
| `party.json` | Turnover, tolerance, margin, dwell and mode. The three pins: the exact commits of platform, ico and feeds that the loop uses. |
| `gitops/apps/namespace.yaml` | The governed Namespace and the one rung line. A notch changes that line and nothing else. |
| `gitops/apps/` | The three workloads, as bare Pods. `pod.yaml` is the probe pod. |
| `.github/workflows/loop.yml` | The cycle. It runs once a day, and after each merge that changes `party.json` or `gitops/apps/`. |
| `.github/pins.sh` | Checks out the three pins and verifies them. |
| `renovate.json` | Keeps the hosted Renovate app silent. |

## How to read the ledger

The ledger is `loop.jsonl` on the branch `ledger`. It is not on `main`. Each cycle appends one JSON line. Skip a line with no `verdict`.

```sh
git fetch origin ledger
git show origin/ledger:loop.jsonl | tail -n 1 | python3 -m json.tool
```

- `figure` is the compared number: `exposure` plus `cost`, the running cost of the current rung in pounds a year. It is compared with `tolerance`.
- `verdict` is the judgement. `within` and `within-partial` hold. `tighten` and `release` move one notch, to `rung_to`. `saturated` and `cage-ineffective` are red. `could-not-look` means the loop could not measure, so it moves nothing.
- `rung` is the rung line in git. `rung_set_by` is the author of the last change to it.
- `looked` says whether the cluster was measured. When it is false, `why` says what failed, and the figure is the uncaged one, not a measurement.
- `rows` lists each way a loss happens, its amount and whether it is open. `unpriced` names the rows with a missing number.
- `sourced_share` is the share of the figure that rests on sourced numbers. `weakest_basis` names the weakest basis in it. `tolerance_basis` and `cost_basis` say where those two numbers come from.
- `pins`, `commit`, `run` and `cause` say which commits the cycle used and what started it.

The `verdict` job of a run is red when the verdict is `saturated`, `cage-ineffective` or `could-not-look`. The line is written all the same.
