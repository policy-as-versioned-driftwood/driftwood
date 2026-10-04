#!/usr/bin/env python3
"""Refresh the current owned feed using the exact published twin producer pin."""
from __future__ import annotations

import ast
from pathlib import Path
import re
import shutil
import subprocess
import sys

import yaml


class UniqueKeys(yaml.SafeLoader):
    pass


def mapping(loader, node, deep=False):
    result = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        if key in result:
            raise ValueError(f'duplicate pin key: {key}')
        result[key] = loader.construct_object(value_node, deep=deep)
    return result


UniqueKeys.add_constructor(yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, mapping)


def refresh(hub: Path) -> None:
    adopter = Path.cwd()
    pin = yaml.load((adopter / 'twin/PIN.yaml').read_text(), Loader=UniqueKeys)
    commit = str(pin['hub_commit'])
    if not re.fullmatch(r'[0-9a-f]{40}', commit):
        raise ValueError('twin/PIN.yaml requires a full hub_commit')
    emitter = adopter / 'twin/emit-forward-intel.py'
    versions = [node.value.value for node in ast.parse(emitter.read_text()).body
                if isinstance(node, ast.Assign)
                and any(isinstance(target, ast.Name) and target.id == 'VERSION' for target in node.targets)
                and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str)]
    if len(versions) != 1 or not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?', versions[0]):
        raise ValueError('emitter must declare one literal VERSION')
    relative = Path('twin/forward-intel') / ('v' + versions[0].split('.')[0]) / 'feed.json'
    subprocess.run(['git', 'clone', '--quiet', '--no-checkout', '--branch', 'main',
                    'https://github.com/policy-as-versioned-flux/policy-as-versioned-flux',
                    str(hub)], check=True)
    subprocess.run(['git', '-C', str(hub), 'merge-base', '--is-ancestor', commit, 'origin/main'], check=True)
    subprocess.run(['git', '-C', str(hub), 'checkout', '--quiet', '--detach', commit], check=True)
    actual = subprocess.check_output(['git', '-C', str(hub), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != commit:
        raise ValueError('hub checkout differs from twin/PIN.yaml')
    mirror = hub / '.estate-clone/driftwood'
    mirror.mkdir(parents=True)
    for directory in ('twin', 'selection-policy'):
        shutil.copytree(adopter / directory, mirror / directory)
    shutil.copyfile(adopter / 'party.yaml', mirror / 'party.yaml')
    subprocess.run([sys.executable, str(mirror / 'twin/emit-forward-intel.py')], check=True)
    # Only the emitter's declared current major moves; frozen historical majors stay intact.
    shutil.copyfile(mirror / relative, adopter / relative)


if __name__ == '__main__':
    try:
        if len(sys.argv) != 2:
            raise ValueError('usage: refresh-twin-feed.py HUB_CHECKOUT_DESTINATION')
        refresh(Path(sys.argv[1]).resolve())
    except (KeyError, ValueError, yaml.YAMLError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f'REFUSED: twin feed refresh: {error}')
