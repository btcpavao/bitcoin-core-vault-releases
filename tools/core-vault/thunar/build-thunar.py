#!/usr/bin/python3
"""Build the patched Thunar executable using extracted Debian development packages.

No package is installed on the host. Supply a patched Debian source tree and an
APT-verified extracted dependency prefix. The prefix is used only at build time;
the executable links to Debian's regular runtime SONAMEs without a private RPATH.
"""
from pathlib import Path
import argparse, os, subprocess

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('source',type=Path)
    p.add_argument('prefix',type=Path)
    p.add_argument('--jobs',type=int,default=2)
    a=p.parse_args()
    source=a.source.resolve(strict=True)
    prefix=a.prefix.resolve(strict=True)
    env=os.environ.copy()
    for k in ['DISPLAY','WAYLAND_DISPLAY','DBUS_SESSION_BUS_ADDRESS','SSH_AUTH_SOCK']:
        env.pop(k,None)
    env.update({
        'LC_ALL':'C.UTF-8',
        'PKG_CONFIG':str(prefix/'usr/bin/pkgconf'),
        'PKG_CONFIG_SYSROOT_DIR':str(prefix),
        'PKG_CONFIG_LIBDIR':':'.join(str(prefix/x) for x in [
            'usr/lib/x86_64-linux-gnu/pkgconfig','usr/lib/pkgconfig','usr/share/pkgconfig']),
        'PKG_CONFIG_PATH':'',
        'LD_LIBRARY_PATH':str(prefix/'usr/lib/x86_64-linux-gnu'),
        'PATH':str(prefix/'usr/bin')+':/usr/bin:/bin',
        'CFLAGS':'-O2 -g -fstack-protector-strong -Wformat -Werror=format-security -fcf-protection',
        'CPPFLAGS':'-D_FORTIFY_SOURCE=2 -I'+str(prefix/'usr/include'),
        'LDFLAGS':'-L'+str(prefix/'usr/lib/x86_64-linux-gnu')+' -Wl,-z,relro -Wl,-z,now -Wl,-O1 -Wl,-z,defs',
    })
    subprocess.run([
        str(source/'configure'), '--prefix=/usr',
        '--x-includes='+str(prefix/'usr/include'),
        '--x-libraries='+str(prefix/'usr/lib/x86_64-linux-gnu'),
        '--libdir=/usr/lib/x86_64-linux-gnu',
        '--with-thunarx-dirs=/usr/lib/x86_64-linux-gnu/thunarx-3:/usr/lib/thunarx-3',
        '--disable-maintainer-mode','--disable-gtk-doc','--disable-introspection',
        '--enable-apr-plugin','--enable-exif','--enable-pcre','--enable-sbr-plugin',
        '--disable-tpa-plugin','--enable-uca-plugin','--enable-gudev',
        '--enable-notifications','--enable-debug=no',
    ],cwd=source,env=env,check=True)
    # Only the native application changes. Debian's extension library/plugins,
    # data and panel applet remain the official binary package payload.
    subprocess.run(['make','-C','thunarx','-j'+str(a.jobs)],cwd=source,env=env,check=True)
    subprocess.run(['make','-C','thunar','-j'+str(a.jobs)],cwd=source,env=env,check=True)

if __name__=='__main__':
    main()
