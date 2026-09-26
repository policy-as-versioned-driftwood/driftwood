"""Eco-system ticket 143: the twin sweep is a read-only twin job and a writer with no twin code.

Run: python3 -m unittest discover -s .github/tests -p 'test_*.py'

This module sits under .github/ on purpose, like test_cut_release_layout.py: the composer's
comparison identity skips hidden paths, so a workflow-shape test can change without moving
driftwood's source identity.

What is graded here is the workflow file as GitHub reads it (parsed, never grepped, except for
the one thing YAML drops: the version comment beside each pinned `uses:`), and the writer's own
validation shell run as an adversary: every wrong handoff it must refuse, refused by name.
"""
import json
import os
import re
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / '.github/workflows/twin-sweep.yml'
PIN = ROOT / 'twin/PIN.yaml'
REQUIREMENTS = ROOT / '.github/requirements/twin-sweep.txt'
GITSIGN_ACTION = ROOT / '.github/actions/install-gitsign/action.yml'
HUB = 'policy-as-versioned-flux/policy-as-versioned-flux'
SHA = re.compile(r'^[0-9a-f]{40}$')
# A `uses:` pinned to a full commit, the version beside it: the sha is what runs, the comment is
# what a human reads.
PINNED_USES = re.compile(r'^\s*-?\s*uses:\s*(\S+?)@([0-9a-f]{40})\s+#\s*v\d+(?:\.\d+)*\s*$')
INERT = ('actions/checkout', 'actions/upload-artifact', 'actions/download-artifact')
# The same shape the hub's verify/schedules/schedules.py reads a `run:` with for programs it
# cannot read (python, bash, sh, npx, node, ./x). The writer stays inline shell by test, not by
# promise, and this regex is the one the checker would apply.
PROGRAM = re.compile(
    r"(?m)(?:^|(?<=[;&|]))\s*(?:(?:if|then|else|do|!|-)\s+)*(?:[A-Za-z_][\w]*=\S*\s+)*"
    r"(?:(?:python3?|bash|sh|npx|node)\s+[^\n|;&]*|\./[^\s|;&]+[^\n|;&]*)")
COMMENT = re.compile(r'(?m)^\s*#[^\n]*\n?')
CONTINUED = re.compile(r'\\\n\s*')
CAGE_SHELL = ('git reset', 'OBSERVATION_LANE', 'git add', 'git diff --cached --name-only', 'exit 1')


def _steps(job):
    return job['steps']


def _step(job, **needle):
    key, value = next(iter(needle.items()))
    found = [s for s in _steps(job) if value in str(s.get(key, ''))]
    assert len(found) == 1, (needle, [s.get('name') for s in found])
    return found[0]


def _index(job, **needle):
    return _steps(job).index(_step(job, **needle))


class TwinSweepSplit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = WORKFLOW.read_text()
        cls.doc = yaml.safe_load(cls.text)
        cls.jobs = cls.doc['jobs']
        cls.twin = cls.jobs['twin']
        cls.write = cls.jobs['write']
        cls.pin = yaml.safe_load(PIN.read_text())

    # --- the pin ------------------------------------------------------------------------------
    def test_pin_names_a_full_hub_commit_and_the_tag_is_not_cut(self):
        self.assertRegex(str(self.pin['hub_commit']), SHA)
        self.assertEqual(self.pin['tag_cut'], False)
        self.assertNotIn('ref: main', self.text, 'the hub is never checked out at a branch')

    def test_twin_job_checks_the_hub_out_at_the_pinned_commit_and_reads_only(self):
        self.assertEqual(sorted(self.jobs), ['twin', 'write'])
        self.assertEqual(self.doc['permissions'], {'contents': 'read'})
        self.assertEqual(self.twin['permissions'], {'contents': 'read'})
        checkouts = [s for s in _steps(self.twin) if str(s.get('uses', '')).startswith('actions/checkout@')]
        hub = [s for s in checkouts if s.get('with', {}).get('repository') == HUB]
        own = [s for s in checkouts if 'repository' not in s.get('with', {})]
        self.assertEqual((len(hub), len(own), len(checkouts)), (1, 1, 2))
        self.assertEqual(hub[0]['with']['ref'], '${{ steps.pin.outputs.hub_commit }}')
        self.assertEqual(hub[0]['with']['fetch-depth'], 1)
        self.assertEqual(hub[0]['with']['path'], 'hub')
        self.assertIs(hub[0]['with']['persist-credentials'], False)
        self.assertIs(own[0]['with']['persist-credentials'], False)
        self.assertEqual(own[0]['with']['path'], 'adopter')
        # driftwood is read before the hub, because the pin lives in driftwood
        self.assertLess(_steps(self.twin).index(own[0]), _steps(self.twin).index(hub[0]))
        self.assertLess(_index(self.twin, id='pin'), _steps(self.twin).index(hub[0]))
        # then moved under the hub, where the emitter walks up to the twin package
        self.assertEqual(self.twin['defaults']['run']['working-directory'], 'hub/.estate-clone/driftwood')
        mover = _step(self.twin, run='mv adopter hub/.estate-clone/driftwood')
        self.assertIn('rev-parse HEAD', mover['run'])
        self.assertIn('HUB_COMMIT', mover['run'])
        # and it pushes nothing, proposes nothing
        shell = '\n'.join(str(s.get('run', '')) for s in _steps(self.twin))
        self.assertNotIn('git push', shell)
        self.assertNotIn('gh pr', shell)
        upload = _step(self.twin, uses='actions/upload-artifact@')
        self.assertEqual(upload['with']['name'], 'twin-sweep-handoff')
        self.assertEqual(upload['with']['if-no-files-found'], 'error')

    def test_pin_step_reads_the_same_commit_yaml_reads_and_refuses_a_bad_pin(self):
        shell = _step(self.twin, id='pin')['run']

        def run(pin_text):
            with tempfile.TemporaryDirectory() as tmp:
                (Path(tmp) / 'twin').mkdir()
                (Path(tmp) / 'twin/PIN.yaml').write_text(pin_text)
                out = Path(tmp) / 'out'
                out.write_text('')
                done = subprocess.run(['bash', '-e', '-c', shell], cwd=tmp, capture_output=True, text=True,
                                      env=dict(os.environ, GITHUB_OUTPUT=str(out)))
                return done.returncode, out.read_text().strip(), done.stdout + done.stderr

        rc, output, _ = run(PIN.read_text())
        self.assertEqual(rc, 0)
        self.assertEqual(output, f"hub_commit={self.pin['hub_commit']}")
        for bad, why in ((PIN.read_text() + 'hub_commit: ' + 'b' * 40 + '\n', 'two hub_commit lines'),
                         (PIN.read_text().replace(self.pin['hub_commit'], 'abc123'), 'a short sha'),
                         (PIN.read_text().replace(self.pin['hub_commit'], 'main'), 'a branch name'),
                         ('twin_version: 0.1.0\n', 'no hub_commit at all')):
            rc, output, said = run(bad)
            self.assertNotEqual(rc, 0, why)
            self.assertEqual(output, '', why)
            self.assertIn('::error::', said, why)

    # --- the network dial -----------------------------------------------------------------------
    def test_every_download_is_pinned_by_hash(self):
        uses = [line for line in self.text.splitlines() if re.match(r'^\s*-?\s*uses:', line)]
        self.assertGreaterEqual(len(uses), 5)
        for line in uses:
            m = PINNED_USES.match(line)
            self.assertIsNotNone(m, f'not pinned to a full commit with its version beside it: {line.strip()}')
            self.assertIn(m.group(1), INERT, line)
        pip = [s for s in _steps(self.twin) if 'pip install' in str(s.get('run', ''))]
        self.assertEqual(len(pip), 1)
        self.assertIn('--require-hashes -r .github/requirements/twin-sweep.txt', pip[0]['run'])
        self.assertNotIn('pip install', '\n'.join(str(s.get('run', '')) for s in _steps(self.write)))
        lines = [l.strip() for l in REQUIREMENTS.read_text().splitlines() if l.strip() and not l.startswith('#')]
        self.assertRegex(lines[0], r'^pyyaml==\d+\.\d+\.\d+ \\$')
        hashes = [l for l in lines[1:]]
        self.assertGreaterEqual(len(hashes), 1)
        for h in hashes:
            self.assertRegex(h, r'^--hash=sha256:[0-9a-f]{64}( \\)?$', h)
        self.assertEqual(sum(1 for l in lines if not l.startswith('--hash=')), 1, 'one requirement, nothing else')
        # gitsign: the workflow's pin is the shared action's pin
        action = yaml.safe_load(GITSIGN_ACTION.read_text())['runs']['steps'][0]['env']
        self.assertEqual(str(self.doc['env']['GITSIGN_VERSION']), str(action['GITSIGN_VERSION']))
        self.assertEqual(self.doc['env']['GITSIGN_SHA256'], action['GITSIGN_SHA256'])
        install = _step(self.write, name='install pinned gitsign')
        self.assertIn('sha256sum -c -', install['run'])
        self.assertNotIn('sudo', install['run'])

    # --- the split ------------------------------------------------------------------------------
    def test_write_job_has_no_hub_checkout_and_runs_inline_shell_only(self):
        self.assertEqual(self.write['needs'], 'twin')
        self.assertEqual(self.write['permissions'],
                         {'contents': 'write', 'pull-requests': 'write', 'id-token': 'write'})
        for step in _steps(self.write):
            uses = str(step.get('uses', ''))
            if uses:
                self.assertNotIn('repository', step.get('with', {}), 'the writer checks out driftwood alone')
                self.assertTrue(uses.startswith(INERT), uses)
            script = CONTINUED.sub(' ', COMMENT.sub('', str(step.get('run', ''))))
            hit = PROGRAM.search(script)
            self.assertIsNone(hit, f"the writer runs a program the checker cannot read: {hit and hit.group(0)!r}")
        download = _step(self.write, uses='actions/download-artifact@')
        self.assertEqual(download['with']['name'], 'twin-sweep-handoff')
        validate = _index(self.write, id='handoff')
        install = _index(self.write, name='install pinned gitsign')
        propose = _index(self.write, id='propose')
        observe = _index(self.write, name='observe -- append')
        cage = _index(self.write, name='observation cage')
        self.assertLess(_steps(self.write).index(download), validate)
        self.assertLess(validate, install)
        self.assertLess(install, propose)
        self.assertLess(propose, observe)
        self.assertLess(observe, cage)
        self.assertEqual(_steps(self.write)[propose]['if'], "steps.handoff.outputs.moved == 'true'")
        self.assertIn('commit -S', _steps(self.write)[propose]['run'])
        self.assertIn('gh pr create', _steps(self.write)[propose]['run'])
        self.assertEqual([i for i, s in enumerate(_steps(self.write)) if 'gh pr create' in str(s.get('run', ''))],
                         [propose])
        cage_shell = _steps(self.write)[cage]['run']
        for fragment in CAGE_SHELL:
            self.assertIn(fragment, cage_shell)
        self.assertIn('commit.gpgsign true', cage_shell)
        self.assertEqual(_steps(self.write)[cage]['if'], 'always()')

    # --- the writer as an adversary: every wrong handoff is refused by name ---------------------
    def test_validation_refuses_every_wrong_handoff_and_admits_the_two_right_ones(self):
        shell = _step(self.write, id='handoff')['run']
        paths = self.doc['env']['PROPOSAL_PATHS'].split()
        pin = self.pin['hub_commit']
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / 'repo'
            repo.mkdir()
            env = dict(os.environ, GIT_CONFIG_COUNT='2', GIT_CONFIG_KEY_0='commit.gpgsign',
                       GIT_CONFIG_VALUE_0='false', GIT_CONFIG_KEY_1='core.hooksPath',
                       GIT_CONFIG_VALUE_1='/dev/null', GITHUB_RUN_ID='4242',
                       PROPOSAL_PATHS=self.doc['env']['PROPOSAL_PATHS'])

            def git(*args):
                return subprocess.check_output(['git', '-C', str(repo), *args], env=env, text=True).strip()

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (repo / 'twin').mkdir()
            (repo / 'twin/PIN.yaml').write_text(PIN.read_text())
            git('add', 'twin/PIN.yaml')
            git('commit', '-qm', 'fixture')
            head = git('rev-parse', 'HEAD')

            def line(**over):
                rec = {'swept_at': '2026-09-26T07:05:00Z', 'org': 'driftwood', 'feed': 'forward-intel',
                       'moved': False, 'proposal': '', 'twin_ref': 'policy-as-versioned-flux@' + pin,
                       'adopter_ref': head, 'run': '4242'}
                rec.update(over)
                return json.dumps(rec, sort_keys=True) + '\n'

            case = {'n': 0}

            def run(observation, proposal=None, extra=None):
                case['n'] += 1
                handoff = Path(tmp) / f'handoff-{case["n"]}'
                handoff.mkdir()
                if observation is not None:
                    (handoff / 'observation.jsonl').write_text(observation)
                for rel, body in (proposal or {}).items():
                    (handoff / 'proposal' / rel).parent.mkdir(parents=True, exist_ok=True)
                    (handoff / 'proposal' / rel).write_text(body)
                for rel, body in (extra or {}).items():
                    (handoff / rel).parent.mkdir(parents=True, exist_ok=True)
                    (handoff / rel).write_text(body)
                out = Path(tmp) / f'out-{case["n"]}'
                out.write_text('')
                done = subprocess.run(['bash', '-e', '-c', shell], cwd=repo, capture_output=True, text=True,
                                      env=dict(env, HANDOFF=str(handoff), GITHUB_OUTPUT=str(out)))
                return done.returncode, out.read_text(), done.stdout + done.stderr

            good_proposal = {paths[0]: '{"schema": "fixture"}\n', paths[1]: 'signals: fixture\n'}
            rc, out, said = run(line())
            self.assertEqual(rc, 0, said)
            self.assertIn('moved=false\n', out)
            rc, out, said = run(line(moved=True, proposal='twin/forward-intel-2026-09-26'), good_proposal)
            self.assertEqual(rc, 0, said)
            self.assertIn('moved=true\n', out)
            self.assertIn('proposal=twin/forward-intel-2026-09-26\n', out)

            refused = [
                ('no observation at all', None, None, None, 'no observation.jsonl'),
                ('two lines', line() + line(), None, None, '2 line(s)'),
                ('no final newline', line().rstrip('\n'), None, None, 'final newline'),
                ('not JSON', 'not json\n', None, None, 'not one JSON object'),
                ('an extra key', line(action='tighten'), None, None, 'keys'),
                ('a missing key', json.dumps({'swept_at': '2026-09-26T07:05:00Z'}) + '\n', None, None, 'keys'),
                ('another run', line(run='4243'), None, None, 'names run 4243'),
                ('another org', line(org='tuppence'), None, None, "driftwood's forward-intel line"),
                ('a dateless sweep', line(swept_at='yesterday'), None, None, 'swept_at'),
                ('a string moved', line(moved='true'), None, None, 'moved is not a boolean'),
                ('the hub at main', line(twin_ref='policy-as-versioned-flux@main'), None, None, 'twin_ref'),
                ('the hub at another commit', line(twin_ref='policy-as-versioned-flux@' + 'c' * 40), None, None,
                 'is not the pinned'),
                ('a commit this repository lacks', line(adopter_ref='d' * 40), None, None, 'not a commit this repository has'),
                ('moved with no proposal', line(moved=True, proposal='twin/forward-intel-2026-09-26'), None, None,
                 'carries no proposal/'),
                ('moved with a wrong branch', line(moved=True, proposal='twin/anything'), good_proposal, None,
                 "not the sweep's own branch name"),
                ('moved with one proposal file', line(moved=True, proposal='twin/forward-intel-2026-09-26'),
                 {paths[0]: '{}\n'}, None, 'carries no proposal/' + paths[1]),
                ('a proposed feed that is not JSON', line(moved=True, proposal='twin/forward-intel-2026-09-26'),
                 {paths[0]: 'nope\n', paths[1]: 'x: 1\n'}, None, 'proposed feed is not one JSON object'),
                ('unmoved with a proposal', line(), good_proposal, None, 'moved is false and the handoff carries a proposal'),
                ('unmoved naming a branch', line(proposal='twin/forward-intel-2026-09-26'), None, None,
                 "moved is false and proposal is"),
                ('a declaration smuggled beside the proposal',
                 line(moved=True, proposal='twin/forward-intel-2026-09-26'), good_proposal,
                 {'proposal/party.yaml': 'party: driftwood\n'}, 'proposal/party.yaml is neither'),
                ('a stray file at the top', line(), None, {'deploy.yaml': 'x\n'}, 'deploy.yaml is neither'),
                ('a stray file in a lane-shaped path', line(), None,
                 {'observations/twin-sweep.jsonl': '{}\n'}, 'observations/twin-sweep.jsonl is neither'),
            ]
            for why, observation, proposal, extra, expect in refused:
                rc, out, said = run(observation, proposal, extra)
                self.assertNotEqual(rc, 0, why)
                self.assertEqual(out, '', why + ': nothing may be output when the handoff is refused')
                self.assertIn('::error::the handoff is refused', said, why)
                self.assertIn(expect, said, why)

    # --- the cage, on what its shell does ---------------------------------------------------------
    def test_cage_stages_only_the_lane_and_refuses_a_declaration(self):
        cage = _step(self.write, name='observation cage')['run']
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            env = dict(os.environ, GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_0='commit.gpgsign',
                       GIT_CONFIG_VALUE_0='false', GIT_CONFIG_KEY_1='tag.gpgsign',
                       GIT_CONFIG_VALUE_1='false', GIT_CONFIG_KEY_2='core.hooksPath',
                       GIT_CONFIG_VALUE_2='/dev/null', GITHUB_REF_NAME='main',
                       OBSERVATION_LANE=self.doc['env']['OBSERVATION_LANE'])

            def git(*args):
                return subprocess.check_output(['git', '-C', str(root), *args], env=env, text=True).strip()

            def cage_run():
                return subprocess.run(['bash', '-e', '-c', cage], cwd=root, env=env, capture_output=True, text=True)

            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (root / 'party.yaml').write_text('party: fixture\n')
            git('add', 'party.yaml')
            git('commit', '-qm', 'fixture')
            # nothing to observe: exits 0 before any commit
            clean = cage_run()
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            self.assertIn('nothing to observe', clean.stdout)
            # an observation beside a declaration: the lane is staged, the declaration is not, and the
            # run fails before anything is committed
            (root / 'observations').mkdir()
            (root / 'observations/twin-sweep.jsonl').write_text('{}\n')
            (root / 'party.yaml').write_text('party: changed\n')
            git('add', 'party.yaml')
            rejected = cage_run()
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual(git('diff', '--cached', '--name-only'), 'observations/twin-sweep.jsonl')
            self.assertEqual(git('log', '--oneline').count('\n'), 0, 'one commit, the fixture, nothing committed')
            # on the proposal branch the cage commits nothing at all
            git('checkout', '-q', '--', 'party.yaml')
            git('reset', '-q')
            git('switch', '-qc', 'twin/forward-intel-2026-09-26')
            elsewhere = cage_run()
            self.assertEqual(elsewhere.returncode, 0)
            self.assertIn('the cage commits nothing', elsewhere.stdout)


if __name__ == '__main__':
    unittest.main()
