#!/usr/bin/python3
"""Real offscreen Qt tests. Never launches an application or powers off a system."""
import argparse, os, sys, runpy
from pathlib import Path
os.environ['QT_QPA_PLATFORM']='offscreen'
ap=argparse.ArgumentParser();ap.add_argument('--project',required=True,type=Path);ap.add_argument('--candidate',type=Path)
ap.add_argument('--runtime-root',type=Path,help='Read-only Debian image root supplying Qt SVG plugins when absent on the build host')
a=ap.parse_args();root=a.project.resolve();candidate=a.candidate.resolve() if a.candidate else root
source=candidate/'config/includes.chroot/usr/local/bin/core-vault-home'
assets=root/'config/includes.chroot/usr/share/core-vault'
sys.argv=[str(source),'--self-test','--assets',str(assets)]
m=runpy.run_path(str(source),run_name='tested_home_v4')
from PySide6.QtCore import Qt, QSize, QCoreApplication
from PySide6.QtGui import QFont, QIcon, QPixmap, QColor
from PySide6.QtWidgets import QApplication
if a.runtime_root:
    plugins=a.runtime_root.resolve(strict=True)/'usr/lib/x86_64-linux-gnu/qt6/plugins'
    if not (plugins/'iconengines/libqsvgicon.so').is_file():
        raise RuntimeError('The selected runtime root lacks Debian Qt SVG icon support.')
    QCoreApplication.addLibraryPath(str(plugins))
app=QApplication.instance() or QApplication(['vault-polish-test']);app.setStyle('Fusion');app.setFont(QFont('DejaVu Sans',10))
QIcon.setThemeName('Adwaita');QIcon.setFallbackThemeName('hicolor')
w=m['VaultHome']();m['self_test'](app,w)
for card in w.cards:
    p=card.icon_label.pixmap()
    bounds,mass=m['icon_bounds'](p.toImage())
    assert not bounds.isEmpty(),card.tool['title']
    logical=max(bounds.width(),bounds.height())/p.devicePixelRatio()
    assert 29<=logical<=39.5,(card.tool['title'],logical)
    assert p.width()/p.devicePixelRatio()==42
# Small icon with excessive transparent padding still becomes visibly full-sized.
p=QPixmap(128,128);p.fill(Qt.transparent)
from PySide6.QtGui import QPainter
paint=QPainter(p);paint.fillRect(60,60,8,8,QColor('white'));paint.end()
out=m['optical_icon'](QIcon(p));bounds,mass=m['icon_bounds'](out.toImage())
assert max(bounds.width(),bounds.height())/out.devicePixelRatio()>=30
for button,name in ((w.restart_button,'Restart'),(w.shutdown_button,'Finish & Shut Down')):
    assert button.text()==''
    assert button.accessibleName()==name
    assert not button.icon().isNull()
    assert button.size()==QSize(48,48)
    assert 'private session' in button.help_text and 'RAM' in button.help_text
    w.show_card_help(button);app.processEvents()
    assert w.hover_popup.isVisible()
    assert w.hover_text.text()==button.help_text
    assert w.hover_popup.geometry().bottom()<button.mapTo(w,button.rect().topLeft()).y()
    w.hide_card_help(button)
print('REAL HOME ICONS + POWER HOVER QT TEST PASSED')
w.deleteLater();app.processEvents()
