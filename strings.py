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
    q.translate("TAction", "Load a new IFC file")
    q.translate("TAction", "Display the IFC file contents")
    q.translate("TAction", "Export assemblies to a new IFC file")
    q.translate("TAction", "Open the options window")
    
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
    q.translate("TAction", "Copy Step Line #{id}")
    q.translate("TAction", "Copy Step ID #{id}")
    q.translate("TAction", "Copy GUID {guid}")
    q.translate("TAction", "Copy This Row")