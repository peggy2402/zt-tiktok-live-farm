import os
from PyQt6.QtGui import QIcon

# This script assumes it is located in the 'ui' directory.
# It builds an absolute path to the 'assets' directory.
try:
    # Get the directory of the current script (ui/resources.py)
    _UI_DIR = os.path.dirname(__file__)
    # Go one level up to the project root, then into the 'assets' directory
    ASSETS_DIR = os.path.abspath(os.path.join(_UI_DIR, '..', 'assets'))
except NameError:
    # Fallback for environments where __file__ is not defined
    ASSETS_DIR = os.path.abspath(os.path.join(os.getcwd(), 'assets'))

ICON_CACHE = {}

def get_icon(name: str) -> QIcon:
    """
    Loads a QIcon from the assets directory.
    Caches icons for better performance.
    Returns an empty QIcon if the file doesn't exist.
    """
    if name in ICON_CACHE:
        return ICON_CACHE[name]

    path = os.path.join(ASSETS_DIR, name)
    if os.path.exists(path):
        icon = QIcon(path)
        ICON_CACHE[name] = icon
        return icon
    else:
        print(f"[UI WARNING] Icon not found: {path}")
        # Cache the empty icon to avoid repeated lookups and warnings
        ICON_CACHE[name] = QIcon()
        return ICON_CACHE[name]
