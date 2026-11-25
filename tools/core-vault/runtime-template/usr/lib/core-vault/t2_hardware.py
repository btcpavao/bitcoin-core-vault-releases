"""Identify Intel Macs with Apple's T2 using the same exact list as GRUB.

The live command-line marker is diagnostic only. Installer decisions read the
actual DMI values again, including when this module is used from the target.
"""
import json
from pathlib import Path

MODELS_FILE = Path("/usr/share/core-vault/t2-models.json")
DMI_DIRECTORY = Path("/sys/class/dmi/id")


def _dmi_value(name):
    try:
        with (DMI_DIRECTORY / name).open("rb") as source:
            data = source.read(257)
        if len(data) > 256:
            return None
        return data.decode("ascii").strip()
    except (OSError, UnicodeError):
        return None


def detect_t2():
    """Return the exact supported T2 model, or None on other/unreadable hardware."""
    manufacturer = _dmi_value("sys_vendor")
    model = _dmi_value("product_name")
    if not manufacturer or not model:
        return None
    with MODELS_FILE.open("rb") as source:
        raw = source.read(16385)
    if len(raw) > 16384:
        raise ValueError("The T2 hardware model list is too large.")
    data = json.loads(raw)
    if (data.get("schema") != 1
            or not isinstance(data.get("manufacturers"), list)
            or not isinstance(data.get("models"), list)
            or not all(isinstance(x, str) and x for x in
                       data["manufacturers"] + data["models"])):
        raise ValueError("The T2 hardware model list is invalid.")
    if manufacturer in data["manufacturers"] and model in data["models"]:
        return model
    return None
