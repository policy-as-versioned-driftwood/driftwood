"""Exercise the runner command with different compiler and implementation trees.

The external verifier download is a fixture. Installation, checksum and Git
tag/SHA checks, and subprocess execution are real; the published v3 tag is
also checked live.
"""
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = ROOT / '.github/scripts/platform-tools.py'


class ToolBoundary(unittest.TestCase):
    def test_runs_verified_compiler_without_running_implementation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            adopter = root / 'adopter'
            tools = root / 'platform-tools'
            implementation = root / 'platform'
            for path in (adopter / '.github', tools / 'compose', implementation / 'compose', root / 'bin'):
                path.mkdir(parents=True)
            env = dict(os.environ, GIT_CONFIG_COUNT='3', GIT_CONFIG_KEY_0='commit.gpgsign',
                       GIT_CONFIG_VALUE_0='false', GIT_CONFIG_KEY_1='tag.gpgsign',
                       GIT_CONFIG_VALUE_1='false', GIT_CONFIG_KEY_2='core.hooksPath',
                       GIT_CONFIG_VALUE_2='/dev/null')
            def git(*args):
                return subprocess.check_output(['git', '-C', str(tools), *args], env=env, text=True).strip()
            git('init', '-q')
            git('config', 'user.name', 'Test')
            git('config', 'user.email', 'test@example.invalid')
            (tools / 'compose/composition.py').write_text('import sys\nprint("TOOLS", *sys.argv[1:])\n')
            (implementation / 'compose/composition.py').write_text('raise SystemExit("WRONG IMPLEMENTATION EXECUTABLE")\n')
            git('add', '.')
            git('commit', '-qm', 'fixture')
            git('tag', '-a', 'v3.0.0', '-m', 'fixture')
            sha = git('rev-parse', 'HEAD')
            pin = adopter / '.github/platform-tools-pin.yaml'
            pin.write_text(f'kind: GitRepository\nspec:\n  ref:\n    tag: v3.0.0\n    commit: {sha}\n')
            # Provision the verifier through the same installer used before
            # Renovate. Only its remote download is replaced by a fixture.
            verifier = root / 'downloaded-verifier'
            verifier.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$VERIFY_ARGS"\necho "VERIFIER DIAGNOSTIC"\nexit "${VERIFY_EXIT:-0}"\n')
            curl = root / 'bin/curl'
            curl.write_text('#!/bin/sh\ncp "$VERIFIER_FIXTURE" "$3"\n')
            curl.chmod(0o755)
            env.update(PATH=str(root / 'bin') + os.pathsep + env['PATH'],
                       VERIFY_ARGS=str(root / 'args'), VERIFIER_FIXTURE=str(verifier),
                       RUNNER_TEMP=str(root / 'runner-temp'), GITHUB_PATH=str(root / 'github-path'))
            installer = ROOT / '.github/actions/install-gitsign/install.sh'
            digest = hashlib.sha256(verifier.read_bytes()).hexdigest()
            before = sorted(str(p.relative_to(adopter)) for p in adopter.rglob('*'))
            rejected = subprocess.run(['bash', str(installer), '0.17.1', '0' * 64],
                                      cwd=adopter, env=env, capture_output=True, text=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertFalse(Path(env['GITHUB_PATH']).exists())
            self.assertFalse((Path(env['RUNNER_TEMP']) / 'pavf-gitsign/bin/gitsign').exists())
            provision = subprocess.run(['bash', str(installer), '0.17.1', digest],
                                       cwd=adopter, env=env, capture_output=True, text=True)
            self.assertEqual(provision.returncode, 0, provision.stderr)
            installed = Path(env['GITHUB_PATH']).read_text().strip()
            self.assertTrue(installed.startswith(env['RUNNER_TEMP']))
            self.assertEqual(before, sorted(str(p.relative_to(adopter)) for p in adopter.rglob('*')))
            env['PATH'] = installed + os.pathsep + env['PATH']
            cmd = [sys.executable, str(RUNNER), '--adopter-dir', str(adopter),
                   '--tools-dir', str(tools), 'compose', str(adopter), '--estate-clone', str(root)]
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertTrue(result.stdout.startswith('TOOLS compose'), result.stdout)
            self.assertIn('--estate-clone ' + str(root), result.stdout)
            # Exercise the actual two composition commands Renovate's
            # completer runs, with the verifier exported by provisioning.
            scripts = adopter / '.github/scripts'
            scripts.mkdir()
            for filename in ('platform-tools.py', 'read-pins.py'):
                shutil.copy(ROOT / '.github/scripts' / filename, scripts / filename)
            completer = (ROOT / '.github/scripts/complete-feed-bump.sh').read_text()
            commands = completer.split('# Compose TWICE', 1)[1].split('# --- the twin', 1)[0]
            commands = '# Compose TWICE' + commands
            completion = subprocess.run(['bash', '-c', 'set -euo pipefail\n' + commands],
                                        cwd=adopter, env=dict(env, work=str(root),
                                        PATH=str(Path(sys.executable).parent) + os.pathsep + env['PATH']),
                                        capture_output=True, text=True)
            self.assertEqual(completion.returncode, 0, completion.stderr)
            self.assertTrue(completion.stdout.startswith('TOOLS compose'), completion.stdout)
            args = (root / 'args').read_text()
            self.assertIn('cut-release', args)
            self.assertIn('https://token.actions.githubusercontent.com', args)
            result = subprocess.run(cmd, env=dict(env, VERIFY_EXIT='1'), capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('TOOLS compose', result.stdout)
            source = tools / 'compose/composition.py'
            original = source.read_text()
            source.write_text('print("TAMPERED")\n')
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('TAMPERED', result.stdout)
            source.write_text(original)
            pin.write_text(pin.read_text().replace(sha, '0' * 40))
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('TOOLS compose', result.stdout)
            pin.unlink()
            result = subprocess.run(cmd, env=env, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
