"""Local, responsive SVG explanations for Vault Guide. No network or wallet access."""
from __future__ import annotations

from html import escape
from PySide6.QtCore import Qt, QPointF, QRectF
from PySide6.QtGui import QColor, QFont, QFontMetricsF, QImage, QPainter, QPen, QPolygonF

COLORS = {
    'ink': '#f2f2f2', 'muted': '#c4c4c4', 'line': '#777777',
    'blue': '#8ecbff', 'amber': '#ffc47e', 'green': '#a5dfb0',
    'purple': '#d0b3ff',
}
FILLS = {'blue': '#142431', 'amber': '#2a2117', 'green': '#17271d',
         'purple': '#241c30', 'ink': '#202020'}

# Alt text is also shown as selectable text, independent of the illustration.
VISUALS = {
    'Watch-Only Wallet in Bitcoin Core': ('pairing', 'Public view and private authority',
        'Vault keeps the private keys. Core exports a public watch-only copy into Private Workspace by default. Files copies that export to USB for Restore Wallet on the online node. Compare receiving addresses independently; only Vault signs.'),
    'Home & keyboard': ('keyboard', 'Move around Home with the keyboard',
        'F12 shows Home or returns to your applications. Tab and Shift+Tab move focus; Space activates a control. In the power confirmation, Enter selects No and Esc cancels.'),
    'Bitcoin Core': ('wallet', 'Two different kinds of protection',
        'Core encryption protects private-key material inside wallet.dat. Public information may remain readable. External GPG encryption protects the whole backup package; its passphrase is separate.'),
    'Create & encrypt a wallet': ('wallet', 'Understand what each lock protects',
        'Create the wallet in Bitcoin Core. Core encryption optionally locks its private keys. A verified GPG backup protects the complete exported file. Keep the required Core and GPG passphrases separately recoverable.'),
    'KeePassXC': ('phrases', 'Choose a length; generate each secret independently',
        'The diagram uses word placeholders, not usable passphrases. KeePassXC starts at six random words; you may choose eight. Generate a fresh phrase for each independent layer and keep recovery copies.'),
    'Generate a passphrase': ('phrases', 'Fresh random words for every independent secret',
        'Six-word and eight-word layouts are examples of lengths. These placeholders are not secrets. Do not derive B or C by making small changes to A; generate each independently in KeePassXC.'),
    'Files': ('storage', 'Working in RAM, saving to a medium',
        'Wallets and working files are temporary. Explicitly export verified encrypted backups and required transfer files to external media. Ending the session removes private RAM files, not files already saved on external media.'),
    'Private Workspace': ('storage', 'What disappears, and what remains',
        'Private Workspace, the private home and Core data are in RAM. The operating system and installed applications remain on the internal disk. Files deliberately saved on external media remain there after the private session ends.'),
    'USB & optical media': ('media', 'Give transfer media and backup copies clear roles',
        'PSBT transfer media carry transaction files. Backup media hold verified encrypted copies. Keep independent copies on different devices and in different locations, and periodically test recovery.'),
    'Brasero': ('optical', 'Writing a disc is only the first step',
        'Write the encrypted backup, read the written disc back and verify it, then store independent copies in different locations. Test recovery periodically; a label is not proof that a disc is readable.'),
    'Print & Labels': ('paper', 'Instructions that make a backup identifiable',
        'This sample label and recovery note contain no secrets. Record the backup identifier, date, verification and access instructions. Keep instructions available outside the backup they explain.'),
    'Editor': ('paper', 'Make the recovery plan readable',
        'Write a simple inventory and recovery checklist without embedding secrets automatically. The location where you save a document determines whether it remains after the session.'),
    'Terminal': ('terminal', 'Read the command before running it',
        'GPG is the program. For a current one-layer wallet backup, wallet.dat.gpg is the encrypted input and wallet.dat is the recovered output. No TAR step is needed. Enter the passphrase at the prompt and follow the RAM-only recovery instructions.'),
    'Encryption security levels': ('layers', 'Every extra layer adds a required secret',
        'A single wallet.dat is encrypted directly; other files and folders first become a standard TAR package. Every GPG layer has an independent required passphrase. Layers do not create Bitcoin multisig or a signing threshold.'),
    'Backup & verify': ('verify', 'Verify the round trip before relying on a copy',
        'Vault compares full authenticated recovery with the original snapshot, then checks the encrypted copy on the destination. A complete restore and signing drill tests the wider recovery plan.'),
    'Finish Private Session': ('finish', 'Two confirmations, then five minutes to reconsider',
        'Confirm that you saved what you need, then confirm the loss of unsaved RAM data. The five-minute countdown can be cancelled or explicitly skipped. Core and the clipboard stay available until the countdown ends. Shutdown never asks for passphrases or verifies backups.'),
    'Sign a PSBT offline': ('psbt', 'Transaction files travel; private keys do not',
        'An online coordinator prepares a PSBT. Transfer it by removable media to Private Workspace, review and sign in the offline Vault, then return the signed PSBT for online broadcast. A PSBT transfer does not carry private keys.'),
    'Recovery / inheritance': ('recovery', 'Redundancy within groups; every required group available',
        'This three-layer example needs one usable backup copy plus A, B and C. Copies within a group are alternatives. Each group is still required. Core-encrypted private keys additionally need the separate Core passphrase for signing.'),
    'Decrypt Backup': ('decrypt', 'Stop when the original files are recovered',
        'Enter all required passphrases in any order. Vault opens the outer layers and validates either a complete wallet.dat or a TAR package. An original document.gpg inside a package stays encrypted.'),
}


class Drawing:
    """Measured text and geometric shapes; labels never shrink to fit."""
    def __init__(self, width):
        self.width = int(width)
        self.parts = []
        self.bounds = []
        self.operations = []

    @staticmethod
    def metrics(size, bold=False, mono=False):
        font = QFont('DejaVu Sans Mono' if mono else 'DejaVu Sans')
        font.setPixelSize(size)
        font.setBold(bold)
        return QFontMetricsF(font)

    def lines(self, text, width, size=18, bold=False, mono=False):
        fm = self.metrics(size, bold, mono)
        result = []
        for paragraph in str(text).split('\n'):
            line = ''
            for word in paragraph.split(' '):
                candidate = (line + ' ' + word).strip()
                if line and fm.horizontalAdvance(candidate) > width:
                    result.append(line)
                    line = word
                else:
                    line = candidate
            result.append(line)
        return result

    def text_height(self, text, width, size=18, bold=False):
        return len(self.lines(text, width, size, bold)) * (size + 7)

    def text(self, x, y, text, width, size=18, color='ink', bold=False, mono=False):
        lines = self.lines(text, width, size, bold, mono)
        fm = self.metrics(size, bold, mono)
        for index, line in enumerate(lines):
            measured = fm.horizontalAdvance(line)
            self.operations.append(('text', (x, y + fm.ascent() + index * (size + 7), line, size, COLORS.get(color, color), bold, mono)))
            self.bounds.append((x, y + index * (size + 7), measured, size + 7))
            self.parts.append(
                '<text x="%g" y="%g" fill="%s" font-family="%s" font-size="%d" font-weight="%s">%s</text>' %
                (x, y + fm.ascent() + index * (size + 7), COLORS.get(color, color),
                 'DejaVu Sans Mono' if mono else 'DejaVu Sans', size,
                 '700' if bold else '400', escape(line)))
        return len(lines) * (size + 7)

    def rect(self, x, y, width, height, tone='ink', radius=10, dashed=False):
        self.operations.append(('rect', (x, y, width, height, radius, FILLS[tone], COLORS[tone] if tone != 'ink' else '#666666', dashed)))
        self.parts.append(
            '<rect x="%g" y="%g" width="%g" height="%g" rx="%d" fill="%s" stroke="%s" stroke-width="1.5"%s/>' %
            (x, y, width, height, radius, FILLS[tone], COLORS[tone] if tone != 'ink' else '#666666',
             ' stroke-dasharray="6 5"' if dashed else ''))

    def box_height(self, width, title, body=''):
        return 32 + self.text_height(title, width - 32, 20, True) + (
            8 + self.text_height(body, width - 32) if body else 0)

    def box(self, x, y, width, title, body='', tone='ink', height=None):
        height = height or self.box_height(width, title, body)
        self.rect(x, y, width, height, tone)
        top = y + 16
        top += self.text(x + 16, top, title, width - 32, 20, tone if tone != 'ink' else 'ink', True)
        if body:
            self.text(x + 16, top + 8, body, width - 32, color='muted')
        return height

    def arrow(self, x1, y1, x2, y2, tone='muted'):
        color = COLORS[tone]
        self.operations.append(('line', (x1, y1, x2, y2, color, 2)))
        self.parts.append('<path d="M %g %g L %g %g" fill="none" stroke="%s" stroke-width="2"/>' %
                          (x1, y1, x2, y2, color))
        if abs(y2 - y1) >= abs(x2 - x1):
            dy = -7 if y2 > y1 else 7
            points = [(x2 - 5, y2 + dy), (x2, y2), (x2 + 5, y2 + dy)]
        else:
            dx = -7 if x2 > x1 else 7
            points = [(x2 + dx, y2 - 5), (x2, y2), (x2 + dx, y2 + 5)]
        self.operations.append(('polyline', (points, color)))
        self.parts.append('<polyline points="%s" fill="none" stroke="%s" stroke-width="2"/>' %
                          (' '.join('%g,%g' % p for p in points), color))

    def footer(self, y, text, tone='blue'):
        self.operations.append(('line', (1, y + 8, self.width - 1, y + 8, '#4a4a4a', 1)))
        self.parts.append('<path d="M 1 %g H %g" stroke="%s" stroke-width="1"/>' %
                          (y + 8, self.width - 1, '#4a4a4a'))
        return y + 26 + self.text(0, y + 26, text, self.width, color=tone, bold=True) + 8

    def pair(self, y, a, b):
        width = (self.width - 24) / 2
        height = max(self.box_height(width, a[0], a[1]), self.box_height(width, b[0], b[1]))
        self.box(1, y, width - 1, *a[:2], tone=a[2], height=height)
        self.box(width + 24, y, width - 1, *b[:2], tone=b[2], height=height)
        return y + height

    def paint(self, height, scale):
        # QTextBrowser displays a device-scale image. Draw the same measured
        # vector commands directly with Qt; no SVG decoder or network is needed.
        scale = max(1.0, min(3.0, float(scale)))
        image = QImage(round(self.width * scale), round(height * scale), QImage.Format.Format_ARGB32_Premultiplied)
        image.fill(Qt.GlobalColor.transparent)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        painter.scale(scale, scale)
        for kind, values in self.operations:
            if kind == 'text':
                x, y, text, size, color, bold, mono = values
                font = QFont('DejaVu Sans Mono' if mono else 'DejaVu Sans')
                font.setPixelSize(size); font.setBold(bold)
                painter.setFont(font); painter.setPen(QColor(color))
                painter.drawText(QPointF(x, y), text)
            elif kind == 'rect':
                x, y, w, h, radius, fill, stroke, dashed = values
                pen = QPen(QColor(stroke), 1.5)
                if dashed: pen.setStyle(Qt.PenStyle.DashLine)
                painter.setPen(pen); painter.setBrush(QColor(fill))
                painter.drawRoundedRect(QRectF(x, y, w, h), radius, radius)
            elif kind == 'line':
                x1, y1, x2, y2, color, weight = values
                painter.setPen(QPen(QColor(color), weight))
                painter.drawLine(QPointF(x1, y1), QPointF(x2, y2))
            else:
                points, color = values
                painter.setPen(QPen(QColor(color), 2)); painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawPolyline(QPolygonF([QPointF(x, y) for x, y in points]))
        painter.end()
        image.setDevicePixelRatio(scale)
        return image

    def finish(self, height):
        height = int(height + 2)
        for x, y, w, h in self.bounds:
            if x < 0 or y < 0 or x + w > self.width + 1 or y + h > height + 1:
                raise ValueError('Guide illustration text exceeds its measured canvas')
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d">%s</svg>' % (
            self.width, height, self.width, height, ''.join(self.parts))
        return svg, height


def keyboard(d, _):
    keys = [('F12', 'Show Home / return to applications'),
            ('Tab', 'Move to the next control'),
            ('Shift+Tab', 'Move to the previous control'),
            ('Space', 'Activate the focused control'),
            ('Enter', 'Choose No in the power confirmation'),
            ('Esc', 'Cancel the confirmation')]
    y = 1
    for key, meaning in keys:
        h = max(54, d.text_height(meaning, d.width - 184) + 24)
        d.rect(1, y, 150, h, 'blue', 8)
        d.text(15, y + 14, key, 125, 19, 'blue', True)
        d.text(176, y + 12, meaning, d.width - 180)
        y += h + 12
    return y


def wallet(d, _):
    y = d.box(1, 1, d.width - 2, 'GPG backup: protects the whole file',
              'Separate GPG passphrase(s)', 'amber') + 25
    d.text(0, y, 'Inside wallet.dat', d.width, 20, bold=True)
    y = d.pair(y + 40,
        ('Private-key material', 'Locked by the Core passphrase if wallet encryption is enabled.', 'blue'),
        ('Public information', 'Addresses and other metadata may remain readable.', 'ink'))
    return d.footer(y + 12, 'Opening GPG reveals the file. Unlocking Core enables signing.')


def phrases(d, _):
    y = 1
    for count in (6, 8):
        y += d.text(0, y, '%d random words' % count, d.width, 20, 'blue', True) + 12
        columns = min(count, 4)
        gap = 10
        cell = (d.width - (columns - 1) * gap) / columns
        for i in range(count):
            x = (i % columns) * (cell + gap)
            top = y + (i // columns) * 50
            d.rect(x + 1, top, cell - 2, 40, 'blue', 6)
            d.text(x + 12, top + 7, 'word %d' % (i + 1), cell - 22, 18)
        y += ((count + columns - 1) // columns) * 50 + 18
    y = d.pair(y, ('Secret A', 'Generate a fresh phrase.', 'amber'),
                  ('Secret B', 'Generate another fresh phrase.', 'purple'))
    return d.footer(y + 8, 'Placeholders only. Never use this illustration as a passphrase.')


def storage(d, _):
    y = d.pair(1,
        ('RAM • Private session', 'Core wallets\nDecrypted files\nWorking notes and PSBTs', 'blue'),
        ('External media', 'Verified encrypted backups\nExported signed PSBTs\nDeliberately saved documents', 'amber'))
    y += 24
    d.arrow(35, y + 18, d.width - 35, y + 18)
    y += 38
    y += d.text(0, y, 'Export the files you need to keep', d.width, 20, bold=True) + 18
    y = d.pair(y,
        ('Session ends', 'Private RAM files disappear.', 'blue'),
        ('Saved copies remain', 'External files are not removed by Finish.', 'amber'))
    return d.footer(y + 12, 'The internal disk keeps the OS and installed applications.', 'muted')


def media(d, _):
    y = d.pair(1,
        ('Transfer medium', 'Unsigned PSBT in\nSigned PSBT out\nPublic watch-only copy', 'blue'),
        ('Backup medium', 'Verified encrypted .gpg files\nRecovery documents', 'amber'))
    y += 34
    y += d.text(0, y, 'Independent backup copies', d.width, 20, bold=True) + 14
    y = d.pair(y,
        ('Copy 1 • Location A', 'A usable encrypted backup.', 'green'),
        ('Copy 2 • Location B', 'Another usable copy on another device.', 'green'))
    return d.footer(y + 12, 'Label the media and test recovery periodically.')


def optical(d, _):
    y = d.pair(1, ('1  WRITE', 'Burn the encrypted backup to a compatible disc.', 'amber'),
                 ('2  READ BACK', 'Read the actual disc and verify the copied data.', 'green'))
    y += 32
    y = d.pair(y, ('3  STORE • Location A', 'Label and keep the first verified disc.', 'blue'),
                 ('3  STORE • Location B', 'Keep an independent verified copy elsewhere.', 'blue'))
    return d.footer(y + 12, 'A successful write is followed by verification and recovery drills.')


def paper(d, _):
    y = d.box(1, 1, d.width - 2, 'EXAMPLE • Media label',
              'Backup ID: vault-backup-01\nCreated: YYYY-MM-DD\nLast recovery drill: YYYY-MM-DD\nCopy: 1 of 2', 'amber')
    y += 25
    y = y + d.box(1, y, d.width - 2, 'Recovery note • stored separately',
                  '1. Locate a verified backup copy.\n2. Contact the required secret holders.\n3. Follow the recovery and signing checklist.', 'blue')
    return d.footer(y + 12, 'No secrets in this sample. Instructions stay outside the backup.')


def terminal(d, _):
    y = d.box(1, 1, d.width - 2, 'Program', 'gpg — stock GnuPG', 'blue')
    y += 24
    y = d.pair(y, ('Encrypted input', 'wallet.dat.gpg', 'amber'),
                 ('Decrypted output', 'wallet.dat • RAM only', 'blue'))
    y += 30
    y += d.text(0, y, 'Command structure', d.width, 20, bold=True) + 12
    y += d.text(0, y, 'gpg --output wallet.dat --decrypt wallet.dat.gpg', d.width, 18, mono=True)
    return d.footer(y + 14, 'Enter the passphrase at the prompt, never in the command.')


def layers(d, count):
    count = max(1, min(3, int(count)))
    tones = ['blue', 'purple', 'amber']
    for index in range(count - 1, -1, -1):
        depth = count - index - 1
        x = 1 + depth * 18
        y = 1 + depth * 63
        w = d.width - 2 - depth * 36
        height = (index + 1) * 77 + 88
        d.rect(x, y, w, height, tones[index])
        d.text(x + 16, y + 14, 'GPG layer %d  •  Passphrase %s' % (index + 1, chr(65 + index)),
               w - 32, 19, tones[index], True)
    x = 1 + count * 18
    y = 1 + count * 63
    w = d.width - 2 - count * 36
    d.box(x, y, w, 'Original data', 'wallet.dat or a standard TAR', 'ink', height=88)
    end = count * 77 + 112
    required = ' + '.join(chr(65 + i) for i in range(count))
    end = d.footer(end, 'Recovery requires: backup.gpg + ' + required, 'amber')
    return d.footer(end + 2, 'Backup access is not a Bitcoin signing threshold.', 'muted')


def verify(d, _):
    gap = 52
    width = (d.width - gap) / 2
    top = [
        ('1  SNAPSHOT', 'Consistent original data in RAM.', 'blue'),
        ('2  ENCRYPT', 'Create and verify the GPG layers.', 'amber')]
    bottom = [
        ('4  COMPARE', 'Match the recovered package to the original snapshot.', 'green'),
        ('3  RECOVER', 'Authenticate and decrypt every layer in RAM.', 'blue')]
    h1 = max(d.box_height(width, *t[:2]) for t in top)
    h2 = max(d.box_height(width, *t[:2]) for t in bottom)
    for i, t in enumerate(top):
        d.box(1 + i * (width + gap), 1, width - 2, *t[:2], tone=t[2], height=h1)
    d.arrow(width + 7, h1 / 2, width + gap - 7, h1 / 2)
    y = h1 + 45
    d.arrow(d.width - width / 2, h1 + 7, d.width - width / 2, y - 7)
    for i, t in enumerate(bottom):
        d.box(1 + i * (width + gap), y, width - 2, *t[:2], tone=t[2], height=h2)
    d.arrow(width + gap - 7, y + h2 / 2, width + 7, y + h2 / 2)
    return d.footer(y + h2 + 14, 'Then publish a new encrypted file and verify the destination copy.', 'green')


def finish(d, _):
    y = d.box(1, 1, d.width - 2, '1  Save what you need',
              'Export backups and keep required passphrases recoverable. Confirm you have saved them.', 'blue')
    y += 18
    y = d.box(1, y, d.width - 2, '2  Confirm session data loss',
              'Anything kept only in RAM will be lost. Start the five-minute countdown.', 'amber')
    y += 18
    y = d.box(1, y, d.width - 2, '05:00 → 00:00',
              'The session stays open. No passphrase entry or backup check.', 'blue')
    y += 18
    y = d.pair(y,
        ('Cancel countdown', 'Keep working and save anything missing.', 'green'),
        ('Timer ends / Finish now', 'Close Core, clear clipboard, end the RAM session.', 'amber'))
    return d.footer(y + 12, 'External copies remain. Power loss can bypass these warnings.', 'muted')


def psbt(d, _):
    gap = 52
    width = (d.width - gap) / 2
    d.text(0, 1, 'ONLINE', width, 20, 'blue', True)
    d.text(width + gap, 1, 'OFFLINE VAULT', width, 20, 'amber', True)
    y = 43
    left = ('1  Prepare', 'Create an unsigned PSBT.')
    right = ('2  Review', 'Check destination, amount and transaction details.')
    h = max(d.box_height(width, *left), d.box_height(width, *right))
    d.box(1, y, width - 2, *left, tone='blue', height=h)
    d.box(width + gap + 1, y, width - 2, *right, tone='amber', height=h)
    d.arrow(width + 7, y + h / 2, width + gap - 7, y + h / 2)
    end_review = y + h
    y += h + 18
    y += d.text(0, y, 'PSBT files cross by removable media', width, 18, 'muted') + 20
    d.arrow(d.width - width / 2, end_review + 7, d.width - width / 2, y - 7)
    left = ('4  Broadcast', 'Publish the signed transaction from the online coordinator.')
    right = ('3  Sign', 'Sign in Core, then export the signed PSBT.')
    h = max(d.box_height(width, *left), d.box_height(width, *right))
    d.box(1, y, width - 2, *left, tone='blue', height=h)
    d.box(width + gap + 1, y, width - 2, *right, tone='amber', height=h)
    d.arrow(width + gap - 7, y + h / 2, width + 7, y + h / 2)
    return d.footer(y + h + 14, 'The PSBT transfer does not contain private keys.', 'green')


def recovery(d, _):
    y = d.pair(1,
        ('BACKUP FILE', 'Copy 1  OR  Copy 2\nDifferent media / locations', 'green'),
        ('SECRET A', 'Copy A1  OR  Copy A2\nIndependent recovery arrangements', 'blue'))
    y = d.pair(y + 24,
        ('SECRET B', 'Copy B1  OR  Copy B2\nSeparate from group A', 'purple'),
        ('SECRET C', 'Copy C1  OR  Copy C2\nSeparate from groups A and B', 'amber'))
    y = d.footer(y + 12, 'ONE usable backup + A + B + C', 'green')
    return d.footer(y, 'All groups are required. Extra copies protect against loss.', 'muted')


def decrypt(d, _):
    y = d.box(1, 1, d.width - 2, 'Passphrases A, B, C • enter in any order',
              'Vault authenticates the outermost remaining layer first.', 'amber')
    y += 24
    y = d.pair(y,
        ('Encrypted backup', 'backup.gpg\nAll required GPG layers', 'amber'),
        ('Original files in RAM', 'wallet.dat\nnotes.txt\ndocument.gpg', 'blue'))
    return d.footer(y + 12, 'STOP: document.gpg is an original file and stays encrypted.', 'amber')


def pairing(d, _):
    y = d.pair(1,
        ('Offline Vault', 'Private keys stay here.\nReview and sign transactions.', 'amber'),
        ('Online Node', 'Public descriptors only.\nWatch and prepare transactions.', 'blue'))
    y = d.box(1, y + 24, d.width - 2, 'Public watch-only export',
        'Core → Private Workspace → Files → USB', 'blue') + y + 24
    y = d.box(1, y + 24, d.width - 2, 'Compare independently',
        'Receiving addresses + change addresses + next index + network', 'green') + y + 24
    return d.footer(y + 12, 'Public descriptors reveal activity, but cannot authorize spending.', 'muted')


RENDERERS = {name: value for name, value in globals().copy().items()
             if name in ('keyboard', 'wallet', 'phrases', 'storage', 'media', 'optical',
                         'paper', 'terminal', 'layers', 'verify', 'finish', 'psbt',
                         'recovery', 'decrypt', 'pairing')}


def render_visual(section, width, layer_count=1, scale=1.0):
    kind, title, description = VISUALS[section]
    drawing = Drawing(max(490, min(960, int(width))))
    height = RENDERERS[kind](drawing, layer_count)
    svg, height = drawing.finish(height)
    return svg, drawing.width, height, title, description, drawing.paint(height, scale)


def render_comparison(width, scale=1.0):
    """Compare backup access with transaction authorization, not strength scores."""
    d = Drawing(max(490, min(960, int(width))))
    col = (d.width - 28) / 2
    titles = [('GPG backup layers', 'blue'), ('Bitcoin multisig', 'purple')]
    title_height = max(d.text_height(title, col - 8, 20, True) for title, _ in titles)
    for i, (title, tone) in enumerate(titles):
        d.text(i * (col + 28), 1, title, col - 8, 20, tone, True)
    y = title_height + 24
    cell = (col - 16) / 3
    for column, labels, tone in [(0, ('A', 'B', 'C'), 'blue'), (1, ('K1', 'K2', 'K3'), 'purple')]:
        origin = column * (col + 28)
        for i, label in enumerate(labels):
            x = origin + i * (cell + 8)
            d.rect(x + 1, y, cell - 2, 42, tone, 8)
            d.text(x + 12, y + 9, label, cell - 20, 18, tone, True)
    y += 62
    notes = [('ALL external secrets', 'blue'), ('Example: ANY 2 of 3 keys', 'purple')]
    h = max(d.text_height(text, col - 8) for text, _ in notes)
    for i, (text, tone) in enumerate(notes):
        d.text(i * (col + 28), y, text, col - 8, 18, tone, True)
        d.arrow(i * (col + 28) + col / 2, y + h + 8,
                i * (col + 28) + col / 2, y + h + 36, tone)
    y += h + 48
    boxes = [('Open the backup', 'Recover the wallet file. Its Bitcoin signing rules stay the same.', 'blue'),
             ('Authorize spending', 'The Bitcoin script requires the signing threshold for a transaction.', 'purple')]
    h = max(d.box_height(col - 2, *t[:2]) for t in boxes)
    for i, t in enumerate(boxes):
        d.box(i * (col + 28) + 1, y, col - 2, *t[:2], tone=t[2], height=h)
    height = d.footer(y + h + 12, 'Different controls: access to a backup and authorization to spend.', 'muted')
    svg, height = d.finish(height)
    description = ('GPG layers require all external secrets to open a backup; the recovered wallet keeps its existing Bitcoin signing rules. '
                   'In the separate 2-of-3 multisig example, any two of three independent Bitcoin keys authorize a transaction.')
    return svg, d.width, height, description, d.paint(height, scale)
