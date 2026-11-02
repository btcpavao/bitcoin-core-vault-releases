#!/usr/bin/python3
import json,os,sys
assert os.environ.get("CORE_VAULT_ISOLATED_GUI_TEST")=="1"
from pathlib import Path
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication,QWidget,QVBoxLayout,QLineEdit
out=Path(sys.argv[1]);app=QApplication(['keyboard-foreign-editor']);app.setStyle('Fusion');w=QWidget();w.setWindowTitle('Keyboard Foreign Editor');w.resize(440,180);layout=QVBoxLayout(w);edit=QLineEdit();layout.addWidget(edit);w.show()
def report():
 temp=out.with_suffix('.tmp');temp.write_text(json.dumps({'window':int(w.winId()),'text':edit.text(),'active':w.isActiveWindow(),'input_focus':edit.hasFocus()}));temp.replace(out)
edit.textChanged.connect(report);timer=QTimer();timer.setInterval(70);timer.timeout.connect(report);timer.start();report();sys.exit(app.exec())
