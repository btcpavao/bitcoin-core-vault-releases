# SPDX-License-Identifier: GPL-3.0-or-later
import sys
import libcalamares
sys.path.insert(0,'/usr/lib/core-offline-installer')
import target

def pretty_name():
    return 'Configure and verify Bitcoin Core Offline'

def run():
    try:
        root=libcalamares.globalstorage.value('rootMountPoint')
        phase=libcalamares.job.configuration.get('phase')
        if phase=='target': return target.configure(root)
        if phase=='verify': return target.verify(root)
        return ('Bitcoin Bitcoin Core Offline configuration error','Unknown target job phase.')
    except Exception as e:
        return ('Bitcoin Bitcoin Core Offline installation stopped',str(e))
