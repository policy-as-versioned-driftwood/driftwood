"""Run Renovate's real completer with local caller fixtures, without network or credentials.

The composer fixture checks ordering only; genuine compiler authentication and
byte replay are exercised separately by RealCompilerLayout.
"""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class FeedCompletion(unittest.TestCase):
    def test_exact_hub_pin_refreshes_current_major_before_composition(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            hub, adopter = root / 'hub-source', root / 'adopter'
            hub.mkdir()
            env = dict(os.environ, GIT_CONFIG_COUNT='3', GIT_EDITOR='true',
                       GIT_CONFIG_KEY_0='commit.gpgsign', GIT_CONFIG_VALUE_0='false',
                       GIT_CONFIG_KEY_1='core.hooksPath', GIT_CONFIG_VALUE_1='/dev/null',
                       GIT_CONFIG_KEY_2='url.' + str(hub) + '.insteadOf',
                       GIT_CONFIG_VALUE_2='https://github.com/policy-as-versioned-')
            # Each production clone URL has its suffix; map those exact URLs
            # to the same harmless local fixture repository instead.
            urls = [('flux/policy-as-versioned-flux', 'hub'), ('platform/platform', 'platform'),
                    ('nist/nist', 'nist'), ('ico/ico', 'ico'), ('feeds/feeds', 'feeds'),
                    ('insurer/insurer', 'insurer')]
            env['GIT_CONFIG_COUNT'] = str(2 + len(urls))
            for index, (suffix, _) in enumerate(urls, 2):
                env[f'GIT_CONFIG_KEY_{index}'] = 'url.' + str(hub) + '.insteadOf'
                env[f'GIT_CONFIG_VALUE_{index}'] = 'https://github.com/policy-as-versioned-' + suffix
            def git(*args):
                return subprocess.check_output(['git', '-C', str(hub), *args],
                                               env=env, text=True).strip()
            git('init', '-q', '-b', 'main')
            git('config', 'user.name', 'Caller fixture')
            git('config', 'user.email', 'fixture@example.invalid')
            (hub / 'producer.txt').write_text('reviewed exact hub')
            git('add', '.')
            git('commit', '-qm', 'pinned producer fixture')
            pinned = git('rev-parse', 'HEAD')
            git('-c', 'tag.gpgsign=false', 'tag', 'fixture')
            (hub / 'producer.txt').write_text('WRONG moving main')
            git('add', '.')
            git('commit', '-qm', 'later moving main fixture')
            scripts = adopter / '.github/scripts'
            scripts.mkdir(parents=True)
            shutil.copy(ROOT / '.github/scripts/complete-feed-bump.sh', scripts)
            refresh = ROOT / '.github/scripts/refresh-twin-feed.py'
            if refresh.exists():
                shutil.copy(refresh, scripts)
            (scripts / 'read-pins.py').write_text("print(' '.join(f'{name}_tag=fixture' for name in ('tools','platform','nist','ico','feeds','insurer')))\n")
            (scripts / 'verify-pinned-checkouts.py').write_text('pass\n')
            (scripts / 'rederive-signals.py').write_text("from pathlib import Path\nPath('twin/signals.yaml').write_text('version: 4\\n')\n")
            (scripts / 'platform-tools.py').write_text("from pathlib import Path\nassert Path('twin/signals.yaml').read_text() == 'version: 4\\n', 'signals stale before compose'\nassert Path('twin/forward-intel/v2/feed.json').read_text() == 'reviewed exact hub', 'current feed stale or wrong hub before compose'\nwith Path('compose-calls').open('a') as out: out.write('compose\\n')\n")
            twin = adopter / 'twin'
            (twin / 'forward-intel/v1').mkdir(parents=True)
            (twin / 'forward-intel/v2').mkdir()
            (twin / 'PIN.yaml').write_text(f'hub_commit: {pinned}\n')
            (twin / 'signals.yaml').write_text('version: 3\n')
            old = b'authentic historical major fixture\n'
            (twin / 'forward-intel/v1/feed.json').write_bytes(old)
            (twin / 'forward-intel/v2/feed.json').write_text('stale current feed')
            (twin / 'emit-forward-intel.py').write_text("from pathlib import Path\nVERSION = '2.0.0'\nhere = Path(__file__).resolve().parent\nhub = here.parents[2]\n(here / 'forward-intel' / ('v' + VERSION.split('.')[0]) / 'feed.json').write_text((hub / 'producer.txt').read_text())\n")
            (adopter / 'selection-policy').mkdir()
            (adopter / 'party.yaml').write_text('id: driftwood\n')
            env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + env['PATH']
            command = ['bash', str(scripts / 'complete-feed-bump.sh')]
            run = subprocess.run(command, cwd=adopter, env=env, text=True, capture_output=True)
            self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
            self.assertEqual((twin / 'forward-intel/v1/feed.json').read_bytes(), old)
            self.assertEqual((twin / 'forward-intel/v2/feed.json').read_text(), 'reviewed exact hub')
            self.assertEqual((adopter / 'compose-calls').read_text(), 'compose\ncompose\n')
            # An unavailable full pin must refuse before copying a feed or composing.
            (adopter / 'compose-calls').unlink()
            (twin / 'PIN.yaml').write_text('hub_commit: ' + '0' * 40 + '\n')
            (twin / 'forward-intel/v2/feed.json').write_text('unchanged on refusal')
            rejected = subprocess.run(command, cwd=adopter, env=env, text=True, capture_output=True)
            self.assertNotEqual(rejected.returncode, 0)
            self.assertEqual((twin / 'forward-intel/v2/feed.json').read_text(), 'unchanged on refusal')
            self.assertEqual((twin / 'forward-intel/v1/feed.json').read_bytes(), old)
            self.assertFalse((adopter / 'compose-calls').exists())


if __name__ == '__main__':
    unittest.main()
