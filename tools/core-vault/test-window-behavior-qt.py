#!/usr/bin/python3
"""Exercise Home event routing using real Qt events, no X11 or applications."""
import argparse
import os
from pathlib import Path
import runpy
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', required=True, type=Path)
opt = parser.parse_args()
root = opt.project.resolve()
source = root / 'config/includes.chroot/usr/local/bin/core-vault-home'
assets = root / 'config/includes.chroot/usr/share/core-vault'
os.environ['QT_QPA_PLATFORM'] = 'offscreen'
sys.argv = [str(source), '--self-test', '--assets', str(assets)]
module = runpy.run_path(str(source), run_name='vault_home_under_test')
from PySide6.QtCore import Qt, QPoint, QPointF, QEvent
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication, QWidget, QVBoxLayout, QLabel
app = QApplication.instance() or QApplication([])
app.setStyle('Fusion')
window = module['VaultHome']()
window._test_size = (1280, 800)
window.fit_screen()
window.show()
for _ in range(8):
    app.processEvents()
    window.layout_cards()
calls = []
window.show_home_from_background_click = lambda: calls.append(True)

def press(widget, pos=None):
    pos = pos or widget.rect().center()
    global_pos = widget.mapToGlobal(pos)
    event = QMouseEvent(QEvent.MouseButtonPress, QPointF(pos), QPointF(global_pos),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    QApplication.sendEvent(widget, event)
    app.processEvents()

# This goes through QApplication's installed filter, not a direct method call.
press(window, QPoint(4, window.height() // 2))
if len(calls) != 1:
    raise RuntimeError('Background click did not reach the installed event filter exactly once.')
press(window.cards[0])
if len(calls) != 1:
    raise RuntimeError('Card press was mistaken for a background click.')
# A disabled card can route a press to its parent: rectangle-based exclusion.
card = window.cards[2]
card.setEnabled(False)
p = card.mapTo(window, card.rect().center())
press(window, p)
if len(calls) != 1:
    raise RuntimeError('Disabled card area was mistaken for a background click.')
press(window.shutdown_button)
if len(calls) != 1:
    raise RuntimeError('Shutdown press was mistaken for a background click.')
# A separate top-level preview window may share Home's Python process.
other = QWidget()
layout = QVBoxLayout(other)
label = QLabel('Test window')
layout.addWidget(label)
other.show()
app.processEvents()
press(label)
if len(calls) != 1:
    raise RuntimeError('Click in a separate window was mistaken for a background click.')
other.close()
print('VAULT BACKGROUND CLICK QT EVENT TEST PASSED')
print('Background handled; cards, disabled cards, Shutdown and other windows excluded.')
