import os
import sys

# Open a new main window in a separate process from the file menu
def open_new_ifc_viewer(file_path=None):
    if getattr(sys, 'frozen', False):
        # We're in a compiled binary, use our own executable
        target = os.path.join(os.path.dirname(sys.executable), "IFCViewer.exe")
        if file_path:
            args = [str(target), str(file_path)]
        else:
            args = [str(target)]
        os.spawnv(os.P_DETACH, target, args)
    else:
        # We're running as a .py file, launch it with Python
        target = os.path.abspath("IFCViewer.py")
        if file_path:
            args = [str(sys.executable), str(target), str(file_path)]
        else:
            args = [str(sys.executable), str(target)]
        os.spawnv(os.P_DETACH, sys.executable, args)