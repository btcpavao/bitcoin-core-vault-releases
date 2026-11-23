"""Local Settings windows for the offline, RAM-only Vault desktop."""
from pathlib import Path
import subprocess
import sys

from PySide6.QtCore import Qt, QSize, QThread, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QApplication, QDialog, QGridLayout, QHBoxLayout,
    QLabel, QMessageBox, QPushButton, QScrollArea, QStyle, QVBoxLayout, QWidget)

ASSETS = Path('/usr/share/core-vault')
if not ASSETS.is_dir():
    ASSETS = Path(__file__).resolve().parents[3] / 'share/core-vault'

# Same control/card styling as the Node Settings screen.
STYLE = '''
QWidget { background:#0b0b0b; color:#f2f2f2; font-size:14px; }
QLabel#Title { font-size:30px; font-weight:700; }
QLabel#Muted { color:#b5b5b5; }
QPushButton#ToolCard { background:#151515; border:1px solid #333; border-radius:10px; padding:0; }
QPushButton#ToolCard:hover { background:#202020; border-color:#555; }
QPushButton#ToolCard:focus { border:2px solid #f7931a; }
QPushButton#ToolCard QLabel { background:transparent; border:none; }
QLabel#CardTitle { font-size:14px; font-weight:600; }
QLabel#CardDescription { font-size:11px; color:#b5b5b5; }
QPushButton { background:#181818; border:1px solid #555; border-radius:8px; padding:12px; }
QPushButton:hover { background:#282828; }
QPushButton:focus, QLineEdit:focus, QComboBox:focus { border:2px solid #f7931a; }
QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QDateTimeEdit { background:#151515; color:#f2f2f2; border:1px solid #666; padding:8px; }
QComboBox { combobox-popup:0; selection-background-color:#343434; selection-color:#fff; }
QComboBox QAbstractItemView { background:#121212; color:#fff; border:1px solid #4a4a4a; padding:4px; outline:0; selection-background-color:#343434; selection-color:#fff; }
QComboBox QAbstractItemView::item { min-height:28px; padding:4px 8px; }
QCheckBox { spacing:8px; }
QCheckBox::indicator { width:18px; height:18px; border:2px solid #888; border-radius:3px; background:#151515; }
QCheckBox::indicator:checked { background:#f7931a; border-color:#f2f2f2; }
QWidget:disabled { color:#777; }
QPushButton#SettingsExit { padding:4px 12px; font-size:12px; border-radius:6px; min-width:0; }
'''


class Job(QThread):
    success = Signal(object)
    failure = Signal(str)

    def __init__(self, operation, parent=None):
        super().__init__(parent)
        self.operation = operation

    def run(self):
        try:
            self.success.emit(self.operation())
        except (ValueError, RuntimeError) as error:
            self.failure.emit(str(error))
        except Exception:
            self.failure.emit('The local setting could not be applied. Please check the connected device and try again.')
        finally:
            self.operation = None


def open_window(home, key, factory):
    if not hasattr(home, '_settings_windows'):
        home._settings_windows = {}
    current = home._settings_windows.get(key)
    if current is not None:
        if current.isMinimized():
            current.showNormal()
        current.show(); current.raise_(); current.activateWindow()
        return current
    dialog = factory()
    dialog.setParent(None, Qt.Window)
    dialog.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
    dialog.setWindowModality(Qt.NonModal)
    dialog.setModal(False)
    home._settings_windows[key] = dialog

    def finished(_):
        if home._settings_windows.get(key) is dialog:
            home._settings_windows.pop(key, None)
        dialog.deleteLater()

    dialog.finished.connect(finished)
    dialog.show(); dialog.raise_(); dialog.activateWindow()
    return dialog


def display_module():
    path = Path('/usr/share/core-desktop')
    if not path.is_dir():
        path = Path(__file__).resolve().parents[3] / 'share/core-desktop'
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
    from core_display_settings import DisplaySettingsDialog
    return DisplaySettingsDialog


def show_display(home, imported_profile=None):
    return open_window(home, 'display_settings', lambda: display_module()(
        product='vault', parent=home, imported_profile=imported_profile))


def show_profiles(home, mode='export'):
    from device_profiles import DeviceProfilesDialog
    return open_window(home, 'device_profiles', lambda: DeviceProfilesDialog(
        'vault', home, initial_mode=mode))


class Card(QPushButton):
    def __init__(self, title, detail, icon, action):
        super().__init__()
        self.setObjectName('ToolCard')
        self.setAccessibleName(title)
        self.setAccessibleDescription(detail)
        self.setToolTip(detail)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumWidth(0)
        self.setFixedHeight(148)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 9, 7, 9)
        layout.setSpacing(3)
        image = QLabel(); image.setFixedHeight(42)
        image.setPixmap(icon.pixmap(QSize(42, 42)))
        heading = QLabel(title); heading.setObjectName('CardTitle')
        heading.setWordWrap(True); heading.setMinimumHeight(45); heading.setMaximumHeight(55)
        text = QLabel(detail); text.setObjectName('CardDescription')
        text.setWordWrap(True); text.setMinimumHeight(28)
        for item in (image, heading, text):
            item.setAlignment(Qt.AlignCenter)
            item.setAttribute(Qt.WA_TransparentForMouseEvents)
            layout.addWidget(item)
        self.clicked.connect(action)


def icon(name, fallback):
    asset = QIcon(str(ASSETS / 'icons' / name))
    return asset if not asset.isNull() else QApplication.style().standardIcon(fallback)


class VaultSettingsDialog(QDialog):
    def __init__(self, home):
        super().__init__(home)
        self.home = home
        self.setWindowTitle('Settings')
        self.setWindowIcon(QIcon(str(ASSETS / 'icons/settings.svg')))
        self.setStyleSheet(STYLE)
        screen = QApplication.primaryScreen()
        area = screen.availableGeometry() if screen else None
        self.resize(min(960, max(560, area.width()-40)) if area else 900,
                    min(555, max(440, area.height()-40)) if area else 555)
        box = QVBoxLayout(self); box.setContentsMargins(18, 15, 18, 13)
        box.addStretch(1)
        title = QLabel('Settings'); title.setObjectName('Title'); title.setAlignment(Qt.AlignCenter)
        box.addWidget(title)
        subtitle = QLabel('Configure displays, local devices, date and time, and wallet backups.\nDevice preferences stay in RAM for this private session.')
        subtitle.setWordWrap(True); subtitle.setObjectName('Muted'); subtitle.setAlignment(Qt.AlignCenter)
        box.addWidget(subtitle); box.addSpacing(24)
        self.scroll = QScrollArea(); self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.page = QWidget(); self.grid = QGridLayout(self.page)
        self.grid.setContentsMargins(0, 0, 0, 0); self.grid.setSpacing(14)
        self.scroll.setWidget(self.page); box.addWidget(self.scroll, 1)
        entries = [
            ('Display Settings', 'Resolution, size and multiple displays', 'settings-display.svg', QStyle.SP_ComputerIcon, lambda: show_display(home)),
            ('Keyboard and Mouse', 'Typing, buttons, scrolling and speed', 'settings-mouse.png', QStyle.SP_ComputerIcon, self.keyboard),
            ('Date & Time', 'Manual clock and local time zone', 'settings-date-time.png', QStyle.SP_FileDialogDetailedView, self.date_time),
            ('Backup and Restore', 'Encrypted wallet backups and recovery', 'settings-chain-backup.png', QStyle.SP_DialogSaveButton, self.backups),
        ]
        self.cards = {}
        self.card_order = tuple(entry[0] for entry in entries)
        for title, detail, filename, fallback, action in entries:
            self.cards[title] = Card(title, detail, icon(filename, fallback), action)
        self.reflow()
        box.addStretch(1)
        row = QHBoxLayout()
        for text, mode in [('Export device settings…', 'export'), ('Import device settings…', 'import')]:
            button = QPushButton(text); button.setObjectName('SettingsExit')
            button.clicked.connect(lambda checked=False, m=mode: show_profiles(home, m))
            row.addWidget(button)
        row.addStretch(1)
        self.exit_button = QPushButton('Exit'); self.exit_button.setObjectName('SettingsExit')
        self.exit_button.setAccessibleName('Exit Settings'); self.exit_button.setFixedSize(78, 32)
        self.exit_button.clicked.connect(self.reject); row.addWidget(self.exit_button)
        box.addLayout(row)

    def reflow(self):
        columns = 4 if self.width() >= 740 else 2
        rows = (len(self.cards)+columns-1)//columns
        content_height = rows*148+(rows-1)*14
        visible_height = min(content_height, max(120, self.height()-210))
        self.scroll.setMinimumHeight(visible_height)
        self.scroll.setMaximumHeight(content_height)
        scrollbar = self.style().pixelMetric(QStyle.PM_ScrollBarExtent) if content_height>visible_height else 0
        card_width = max(104, (self.width()-36-scrollbar-(columns-1)*14)//columns)
        while self.grid.count():
            self.grid.takeAt(0)
        for i, card in enumerate(self.cards.values()):
            card.setFixedWidth(card_width)
            self.grid.addWidget(card, i//columns, i % columns)

    def resizeEvent(self, event):
        if hasattr(self, 'cards'):
            self.reflow()
        super().resizeEvent(event)

    def keyboard(self):
        from vault_input_ui import KeyboardMouseDialog
        return open_window(self.home, 'keyboard_mouse', lambda: KeyboardMouseDialog(self))

    def date_time(self):
        from vault_time_ui import VaultDateTimeDialog
        return open_window(self.home, 'date_time', lambda: VaultDateTimeDialog(self))

    def backups(self):
        return open_window(self.home, 'backup_restore', lambda: BackupRestoreDialog(self))


class BackupRestoreDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.home = getattr(parent, 'home', None)
        self.setWindowTitle('Backup and Restore'); self.setStyleSheet(STYLE)
        self.resize(650, 440)
        box = QVBoxLayout(self)
        title = QLabel('Backup and Restore'); title.setObjectName('Title'); box.addWidget(title)
        text = QLabel('Create a verified encrypted wallet backup, or decrypt an existing backup into Private Workspace. Please save necessary backups to external media before ending the session.')
        text.setWordWrap(True); box.addWidget(text)
        for caption, command in (
            ('Wallet Backup', ['/usr/local/bin/core-vault-wallet-backup']),
            ('Decrypt Backup', ['/usr/bin/core-vault-backup', 'decrypt'])):
            button = QPushButton(caption)
            button.clicked.connect(lambda checked=False, c=command: self.launch(c))
            box.addWidget(button)
        recovery = QLabel('After decrypting a wallet backup, open Bitcoin Core and choose File → Restore Wallet. Select the recovered wallet.dat and give the wallet a name. The recovered wallet remains in the private RAM workspace.')
        recovery.setWordWrap(True); recovery.setObjectName('Muted'); box.addWidget(recovery)
        core = QPushButton('Open Bitcoin Core')
        core.clicked.connect(lambda: self.launch(['/usr/local/bin/core-vault-bitcoin']))
        box.addWidget(core)
        box.addStretch(1)
        back = QPushButton('Back to Settings'); back.clicked.connect(self.reject); box.addWidget(back)

    def launch(self, command):
        try:
            refresh = getattr(self.home, 'refresh_launch_environment', None)
            if refresh is not None:
                refresh()
            subprocess.Popen(command, start_new_session=True)
        except OSError:
            QMessageBox.warning(self, 'Application unavailable', 'Please check the installed Vault application and try again.')
