"""Reviewable USB device-preference transfer; display changes need their own confirmation."""
from pathlib import Path
from PySide6.QtCore import Qt, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout
import device_profile_data as profiles


class DeviceProfilesDialog(QDialog):
    def __init__(self, product, owner, initial_mode='export'):
        super().__init__(owner)
        self.product = product; self.owner = owner; self.profile = None; self.job = None
        if product == 'node':
            from ui import STYLE
        else:
            from vault_settings import STYLE
        self.setStyleSheet(STYLE); self.setWindowTitle('Device Settings')
        self.resize(700, 470)
        box = QVBoxLayout(self)
        heading = QLabel('Device Settings'); heading.setObjectName('Title'); box.addWidget(heading)
        info = QLabel('Transfer keyboard, mouse and saved display preferences using a JSON file. Wallets, passwords, network settings and clock timestamps are excluded.')
        info.setWordWrap(True); info.setObjectName('Muted'); box.addWidget(info)
        note = QLabel('On Vault, imported preferences stay in RAM for this session.' if product == 'vault'
                      else 'On the installed Node, imported input preferences are saved locally.')
        note.setWordWrap(True); box.addWidget(note)
        row = QHBoxLayout()
        self.export_button = QPushButton('Export device settings…'); self.export_button.clicked.connect(self.export_file)
        self.import_button = QPushButton('Open device settings…'); self.import_button.clicked.connect(self.open_file)
        row.addWidget(self.export_button); row.addWidget(self.import_button); box.addLayout(row)
        self.review = QLabel('Please open a profile to review its contents before applying it.')
        self.review.setWordWrap(True); self.review.setTextFormat(Qt.PlainText); box.addWidget(self.review)
        actions = QHBoxLayout()
        self.apply = QPushButton('Apply input settings'); self.apply.setEnabled(False); self.apply.clicked.connect(self.apply_input)
        self.displays = QPushButton('Review display settings'); self.displays.setEnabled(False); self.displays.clicked.connect(self.review_displays)
        actions.addWidget(self.apply); actions.addWidget(self.displays); box.addLayout(actions)
        self.feedback = QLabel(); self.feedback.setWordWrap(True); self.feedback.setTextFormat(Qt.PlainText)
        box.addWidget(self.feedback); box.addStretch(1)
        self.back = QPushButton('Back to Settings'); self.back.clicked.connect(self.reject); box.addWidget(self.back)
        (self.import_button if initial_mode == 'import' else self.export_button).setFocus()

    def choose(self, title, initial, saving=False):
        if self.product == 'node':
            from media_file_dialog import choose_media_file
        else:
            from vault_media_file_dialog import choose_media_file
        return choose_media_file(self, title, initial, saving=saving,
                                 name_filter='Device settings (*.json)')

    def export_file(self):
        if self.job is not None:
            return
        try:
            value = profiles.snapshot(self.product)
            path = self.choose('Export device settings', str(Path.home() / 'device-settings.json'), True)
            if not path:
                return
            profiles.write(path, value, self.product)
            self.feedback.setText('Device settings exported. Please keep the file on external media if you need it after this session.')
        except FileExistsError:
            self.feedback.setText('That file already exists. Please choose a new filename.')
        except (OSError, ValueError, RuntimeError):
            self.feedback.setText('Device settings could not be exported. Please choose a writable destination and check the current settings.')

    def open_file(self):
        if self.job is not None:
            return
        path = self.choose('Open device settings', '/media')
        if not path:
            return
        try:
            value = profiles.read(path, self.product)
        except (OSError, ValueError, RuntimeError):
            self.profile = None; self.apply.setEnabled(False); self.displays.setEnabled(False)
            self.feedback.setText('This is not a valid supported device-settings profile. No changes were made.')
            return
        self.profile = value
        data = value['input']
        names = set(data['pointer']['devices']) | set(data['preferences']['devices'])
        self.review.setText('Keyboard layout: ' + data['layout']['layout'] +
            (' / ' + data['layout']['variant'] if data['layout']['variant'] else '') +
            '\nSaved pointer devices: ' + str(len(names)) +
            '\nDisplay profile: ' + ('available for review' if value['display'] else 'none saved') +
            '\nInput preferences apply only to supported matching devices. Display settings are reviewed separately and require Keep changes confirmation.')
        self.apply.setEnabled(True); self.displays.setEnabled(value['display'] is not None)
        self.feedback.setText('Profile validated. Please choose which settings to apply.')

    def apply_input(self):
        if self.job is not None or self.profile is None:
            return
        if self.product == 'node':
            from ui import Job
        else:
            from vault_settings import Job
        self.feedback.setText('Applying local keyboard and pointer preferences…')
        for control in (self.apply, self.displays, self.import_button, self.export_button, self.back):
            control.setEnabled(False)
        self.job = Job(lambda: profiles.apply_input(self.profile, self.product), self)
        self.job.success.connect(self.applied); self.job.failure.connect(self.failed)
        self.job.finished.connect(self.finished_job); self.job.start()

    @Slot(object)
    def applied(self, result):
        self.feedback.setText('Input preferences applied. Display settings have not changed; use Review display settings to check and apply them.')

    @Slot(str)
    def failed(self, message):
        self.feedback.setText('Some input settings could not be applied. Please reopen Keyboard and Mouse to check the current state. ' + message)

    @Slot()
    def finished_job(self):
        job = self.job; self.job = None
        for control in (self.apply, self.import_button, self.export_button, self.back):
            control.setEnabled(True)
        self.displays.setEnabled(self.profile is not None and self.profile['display'] is not None)
        job.deleteLater()

    def review_displays(self):
        if self.profile is None or self.profile['display'] is None:
            return
        registry = getattr(self.owner, '_modeless_windows', {}) if self.product == 'node' else getattr(self.owner, '_settings_windows', {})
        if registry.get('display_settings') is not None:
            self.feedback.setText('Please close the existing Display Settings window before reviewing the imported display profile.')
            self.owner.display_settings()
            return
        self.owner.display_settings(imported_profile=self.profile['display'])

    def done(self, result):
        if self.job is None:
            super().done(result)

    def closeEvent(self, event):
        if self.job is not None:
            event.ignore()
        else:
            super().closeEvent(event)
