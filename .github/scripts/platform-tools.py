#!/usr/bin/env python3
"""Run the independently pinned platform compiler, never the policy parent.

The implementation checkout remains estate/platform at party.yaml's accepted
version. This command verifies the tool tag, commit and release identity before
executing any tool code. ADR-0025 delegated split; no policy-window override.
"""
from __future__ import annotations

import argparse
import os
from pathlib import Path
import re
import subprocess
import sys

from importlib import import_module

read_pin = import_module('read-pins').read_pin
IDENTITY = (r'^https://github\.com/policy-as-versioned-platform/platform/'
            r'\.github/workflows/cut-release\.yml@refs/heads/'
            r'(main|release/[0-9]+\.[0-9]+\.x)$')
ISSUER = 'https://token.actions.githubusercontent.com'
COMMANDS = {'compose': ('compose/composition.py', 'compose'),
            'verify': ('compose/composition.py', 'verify'),
            'tier-check': ('shift-left/tier_binding.py', 'check'),
            'tier-propose': ('wargamer/tier_pr.py', 'run')}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--adopter-dir', type=Path, default=Path('.'))
    parser.add_argument('--tools-dir', type=Path, required=True)
    parser.add_argument('command', choices=[*COMMANDS, 'check'])
    parser.add_argument('args', nargs=argparse.REMAINDER)
    args = parser.parse_args()
    try:
        tag, commit = read_pin(str(args.adopter_dir / '.github/platform-tools-pin.yaml'))
        if not re.fullmatch(r'v[0-9]+\.[0-9]+\.[0-9]+', tag) or not re.fullmatch(r'[a-f0-9]{40}', commit):
            raise ValueError('tool pin requires an exact release tag and 40-character SHA')
        def rev(ref: str) -> str:
            return subprocess.check_output(['git', '-C', str(args.tools_dir), 'rev-parse',
                                            '--verify', ref], text=True).strip()
        if rev('HEAD') != commit or rev(f'refs/tags/{tag}^{{commit}}') != commit:
            raise ValueError('tool checkout or release tag disagrees with the pinned commit')
        dirty = subprocess.check_output(['git', '-C', str(args.tools_dir), 'status',
                                         '--porcelain', '--untracked-files=all'], text=True)
        if dirty.strip():
            raise ValueError('tool checkout differs from its signed release tree')
        subprocess.run(['gitsign', 'verify-tag', tag, '--certificate-identity-regexp=' + IDENTITY,
                        '--certificate-oidc-issuer=' + ISSUER], cwd=args.tools_dir,
                       env=dict(os.environ, GITSIGN_REKOR_MODE='offline'), check=True,
                       capture_output=True, text=True)
        if args.command == 'check':
            print(f'OK: platform tools {tag} at {commit}, release identity verified')
            return 0
        path, command = COMMANDS[args.command]
        return subprocess.run([sys.executable, str(args.tools_dir / path), command, *args.args]).returncode
    except (OSError, ValueError, KeyError, StopIteration, subprocess.CalledProcessError) as exc:
        detail = (exc.stderr or exc.stdout or str(exc)) if isinstance(exc, subprocess.CalledProcessError) else str(exc)
        print(f'REFUSED: platform tools: {detail}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
