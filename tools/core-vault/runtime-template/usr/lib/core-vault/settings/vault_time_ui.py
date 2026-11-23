"""Offline Date & Time UI: explicit system-clock action, session-only timezone."""
from datetime import datetime
import json
import subprocess
from PySide6.QtCore import Qt, QDate, QTime, QDateTime, QTimeZone, QTimer, Slot
from PySide6.QtWidgets import (QComboBox, QCompleter, QDateTimeEdit, QDialog,
    QHBoxLayout, QLabel, QPushButton, QVBoxLayout)
from vault_settings import STYLE, Job
from vault_time import TimeError, snapshot, validate_request, zone, zone_names


class VaultDateTimeDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Date & Time'); self.setStyleSheet(STYLE)
        self.resize(640, 500); self.job = None
        box = QVBoxLayout(self); box.setContentsMargins(24, 20, 24, 20)
        heading = QLabel('Date & Time'); heading.setObjectName('Title'); box.addWidget(heading)
        detail = QLabel('Set the running system clock manually. The time zone stays in RAM for this session. This does not enable network time or write the hardware clock.')
        detail.setWordWrap(True); detail.setObjectName('Muted'); box.addWidget(detail)
        self.live = QLabel(); self.live.setAlignment(Qt.AlignCenter)
        self.live.setStyleSheet('font-size:22px;font-weight:600;padding:8px;'); box.addWidget(self.live)
        box.addWidget(QLabel('Time zone'))
        self.timezone = QComboBox(); self.timezone.setAccessibleName('Time zone')
        self.timezone.setEditable(True); self.timezone.setInsertPolicy(QComboBox.NoInsert)
        names = zone_names(); self.timezone.addItems(names)
        completer = QCompleter(names, self.timezone); completer.setCaseSensitivity(Qt.CaseInsensitive)
        completer.setFilterMode(Qt.MatchContains); self.timezone.setCompleter(completer)
        self.timezone.setCurrentText(snapshot()['timezone']); box.addWidget(self.timezone)
        box.addWidget(QLabel('Manual date and time'))
        self.manual = QDateTimeEdit(); self.manual.setTimeZone(QTimeZone(b'UTC'))
        self.manual.setAccessibleName('Manual date and time')
        self.manual.setDisplayFormat('dd.MM.yyyy HH:mm:ss'); self.manual.setKeyboardTracking(False)
        self.manual.setMinimumDateTime(QDateTime(QDate(2000, 1, 1), QTime(0, 0), Qt.UTC))
        self.manual.setMaximumDateTime(QDateTime(QDate(2100, 12, 31), QTime(23, 59, 59), Qt.UTC))
        box.addWidget(self.manual)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setTextFormat(Qt.PlainText)
        box.addWidget(self.feedback); box.addStretch(1)
        row = QHBoxLayout(); self.back = QPushButton('Back to Settings')
        self.back.clicked.connect(self.reject); row.addWidget(self.back); row.addStretch(1)
        self.apply = QPushButton('Apply date and time'); self.apply.clicked.connect(self.save); row.addWidget(self.apply)
        box.addLayout(row)
        self.timezone.currentTextChanged.connect(self.update_manual)
        self.timer = QTimer(self); self.timer.setInterval(1000); self.timer.timeout.connect(self.tick)
        self.timer.start(); self.update_manual(); self.tick()

    def update_manual(self, *_):
        try:
            now = datetime.now(zone(self.timezone.currentText().strip()))
            self.manual.setDateTime(QDateTime(QDate(now.year, now.month, now.day), QTime(now.hour, now.minute, now.second), Qt.UTC))
        except TimeError:
            pass

    def tick(self):
        try:
            current = datetime.now(zone(snapshot()['timezone']))
            self.live.setText(current.strftime('%d.%m.%Y. · %H:%M:%S'))
        except TimeError:
            self.live.setText('Current local time unavailable')

    def save(self):
        if self.job is not None:
            return
        request = {'timezone': self.timezone.currentText().strip(),
                   'local_time': self.manual.dateTime().toString('yyyy-MM-dd HH:mm:ss')}
        try:
            validate_request(request)
        except TimeError as error:
            self.feedback.setText(str(error)); return
        def apply():
            result = subprocess.run(['/usr/bin/pkexec', '/usr/local/libexec/core-vault-time'],
                input=json.dumps(request), capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise TimeError('Date and time could not be applied. Please check the local Vault session and selected values.')
            return json.loads(result.stdout)
        for widget in (self.timezone, self.manual, self.apply, self.back):
            widget.setEnabled(False)
        self.feedback.setText('Applying manual date and time…')
        self.job = Job(apply, self)
        self.job.success.connect(self.applied); self.job.failure.connect(self.failed)
        self.job.finished.connect(self.finished_job); self.job.start()

    @Slot(object)
    def applied(self, result):
        self.feedback.setText('Manual system time applied. The time zone is set for this session.')
        self.tick()

    @Slot(str)
    def failed(self, message):
        self.feedback.setText(message)

    @Slot()
    def finished_job(self):
        job = self.job; self.job = None
        for widget in (self.timezone, self.manual, self.apply, self.back):
            widget.setEnabled(True)
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
