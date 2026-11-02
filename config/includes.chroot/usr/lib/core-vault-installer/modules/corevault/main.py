# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import libcalamares
sys.path.insert(0, '/usr/lib/core-vault-installer')
import target

def pretty_name():
    return 'Configure and verify Bitcoin Core Vault'

def run():
    try:
        root = libcalamares.globalstorage.value('rootMountPoint')
        phase = libcalamares.job.configuration.get('phase')
        if phase == 'target':
            return target.configure(root)
        if phase == 'verify':
            return target.verify(root)
        raise target.TargetError('Unknown installer verification phase.')
    except Exception as exc:
        return ('Bitcoin Core Vault installation stopped', str(exc))
