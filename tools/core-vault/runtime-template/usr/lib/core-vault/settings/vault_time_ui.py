"""Offline date and time with selected-zone preview and explicit clock changes."""
from datetime import datetime
import json
import subprocess
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, QTimeZone, QTimer, Slot
from PySide6.QtWidgets import (QCheckBox, QComboBox, QCompleter, QDateTimeEdit, QDialog,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout)
from vault_settings import STYLE, Job
from vault_time import TimeError, snapshot, validate_request, zone, zone_names
from vault_device_state import installed_mode


class VaultDateTimeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Date & Time'); self.setStyleSheet(STYLE)
        self.resize(660, 560); self.job = None; self.installed = installed_mode()
        box = QVBoxLayout(self); box.setContentsMargins(24, 20, 24, 20)
        heading = QLabel('Date & Time'); heading.setObjectName('Title'); box.addWidget(heading)
        detail = QLabel(
            'The time zone is saved on this installed Vault. Manual clock changes also update the hardware clock. No network time is used.'
            if self.installed else
            'The time zone applies to this live session. Manual changes affect the running clock only. No hardware clock or network time is used.')
        detail.setWordWrap(True); detail.setObjectName('Muted'); box.addWidget(detail)
        preview_title = QLabel('Current time in the selected time zone')
        preview_title.setAlignment(Qt.AlignCenter); box.addWidget(preview_title)
        self.live = QLabel(); self.live.setAlignment(Qt.AlignCenter); self.live.setTextFormat(Qt.PlainText)
        self.live.setStyleSheet('font-size:22px;font-weight:600;padding:8px;'); box.addWidget(self.live)
        self.zone_status = QLabel(); self.zone_status.setAlignment(Qt.AlignCenter)
        self.zone_status.setTextFormat(Qt.PlainText); self.zone_status.setObjectName('Muted'); box.addWidget(self.zone_status)
        box.addWidget(QLabel('Time zone'))
        self.timezone = QComboBox(); self.timezone.setAccessibleName('Time zone')
        self.timezone.setEditable(True); self.timezone.setInsertPolicy(QComboBox.NoInsert)
        names = zone_names(); self.timezone.addItems(names)
        completer = QCompleter(names, self.timezone); completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains); self.timezone.setCompleter(completer)
        self.timezone.setCurrentText(snapshot()['timezone']); box.addWidget(self.timezone)
        note = QLabel('Changing the time zone keeps the clock running. If the time is still wrong, please set the date and time manually below.')
        note.setWordWrap(True); note.setObjectName('Muted'); box.addWidget(note)
        self.change_clock = QCheckBox('Set date and time manually')
        self.change_clock.setAccessibleName('Set date and time manually')
        box.addWidget(self.change_clock)
        self.manual = QDateTimeEdit(); self.manual.setTimeZone(QTimeZone(b'UTC'))
        self.manual.setAccessibleName('Manual date and time in the selected time zone')
        self.manual.setDisplayFormat('dd.MM.yyyy HH:mm:ss'); self.manual.setKeyboardTracking(False)
        self.manual.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0), QTimeZone(b'UTC')))
        self.manual.setMaximumDateTime(QDateTime(QDate(2100, 12, 31), QTime(23, 59, 59), QTimeZone(b'UTC')))
        self.manual.setEnabled(False); box.addWidget(self.manual)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setTextFormat(Qt.PlainText)
        box.addWidget(self.feedback); box.addStretch(1)
        row = QHBoxLayout(); self.back = QPushButton('Back to Settings')
        self.back.clicked.connect(self.reject); row.addWidget(self.back); row.addStretch(1)
        self.apply = QPushButton('Apply time zone'); self.apply.clicked.connect(self.save); row.addWidget(self.apply)
        box.addLayout(row)
        self.timezone.currentTextChanged.connect(self.selection_changed)
        self.change_clock.toggled.connect(self.manual_changed)
        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self.tick)
        self.timer.start(); self.tick()

    def update_manual(self):
        try:
            now = datetime.now(zone(self.timezone.currentText().strip()))
            self.manual.setDateTime(QDateTime(QDate(now.year, now.month, now.day), QTime(now.hour, now.minute, now.second), QTimeZone(b'UTC')))
        except TimeError:
            pass

    def selection_changed(self, *_):
        self.tick()

    @Slot(bool)
    def manual_changed(self, enabled):
        self.manual.setEnabled(enabled)
        self.apply.setText('Apply date and time' if enabled else 'Apply time zone')
        self.update_manual()
        self.tick()

    def tick(self):
        try:
            name = self.timezone.currentText().strip()
            current = datetime.now(zone(name))
            self.live.setText(current.strftime('%d.%m.%Y. · %H:%M:%S'))
            offset = current.strftime('%z')
            self.zone_status.setText(name + ' · UTC' + offset[:3] + ':' + offset[3:])
            if not self.change_clock.isChecked():
                self.update_manual()
        except TimeError:
            self.live.setText('Please select an available time zone')
            self.zone_status.clear()

    def request_values(self):
        return {'timezone': self.timezone.currentText().strip(),
                'local_time': self.manual.dateTime().toString('yyyy-MM-dd HH:mm:ss')
                if self.change_clock.isChecked() else None}

    def save(self):
        if self.job is not None:
            return
        request = self.request_values()
        try:
            validate_request(request)
        except TimeError as error:
            self.feedback.setText(str(error)); return
        def apply():
            result = subprocess.run(['/usr/bin/pkexec', '/usr/local/libexec/core-vault-time'],
                input=json.dumps(request), capture_output=True, text=True, timeout=60)
            try:
                data = json.loads(result.stdout)
            except (ValueError, TypeError):
                data = {}
            if result.returncode or not isinstance(data, dict) or data.get('ok') is not True:
                message = data.get('error') if isinstance(data, dict) else None
                if not isinstance(message, str) or not 1 <= len(message) <= 1000:
                    message = 'Date and time could not be applied. Please check the local Vault session and selected values.'
                raise TimeError(message)
            return data
        for widget in (self.timezone, self.change_clock, self.manual, self.apply, self.back):
            widget.setEnabled(False)
        self.feedback.setText('Applying date and time…' if request['local_time'] is not None else 'Applying time zone…')
        self.job = Job(apply, self)
        self.job.success.connect(self.applied); self.job.failure.connect(self.failed)
        self.job.finished.connect(self.finished_job); self.job.start()

    @Slot(object)
    def applied(self, result):
        if result.get('clock_changed'):
            text = ('Date and time applied and saved to the hardware clock. Time zone saved for the next startup.'
                    if result.get('rtc_saved') else 'Running clock updated. Time zone applied for this live session.')
        else:
            text = ('Time zone saved for the next startup. The clock was not changed.'
                    if result.get('persistent') else 'Time zone applied for this live session. The clock was not changed.')
        self.feedback.setText(text)
        self.change_clock.setChecked(False)
        self.tick()

    @Slot(str)
    def failed(self, message):
        self.feedback.setText(message)
        self.tick()

    @Slot()
    def finished_job(self):
        job = self.job; self.job = None
        for widget in (self.timezone, self.change_clock, self.apply, self.back):
            widget.setEnabled(True)
        self.manual.setEnabled(self.change_clock.isChecked())
        job.deleteLater()

    def done(self, result):
        if self.job is not None:
            return
        self.timer.stop(); super().done(result)

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
        else:
            super().closeEvent(event)
