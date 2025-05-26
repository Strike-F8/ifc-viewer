from PySide6.QtCore import QCoreApplication as q

# ==============================
# MAIN TOOLBAR
# ==============================

MAIN_TOOLBAR_ACTION_KEYS = [
    "Open File",
    "Load Entities",
    "Assembly Exporter",
    "Options"
]
MAIN_TOOLBAR_TOOLTIP_KEYS = [
    "Load a new IFC file",
    "Display the IFC file contents",
    "Export assemblies to a new IFC file",
    "Open the options window"
]

# This function is never imported nor called
# It only serves to supply markers for lupdate to pick up the strings
def mark_toolbar_translations():
    # Toolbar actions
    q.translate("TAction", "Open File")
    q.translate("TAction", "Load Entities")
    q.translate("TAction", "Assembly Exporter")
    q.translate("TAction", "Options")

    # Toolbar Tooltips
    q.translate("Main Toolbar", "Load a new IFC file")
    q.translate("Main Toolbar", "Display the IFC file contents")
    q.translate("Main Toolbar", "Export assemblies to a new IFC file")
    q.translate("Main Toolbar", "Open the options window")
    
# ==============================
# CONTEXT MENU
# ==============================

CONTEXT_MENU_ACTION_KEYS = [
    "Copy Step Line #{id}",
    "Copy Step ID #{id}",
    "Copy GUID {guid}",
    "Copy This Row"
]

# This function is never imported nor called
# It only serves to supply markers for lupdate to pick up the strings
def mark_context_menu_translations():
    q.translate("Entity Views Context Menu", "Copy Step Line #{id}")
    q.translate("Entity Views Context Menu", "Copy Step ID #{id}")
    q.translate("Entity Views Context Menu", "Copy GUID {guid}")
    q.translate("Entity Views Context Menu", "Copy This Row")

# ==============================
# FILE MENU
# ==============================

FILE_MENU_KEY = "File"

FILE_MENU_ACTION_KEYS = [
    "Open",
    "New Window",
    "Recent Files"
]

RECENT_FILES_MENU_KEY = "Recent Files"

def mark_file_menu_translations():
    q.translate("Main File Menu", "File")
    q.translate("Main File Menu", "Open")
    q.translate("Main File Menu", "New Window")
    q.translate("Main File Menu", "Recent Files")