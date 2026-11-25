"""Shared native Display Settings dialog for Node and Vault."""
# SPDX-License-Identifier: GPL-3.0-or-later
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal, Slot
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDialog,
    QFileDialog, QFormLayout, QFrame, QGroupBox, QHBoxLayout, QLabel,
    QMessageBox, QPushButton, QScrollArea, QVBoxLayout, QWidget)

import core_display as display


STYLE = '''
QWidget { background:#0b0b0b; color:#f2f2f2; font-size:14px; }
QLabel#Title { font-size:28px; font-weight:700; }
QLabel#Muted { color:#b5b5b5; }
QLabel#Status { color:#d5d5d5; }
QGroupBox { border:1px solid #333; border-radius:8px; margin-top:12px; padding:14px 12px 10px; font-weight:600; }
QGroupBox::title { subcontrol-origin:margin; left:12px; padding:0 5px; }
QScrollArea { border:none; background:transparent; }
QPushButton { background:#181818; border:1px solid #555; border-radius:8px; padding:9px 14px; min-height:18px; }
QPushButton:hover { background:#282828; }
QPushButton:focus, QComboBox:focus { border:2px solid #f7931a; }
QPushButton#Apply { background:#f2f2f2; border-color:#f2f2f2; color:#111; font-weight:600; }
QPushButton#Apply:hover { background:#fff; }
QPushButton:disabled { color:#777; border-color:#333; background:#151515; }
QComboBox { background:#151515; border:1px solid #666; border-radius:4px; padding:6px 8px; min-height:20px; combobox-popup:0; }
QComboBox:disabled { color:#777; border-color:#333; }
QComboBox QAbstractItemView { background:#121212; color:#fff; border:1px solid #4a4a4a; padding:4px; outline:0; selection-background-color:#343434; selection-color:#fff; }
QComboBox QAbstractItemView::item { min-height:26px; padding:4px 8px; }
QComboBoxPrivateContainer { background:#121212; border:1px solid #4a4a4a; padding:0; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:16px; height:16px; border:2px solid #888; border-radius:3px; background:#151515; }
QCheckBox::indicator:checked { background:#f7931a; border-color:#f2f2f2; }
'''


def configure_application(app):
    app.setStyle('Fusion')
    palette = QPalette()
    for role, color in [('Window','#0b0b0b'),('WindowText','#f2f2f2'),('Base','#151515'),
                        ('Text','#f2f2f2'),('Button','#181818'),('ButtonText','#f2f2f2'),
                        ('Highlight','#343434'),('HighlightedText','#fff'),('ToolTipBase','#181818'),
                        ('ToolTipText','#f2f2f2')]:
        palette.setColor(getattr(QPalette, role), QColor(color))
    app.setPalette(palette)


def label(text, muted=False):
    widget = QLabel(text)
    widget.setWordWrap(True)
    widget.setTextFormat(Qt.PlainText)
    if muted:
        widget.setObjectName('Muted')
    return widget


class ProbeJob(QThread):
    result = Signal(object)
    failed = Signal(str)

    def __init__(self, backend, parent):
        super().__init__(parent)
        self.backend = backend

    def run(self):
        try:
            self.result.emit(self.backend.probe())
        except (OSError, display.DisplayError):
            self.failed.emit('Display information is unavailable. Please check that a display is connected and try Refresh.')


class TransactionJob(QThread):
    changed = Signal(object)
    failed = Signal(str)

    def __init__(self, product, profile, parent, factory=None):
        super().__init__(parent)
        self.product, self.profile = product, profile
        self.factory = factory or display.start_transaction
        self.process, self.pending_action = None, None
        self.lock = threading.Lock()

    def decide(self, action):
        if action not in ('keep', 'revert'):
            return
        with self.lock:
            self.pending_action = action
            if self.process is not None:
                try:
                    self.process.stdin.write((action + '\n').encode())
                    self.process.stdin.flush()
                    self.pending_action = None
                except (BrokenPipeError, OSError, ValueError):
                    pass

    def run(self):
        completed = False
        try:
            process = self.factory(self.product, self.profile)
            with self.lock:
                self.process = process
                if self.pending_action:
                    process.stdin.write((self.pending_action + '\n').encode())
                    process.stdin.flush()
                    self.pending_action = None
            while True:
                raw = process.stdout.readline(4097)
                if not raw:
                    break
                if len(raw) > 4096:
                    raise display.DisplayError('The display service returned an invalid response.')
                value = json.loads(raw)
                if value.get('state') in ('kept', 'reverted', 'error'):
                    completed = True
                self.changed.emit(value)
            process.wait(timeout=20)
            if not completed:
                display.recover_abandoned(self.product)
                self.failed.emit('The display change ended unexpectedly. The safety process restores unconfirmed changes.')
        except Exception:
            try:
                display.recover_abandoned(self.product)
            except (display.DisplayError, OSError):
                pass
            self.failed.emit('The display change could not be completed. Unconfirmed changes are restored automatically.')
        finally:
            with self.lock:
                process = self.process
                if process is not None:
                    for stream in (process.stdin, process.stdout, process.stderr):
                        try:
                            stream.close()
                        except (AttributeError, OSError):
                            pass
                self.process = None


class KeepDialog(QDialog):
    decision = Signal(str)

    def __init__(self, seconds, parent):
        super().__init__(parent)
        self.setWindowTitle('Keep display settings?')
        self.setStyleSheet(STYLE)
        self.setModal(True)
        self.seconds = max(1, int(seconds))
        self.sent = False
        box = QVBoxLayout(self)
        box.setContentsMargins(24, 20, 24, 20)
        title = label('Keep these display settings?')
        title.setObjectName('Title')
        box.addWidget(title)
        self.message = label('')
        box.addWidget(self.message)
        row = QHBoxLayout()
        revert = QPushButton('Revert')
        revert.setObjectName('DisplayRevert')
        revert.setDefault(True)
        revert.clicked.connect(lambda: self.choose('revert'))
        keep = QPushButton('Keep changes')
        keep.setObjectName('DisplayKeep')
        keep.setStyleSheet('background:#f2f2f2; color:#111; font-weight:600;')
        keep.clicked.connect(lambda: self.choose('keep'))
        row.addWidget(revert)
        row.addWidget(keep)
        box.addLayout(row)
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self.tick)
        self.update_message()
        self.timer.start()
        self.resize(520, 190)

    def update_message(self):
        self.message.setText('Please confirm that the image is readable. The previous settings return automatically in '
                             + str(self.seconds) + ' seconds.')

    def tick(self):
        self.seconds = max(0, self.seconds - 1)
        self.update_message()
        if not self.seconds:
            self.choose('revert')

    def choose(self, action):
        if self.sent:
            return
        self.sent = True
        self.timer.stop()
        self.decision.emit(action)
        super().done(QDialog.Accepted if action == 'keep' else QDialog.Rejected)

    def reject(self):
        self.choose('revert')

    def finish(self):
        self.sent = True
        self.timer.stop()
        super().done(QDialog.Rejected)


class OutputControls(QGroupBox):
    changed = Signal()

    def __init__(self, output, parent=None):
        super().__init__(output.label, parent)
        self.output = output
        form = QFormLayout(self)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.resolution = QComboBox()
        self.resolution.setObjectName('DisplayResolution_' + output.name)
        self.resolution.setAccessibleName(output.label + ' resolution')
        self.resolution.setMinimumContentsLength(14)
        for mode in output.modes:
            caption = str(mode.width) + ' × ' + str(mode.height)
            if mode.preferred:
                caption += ' (recommended)'
            self.resolution.addItem(caption, mode.name)
        self.rate = QComboBox()
        self.rate.setObjectName('DisplayRate_' + output.name)
        self.rate.setAccessibleName(output.label + ' refresh rate')
        self.rotation = QComboBox()
        self.rotation.setObjectName('DisplayRotation_' + output.name)
        self.rotation.setAccessibleName(output.label + ' orientation')
        for caption, value in [('Landscape', 'normal'), ('Portrait left', 'left'),
                               ('Portrait right', 'right'), ('Upside down', 'inverted')]:
            if value in output.rotations:
                self.rotation.addItem(caption, value)
        self.rotation_label = QLabel('Orientation')
        form.addRow('Resolution', self.resolution)
        form.addRow('Refresh rate', self.rate)
        form.addRow(self.rotation_label, self.rotation)
        selected = output.mode or (output.preferred_mode().name if output.preferred_mode() else None)
        self.resolution.setCurrentIndex(max(0, self.resolution.findData(selected)))
        self.refresh_rates(output.rate)
        self.rotation.setCurrentIndex(max(0, self.rotation.findData(output.rotation)))
        self.resolution.currentIndexChanged.connect(self.resolution_changed)
        self.rate.currentIndexChanged.connect(self.changed)
        self.rotation.currentIndexChanged.connect(self.changed)
        self.advanced(False)

    def advanced(self, enabled):
        self.rotation.setVisible(enabled)
        self.rotation_label.setVisible(enabled)

    def resolution_changed(self, *_):
        self.refresh_rates()
        self.changed.emit()

    def refresh_rates(self, selected=None):
        old = selected or self.rate.currentData()
        mode = self.output.find_mode(self.resolution.currentData())
        self.rate.blockSignals(True)
        self.rate.clear()
        for rate in mode.rates if mode else []:
            self.rate.addItem('Automatic' if rate == '0' else rate + ' Hz', rate)
        self.rate.setCurrentIndex(max(0, self.rate.findData(old)))
        self.rate.blockSignals(False)

    def select(self, item):
        index = self.resolution.findData(item['mode'])
        if index >= 0:
            self.resolution.setCurrentIndex(index)
            self.refresh_rates(item['rate'])
        self.rotation.setCurrentIndex(max(0, self.rotation.findData(item['rotation'])))


class DisplaySettingsDialog(QDialog):
    def __init__(self, product='node', parent=None, imported_profile=None, backend=None,
                 transaction_factory=None):
        super().__init__(parent)
        self.product = display.product_name(product)
        self.backend = backend or display.Backend()
        self.transaction_factory = transaction_factory
        self.snapshot, self.rows = None, {}
        self.probe_job, self.job = None, None
        self.confirmation = None
        self.imported_profile = display.validate_profile(imported_profile) if imported_profile is not None else None
        self.pending_close, self.populate_guard, self.last_result = None, False, None
        self.closed = False
        self.setWindowTitle('Display Settings')
        self.setStyleSheet(STYLE)
        self.setMinimumSize(540, 420)
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(820, max(540, area.width() - 40)) if area else 820,
                    min(720, max(420, area.height() - 50)) if area else 650)
        box = QVBoxLayout(self)
        box.setContentsMargins(20, 16, 20, 14)
        box.setSpacing(10)
        title_row = QHBoxLayout()
        heading = label('Display Settings')
        heading.setObjectName('Title')
        title_row.addWidget(heading, 1)
        self.refresh_button = QPushButton('Refresh')
        self.refresh_button.setObjectName('DisplayRefresh')
        self.refresh_button.clicked.connect(lambda: self.refresh(True))
        title_row.addWidget(self.refresh_button)
        box.addLayout(title_row)
        note = ('Choose a resolution and arrange your displays. Confirm changes before they are saved.' if product == 'node'
                else 'Choose a resolution and arrange your displays. Confirm changes before they are saved. ' + display.vault_device_state().notice())
        box.addWidget(label(note, True))
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.body = QWidget()
        body = QVBoxLayout(self.body)
        body.setContentsMargins(0, 0, 8, 0)
        body.setSpacing(12)
        form = QFormLayout()
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        self.mode = QComboBox()
        self.mode.setObjectName('DisplayPreset')
        self.mode.setAccessibleName('Display mode')
        for caption, value in [('Built-in display only', 'built-in'), ('Mirror displays', 'mirror'),
                               ('Extend desktop', 'extend'), ('External display only', 'external')]:
            self.mode.addItem(caption, value)
        self.external = QComboBox()
        self.external.setObjectName('DisplayExternal')
        self.external.setAccessibleName('External display to use')
        self.external_label = QLabel('External display')
        self.primary = QComboBox()
        self.primary.setObjectName('DisplayPrimary')
        self.primary.setAccessibleName('Primary display')
        self.arrangement = QComboBox()
        self.arrangement.setObjectName('DisplayArrangement')
        self.arrangement.setAccessibleName('Position of other displays')
        for caption, value in [('To the right', 'right'), ('To the left', 'left'), ('Below', 'below'), ('Above', 'above')]:
            self.arrangement.addItem(caption, value)
        self.arrangement_label = QLabel('Other displays')
        form.addRow('Display mode', self.mode)
        form.addRow(self.external_label, self.external)
        form.addRow('Primary display', self.primary)
        form.addRow(self.arrangement_label, self.arrangement)
        self.scale = QComboBox()
        self.scale.setObjectName('DisplayScale')
        self.scale.setAccessibleName('Interface size')
        self.scale.addItem('Automatic', 'auto')
        for percent in range(100, 301, 25):
            self.scale.addItem(str(percent) + '%', display.validate_scale(percent / 100))
        form.addRow('Interface size', self.scale)
        body.addLayout(form)
        body.addWidget(label('Interface size changes text and controls, separately from resolution. One size is used across displays. Some applications may need to be reopened; your session will not restart.', True))
        self.mirror_box = QGroupBox('Shared mirror settings')
        mirror_form = QFormLayout(self.mirror_box)
        self.mirror_resolution = QComboBox()
        self.mirror_resolution.setObjectName('DisplayMirrorResolution')
        self.mirror_resolution.setAccessibleName('Shared mirror resolution')
        self.mirror_rate = QComboBox()
        self.mirror_rate.setObjectName('DisplayMirrorRate')
        self.mirror_rate.setAccessibleName('Shared mirror refresh rate')
        self.mirror_rotation = QComboBox()
        self.mirror_rotation.setObjectName('DisplayMirrorRotation')
        self.mirror_rotation.setAccessibleName('Shared mirror orientation')
        for caption, value in [('Landscape', 'normal'), ('Portrait left', 'left'),
                               ('Portrait right', 'right'), ('Upside down', 'inverted')]:
            self.mirror_rotation.addItem(caption, value)
        self.mirror_rotation_label = QLabel('Orientation')
        mirror_form.addRow('Resolution', self.mirror_resolution)
        mirror_form.addRow('Refresh rate', self.mirror_rate)
        mirror_form.addRow(self.mirror_rotation_label, self.mirror_rotation)
        self.mirror_displays = label('', True)
        mirror_form.addRow(self.mirror_displays)
        self.mirror_rotation.hide()
        self.mirror_rotation_label.hide()
        body.addWidget(self.mirror_box)
        self.outputs_box = QVBoxLayout()
        body.addLayout(self.outputs_box)
        self.advanced = QCheckBox('Advanced — display orientation')
        self.advanced.setObjectName('DisplayAdvanced')
        self.advanced.toggled.connect(self.toggle_advanced)
        body.addWidget(self.advanced)
        self.layout_note = label('', True)
        body.addWidget(self.layout_note)
        body.addStretch(1)
        self.scroll.setWidget(self.body)
        box.addWidget(self.scroll, 1)
        self.status = label('Reading connected displays…')
        self.status.setObjectName('Status')
        box.addWidget(self.status)
        profiles = QHBoxLayout()
        self.export_button = QPushButton('Export display settings…')
        self.export_button.setObjectName('DisplayExport')
        self.export_button.clicked.connect(self.export_settings)
        self.import_button = QPushButton('Import display settings…')
        self.import_button.setObjectName('DisplayImport')
        self.import_button.clicked.connect(self.import_settings)
        profiles.addWidget(self.export_button)
        profiles.addWidget(self.import_button)
        profiles.addStretch(1)
        box.addLayout(profiles)
        buttons = QHBoxLayout()
        self.apply_button = QPushButton('Apply')
        self.apply_button.setObjectName('DisplayApply')
        self.apply_button.setStyleSheet('background:#f2f2f2; color:#111; font-weight:600;')
        self.apply_button.clicked.connect(self.apply_changes)
        self.back_button = QPushButton('Back to Settings')
        self.back_button.setObjectName('DisplayBack')
        self.back_button.clicked.connect(self.accept)
        buttons.addWidget(self.apply_button)
        buttons.addStretch(1)
        buttons.addWidget(self.back_button)
        box.addLayout(buttons)
        self.mode.currentIndexChanged.connect(self.preset_changed)
        self.external.currentIndexChanged.connect(self.preset_changed)
        self.mirror_resolution.currentIndexChanged.connect(self.mirror_resolution_changed)
        self.mirror_rate.currentIndexChanged.connect(self.synchronize_mirror)
        self.mirror_rotation.currentIndexChanged.connect(self.mirror_rotation_changed)
        self.poll = QTimer(self)
        self.poll.setInterval(5000)
        self.poll.timeout.connect(lambda: self.refresh(False))
        self.poll.start()
        app = QApplication.instance()
        app.primaryScreenChanged.connect(self.relocate)
        app.screenRemoved.connect(self.relocate)
        app.screenAdded.connect(self.screen_added)
        self.refresh(True)

    def busy(self):
        return self.job is not None or self.probe_job is not None

    def set_controls(self):
        idle = not self.busy()
        ready = self.snapshot is not None and bool(self.snapshot.connected)
        # A background topology check must not close an open combo box or make
        # the whole form flicker. Only explicit refresh/apply blocks editing.
        reading = self.probe_job is not None and (self.manual_refresh or self.snapshot is None)
        self.body.setEnabled(self.job is None and not reading and ready)
        self.apply_button.setEnabled(idle and ready)
        self.refresh_button.setEnabled(idle)
        self.export_button.setEnabled(idle and ready)
        self.import_button.setEnabled(idle and ready)

    def refresh(self, manual=False):
        if self.closed or self.busy() or self.pending_close is not None:
            return
        if not manual and any(combo.view().isVisible() for combo in self.findChildren(QComboBox)):
            return
        self.manual_refresh = manual
        self.probe_job = ProbeJob(self.backend, self)
        self.probe_job.result.connect(self.received_snapshot)
        self.probe_job.failed.connect(self.probe_failed)
        self.probe_job.finished.connect(self.probe_finished)
        self.set_controls()
        self.probe_job.start()

    @Slot(object)
    def received_snapshot(self, snapshot):
        changed = self.snapshot is not None and self.snapshot.topology() != snapshot.topology()
        first = self.snapshot is None
        self.snapshot = snapshot
        if first or changed or self.manual_refresh:
            self.populate()
            if self.imported_profile is not None:
                imported, self.imported_profile = self.imported_profile, None
                self.stage_profile(imported)
            elif changed:
                self.status.setText('The connected displays changed. Please review the available settings before applying.')
            elif not self.last_result:
                self.status.setText('Changes are tested for 15 seconds before confirmation.')

    @Slot(str)
    def probe_failed(self, message):
        self.status.setText(message)

    @Slot()
    def probe_finished(self):
        previous, self.probe_job = self.probe_job, None
        if previous:
            previous.deleteLater()
        self.set_controls()
        if self.pending_close is not None:
            self.done(self.pending_close)

    def populate(self):
        self.populate_guard = True
        old_primary = self.primary.currentData()
        while self.outputs_box.count():
            item = self.outputs_box.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self.rows = {}
        self.external.clear()
        for output in self.snapshot.connected:
            row = OutputControls(output, self.body)
            row.changed.connect(self.output_changed)
            row.advanced(self.advanced.isChecked())
            self.rows[output.name] = row
            self.outputs_box.addWidget(row)
            if not output.builtin:
                self.external.addItem(output.label, output.name)
        builtin = any(o.builtin for o in self.snapshot.connected)
        self.mode.model().item(self.mode.findData('built-in')).setEnabled(builtin)
        self.mode.model().item(self.mode.findData('external')).setEnabled(bool(self.external.count()))
        for value in ('mirror', 'extend'):
            self.mode.model().item(self.mode.findData(value)).setEnabled(len(self.snapshot.connected) > 1)
        saved = display.load_saved(self.product)
        scale = saved['layout']['scale'] if saved else 'auto'
        self.select_scale(scale)
        try:
            current = display.layout_from_snapshot(self.snapshot, scale)
            desired = current['preset']
        except display.DisplayError:
            desired = 'built-in' if builtin else 'external'
        self.mode.setCurrentIndex(max(0, self.mode.findData(desired)))
        active_external = next((o.name for o in self.snapshot.active if not o.builtin), None)
        if active_external:
            self.external.setCurrentIndex(max(0, self.external.findData(active_external)))
        self.populate_guard = False
        self.preset_changed()
        actual_primary = next((o.name for o in self.snapshot.active if o.primary), old_primary)
        self.primary.setCurrentIndex(max(0, self.primary.findData(actual_primary)))

    def select_scale(self, scale):
        scale = display.validate_scale(scale)
        index = self.scale.findData(scale)
        if index < 0:
            self.scale.addItem(str(round(float(scale) * 100, 2)) + '%', scale)
            index = self.scale.count() - 1
        self.scale.setCurrentIndex(index)

    def enabled_outputs(self):
        if self.snapshot is None:
            return []
        preset = self.mode.currentData()
        if preset == 'built-in':
            return [next(o.name for o in self.snapshot.connected if o.builtin)] if any(o.builtin for o in self.snapshot.connected) else []
        if preset == 'external':
            return [self.external.currentData()] if self.external.currentData() else []
        return [o.name for o in self.snapshot.connected if o.modes]

    def preset_changed(self, *_):
        if self.populate_guard or self.snapshot is None:
            return
        enabled = self.enabled_outputs()
        mirror = self.mode.currentData() == 'mirror'
        external = self.mode.currentData() == 'external'
        extend = self.mode.currentData() == 'extend'
        self.external.setVisible(external)
        self.external_label.setVisible(external)
        self.arrangement.setVisible(extend)
        self.arrangement_label.setVisible(extend)
        self.mirror_box.setVisible(mirror)
        selected = self.primary.currentData()
        self.primary.blockSignals(True)
        self.primary.clear()
        for name in enabled:
            self.primary.addItem(self.snapshot.find(name).label, name)
        self.primary.setCurrentIndex(max(0, self.primary.findData(selected)))
        self.primary.blockSignals(False)
        for name, row in self.rows.items():
            row.setEnabled(name in enabled)
            row.setVisible(name in enabled and not mirror)
            row.resolution.setEnabled(name in enabled and not mirror)
            row.rate.setEnabled(name in enabled and not mirror)
        if mirror:
            self.fill_mirror_modes()
            for index in range(self.mirror_rotation.count()):
                supported = all(self.mirror_rotation.itemData(index) in self.snapshot.find(name).rotations for name in enabled)
                self.mirror_rotation.model().item(index).setEnabled(supported)
            if not self.mirror_rotation.model().item(self.mirror_rotation.currentIndex()).isEnabled():
                self.mirror_rotation.setCurrentIndex(0)
            self.mirror_rotation_changed()
            self.mirror_displays.setText('Same picture on: ' + ', '.join(self.snapshot.find(name).label for name in enabled) + '.')
        off = [o.label for o in self.snapshot.connected if o.name not in enabled]
        self.layout_note.setText('Apply will switch off: ' + ', '.join(off) + '.' if off else
                                'All connected displays are included in this arrangement.')

    def shared_modes(self):
        shared = None
        for name in self.enabled_outputs():
            available = {}
            for mode in self.snapshot.find(name).modes:
                available.setdefault((mode.width, mode.height), set()).update(mode.rates)
            shared = available if shared is None else {
                key: shared[key] & available[key] for key in shared.keys() & available.keys()
                if shared[key] & available[key]}
        return shared or {}

    def fill_mirror_modes(self):
        previous = self.mirror_resolution.currentData()
        self.mirror_resolution.blockSignals(True)
        self.mirror_resolution.clear()
        for size in sorted(self.shared_modes(), key=lambda size: size[0] * size[1], reverse=True):
            self.mirror_resolution.addItem(str(size[0]) + ' × ' + str(size[1]), size)
        self.mirror_resolution.setCurrentIndex(max(0, self.mirror_resolution.findData(previous)))
        self.mirror_resolution.blockSignals(False)
        self.mirror_resolution_changed()
        if not self.mirror_resolution.count():
            self.status.setText('These displays have no shared resolution and refresh rate. Please choose Extend desktop or one display only.')

    def mirror_resolution_changed(self, *_):
        if self.populate_guard or self.mode.currentData() != 'mirror':
            return
        previous = self.mirror_rate.currentData()
        self.mirror_rate.blockSignals(True)
        self.mirror_rate.clear()
        for rate in sorted(self.shared_modes().get(self.mirror_resolution.currentData(), ()), key=float, reverse=True):
            self.mirror_rate.addItem('Automatic' if rate == '0' else rate + ' Hz', rate)
        self.mirror_rate.setCurrentIndex(max(0, self.mirror_rate.findData(previous)))
        self.mirror_rate.blockSignals(False)
        self.synchronize_mirror()

    def synchronize_mirror(self, *_):
        if self.populate_guard or self.mode.currentData() != 'mirror':
            return
        size, rate = self.mirror_resolution.currentData(), self.mirror_rate.currentData()
        if size is None or rate is None:
            return
        self.populate_guard = True
        for name in self.enabled_outputs():
            output = self.snapshot.find(name)
            mode = next((m for m in output.modes if (m.width, m.height) == tuple(size) and rate in m.rates), None)
            if mode:
                row = self.rows[name]
                row.resolution.setCurrentIndex(row.resolution.findData(mode.name))
                row.refresh_rates(rate)
        self.populate_guard = False

    def output_changed(self):
        if self.populate_guard:
            return
        if self.mode.currentData() == 'mirror':
            changed = self.sender()
            if isinstance(changed, OutputControls):
                rotation = changed.rotation.currentData()
                self.populate_guard = True
                for row in self.rows.values():
                    row.rotation.setCurrentIndex(row.rotation.findData(rotation))
                self.populate_guard = False

    def mirror_rotation_changed(self, *_):
        if self.populate_guard or self.mode.currentData() != 'mirror':
            return
        rotation = self.mirror_rotation.currentData()
        self.populate_guard = True
        for row in self.rows.values():
            row.rotation.setCurrentIndex(row.rotation.findData(rotation))
        self.populate_guard = False

    def toggle_advanced(self, enabled):
        for row in self.rows.values():
            row.advanced(enabled)
        self.mirror_rotation.setVisible(enabled)
        self.mirror_rotation_label.setVisible(enabled)

    def requested_layout(self):
        enabled = self.enabled_outputs()
        display.require(enabled, 'Please choose an available display.')
        primary = self.primary.currentData()
        display.require(primary in enabled, 'Please choose an available primary display.')
        ordered = [primary] + [name for name in enabled if name != primary]
        configs, sizes = [], {}
        for name in ordered:
            row = self.rows[name]
            mode_name, rate, rotation = row.resolution.currentData(), row.rate.currentData(), row.rotation.currentData()
            mode = self.snapshot.find(name).find_mode(mode_name)
            display.require(mode is not None and rate is not None, 'Please choose a supported resolution and refresh rate.')
            sizes[name] = (mode.height, mode.width) if rotation in ('left', 'right') else (mode.width, mode.height)
            configs.append(dict(name=name, mode=mode_name, rate=rate, x=0, y=0,
                                rotation=rotation, primary=name == primary))
        preset, arrangement = self.mode.currentData(), self.arrangement.currentData()
        if preset == 'extend':
            order = list(reversed(configs)) if arrangement in ('left', 'above') else configs
            cursor = 0
            for config in order:
                if arrangement in ('left', 'right'):
                    config['x'] = cursor
                    cursor += sizes[config['name']][0]
                else:
                    config['y'] = cursor
                    cursor += sizes[config['name']][1]
        return display.validate_live_layout(dict(outputs=configs, scale=self.scale.currentData(),
                                                  preset=preset, arrangement=arrangement), self.snapshot)

    def apply_changes(self):
        if self.busy() or self.snapshot is None:
            return
        try:
            profile = display.make_profile(self.product, self.snapshot, self.requested_layout())
        except display.DisplayError as exc:
            self.status.setText(str(exc))
            return
        self.last_result = None
        self.job = TransactionJob(self.product, profile, self, self.transaction_factory)
        self.job.changed.connect(self.transaction_changed)
        self.job.failed.connect(self.transaction_failed)
        self.job.finished.connect(self.transaction_finished)
        self.status.setText('Applying display settings…')
        self.set_controls()
        self.job.start()

    @Slot(object)
    def transaction_changed(self, result):
        state = result.get('state')
        if state == 'pending':
            if self.pending_close is not None:
                self.job.decide('revert')
                return
            self.confirmation = KeepDialog(result.get('seconds', display.CONFIRM_SECONDS), self)
            self.confirmation.decision.connect(self.job.decide)
            self.relocate()
            self.confirmation.open()
            QTimer.singleShot(50, self.relocate)
            return
        if self.confirmation is not None:
            self.confirmation.finish()
            self.confirmation.deleteLater()
            self.confirmation = None
        message = result.get('message', 'Display settings could not be changed.')
        self.last_result = state
        self.status.setText(message)
        if state == 'kept':
            env = display.launch_environment()
            for key in ('QT_SCALE_FACTOR', 'QT_SCREEN_SCALE_FACTORS', 'QT_FONT_DPI',
                        'QT_AUTO_SCREEN_SCALE_FACTOR', 'QT_USE_PHYSICAL_DPI'):
                os.environ.pop(key, None)
            os.environ.update(env)
            self.status.setText(message + ' Some open applications may need to be reopened for the interface size to update.')
            try:
                chosen = self.job.profile['layout']['scale']
                runtime = Path(os.environ['XDG_RUNTIME_DIR']) / 'core-display-scale.json'
                with runtime.open('rb') as stream:
                    effective = display.decode_json(stream.read(display.PROFILE_LIMIT + 1))['scale']
                if chosen != 'auto' and float(effective) < float(chosen):
                    self.status.setText(message + ' Interface size is limited to '
                                        + str(round(float(effective) * 100)) + '% so the controls fit on every active display.')
            except (OSError, KeyError, ValueError, TypeError):
                pass

    @Slot(str)
    def transaction_failed(self, message):
        self.transaction_changed(dict(state='error', message=message))

    @Slot()
    def transaction_finished(self):
        previous, self.job = self.job, None
        if previous:
            previous.deleteLater()
        self.set_controls()
        self.relocate()
        if self.pending_close is not None:
            self.done(self.pending_close)
        else:
            self.refresh(True)

    def stage_profile(self, profile):
        try:
            profile = display.validate_profile(profile)
            display.require(display.matches_hardware(profile, self.snapshot),
                            'This profile describes different connected displays. Please choose the settings for this computer.')
            layout = display.validate_live_layout(profile['layout'], self.snapshot)
            display.require(layout['preset'] != 'custom', 'Please select a display mode for this imported custom layout.')
            self.populate_guard = True
            self.mode.setCurrentIndex(self.mode.findData(layout['preset']))
            if layout['preset'] == 'external':
                self.external.setCurrentIndex(self.external.findData(layout['outputs'][0]['name']))
            self.arrangement.setCurrentIndex(self.arrangement.findData(layout['arrangement']))
            self.select_scale(layout['scale'])
            self.populate_guard = False
            self.preset_changed()
            self.populate_guard = True
            for item in layout['outputs']:
                self.rows[item['name']].select(item)
            primary = next(item['name'] for item in layout['outputs'] if item['primary'])
            self.primary.setCurrentIndex(self.primary.findData(primary))
            if layout['preset'] == 'mirror':
                item = layout['outputs'][0]
                self.mirror_rotation.setCurrentIndex(self.mirror_rotation.findData(item['rotation']))
                mode = self.snapshot.find(item['name']).find_mode(item['mode'])
                self.mirror_resolution.setCurrentIndex(self.mirror_resolution.findData((mode.width, mode.height)))
                self.populate_guard = False
                self.mirror_resolution_changed()
                self.mirror_rate.setCurrentIndex(self.mirror_rate.findData(item['rate']))
            self.populate_guard = False
            self.status.setText('Imported settings are ready to review. Please choose Apply to test them; no display settings have changed.')
        except (display.DisplayError, OSError) as exc:
            self.populate_guard = False
            self.status.setText(str(exc))

    def import_settings(self):
        filename, _ = QFileDialog.getOpenFileName(self, 'Import display settings', '/media', 'Display settings (*.json)')
        if not filename:
            return
        try:
            self.stage_profile(display.read_profile(filename))
        except (display.DisplayError, OSError):
            self.status.setText('Please choose a valid display settings JSON file of at most 32 KiB.')

    def export_settings(self):
        if self.snapshot is None:
            return
        # Export the confirmed/current layout, not untested edits in the form.
        try:
            saved = display.load_saved(self.product)
            scale = saved['layout']['scale'] if saved else 'auto'
            value = display.make_profile(self.product, self.snapshot, display.layout_from_snapshot(self.snapshot, scale))
            filename, _ = QFileDialog.getSaveFileName(self, 'Export display settings', '/media/display-settings.json', 'Display settings (*.json)')
            if filename:
                display.export_profile(filename, value)
                self.status.setText('Display settings exported. This file contains display preferences only.')
        except (display.DisplayError, OSError):
            self.status.setText('The display settings could not be exported. Please choose a writable folder or USB drive.')

    def screen_added(self, *_):
        self.relocate()
        QTimer.singleShot(700, lambda: self.refresh(False))

    def relocate(self, *_):
        screens = QApplication.screens()
        if not screens:
            return
        screen = QApplication.primaryScreen() or screens[0]
        area = screen.availableGeometry()
        for window in (self, self.confirmation):
            if window is None:
                continue
            frame = window.frameGeometry()
            if not any(s.availableGeometry().contains(frame) for s in screens):
                window.resize(min(window.width(), max(420, area.width() - 30)),
                              min(window.height(), max(240, area.height() - 40)))
                window.move(area.x() + max(0, (area.width() - window.width()) // 2),
                            area.y() + max(0, (area.height() - window.height()) // 2))

    def done(self, result):
        if self.busy():
            self.pending_close = result
            if self.job is not None:
                self.job.decide('revert')
                self.status.setText('Restoring unconfirmed display changes…')
            return
        self.poll.stop()
        self.closed = True
        super().done(result)
