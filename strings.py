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
    q.translate("Main Toolbar", "Open File")
    q.translate("Main Toolbar", "Load Entities")
    q.translate("Main Toolbar", "Assembly Exporter")
    q.translate("Main Toolbar", "Options")

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
# MAIN FILE MENU
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

# ==============================
# MAIN STATUS LABEL
# ==============================

MAIN_STATUS_LABEL_KEYS = [
    "＜ーChoose an IFC file to open",
    "Now loading: {file_path}",
    "Now loading IFC model into view",
    "Finished loading {file_path}",
    "Loaded {file_path}\nPress the \"Load Entities\" button to view the contents",
    "Selected entity #{id}"
]

def mark_main_status_label_keys():
    q.translate("Main Status Label", "＜ーChoose an IFC file to open")
    q.translate("Main Status Label", "Now loading: {file_path}")
    q.translate("Main Status Label", "Now loading IFC model into view")
    q.translate("Main Status Label", "Finished loading {file_path}")
    q.translate("Main Status Label", "Loaded {file_path}\nPress the \"Load Entities\" button to view the contents")
    q.translate("Main Status Label", "Selected entity #{id}")

# ==============================
# FILTER WIDGET
# ==============================

FILTER_WIDGET_KEYS = [
    "Filter Entities...", # Filter input text box
    "Filter"              # Filter apply button
]

def mark_filter_widget_keys():
    q.translate("Filter Widget", "Filter Entities...")
    q.translate("Filter Widget", "Filter")

# ==============================
# ROW COUNT
# ==============================

ROW_COUNT_KEY      = "{items} rows"
BUILDING_INDEX_KEY = "Building index for filtering. Please Wait..."

def mark_row_count_key():
    q.translate("Row Count", "{items} rows")
    q.translate("Row Count", "Building index for filtering. Please Wait...")

# ======================================
# ASSEMBLY EXPORTER
# ======================================
# ==============================
# STATUS LABEL
# ==============================

A_STATUS_LABEL_KEY = "Select the assemblies to be exported"
A_EXPORTING_KEYS = [
    "Exporting {entity_count} {entity_type}(s) to {file_path}",
    "Exported {entity_count} {entity_type}(s) to {file_path}"
]

def mark_a_status_label_key():
    q.translate("Assembly Status Label", "Select the assemblies to be exported")
    q.translate("Assembly Status Label", "Exporting {entity_count} {entity_type}(s) to {file_path}")
    q.translate("Assembly Status Label", "Exported {entity_count} {entity_type}(s) to {file_path}")

# ==============================
# OUTPUT PATH SELECTOR
# ==============================

A_OUTPUT_PATH_LABEL_KEY = "Output Path:"
A_OUTPUT_BROWSE_KEY     = "Browse..."
A_EXPORT_BUTTON_KEY     = "Export"

def mark_output_path_keys():
    q.translate("Output Path Selector", "Output Path:")
    q.translate("Output Path Selector", "Browse...")
    q.translate("Output Path Selector", "Export")

# ==============================
# EXPORTER SETTINGS
# ==============================

A_EXPORTER_CHECKBOX_KEYS = [
    "Draw Graph",
    "Export Grids",
    "Preserve original STEP IDs (BUGGY!)",
    "Open Exported File"
]

A_EXPORTER_VERSION_LABEL_KEY = "IFC Version: "

def mark_exporter_settings_keys():
    q.translate("Exporter Settings", "Draw Graph")
    q.translate("Exporter Settings", "Export Grids")
    q.translate("Exporter Settings", "Preserve original STEP IDs (BUGGY!)")
    q.translate("Exporter Settings", "Open Exported File")
    q.translate("Exporter Settings", "IFC Version: ")

# ==============================
# STATS PANEL
# ==============================

STATS_PANEL_KEYS = [
    "IFC Version: {version}",
    "Entity Count: {count}",
    "Loaded in {time}s",
    "Total Entity Types: {count}"
]

def mark_stats_panel_keys():
    q.translate("Stats Panel", "IFC Version: {version}")
    q.translate("Stats Panel", "Entity Count: {count}")
    q.translate("Stats Panel", "Loaded in {time}s")
    q.translate("Stats Panel", "Total Entity Types: {count}")