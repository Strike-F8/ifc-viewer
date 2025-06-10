import os
import json
import ifcopenshell

from collections import defaultdict
from collections.abc import Iterable

from PySide6.QtWidgets import (
    QTableView, QHeaderView, QMainWindow, QWidget, QVBoxLayout, QApplication, QMessageBox,
    QAbstractItemView, QFileDialog, QHBoxLayout, QComboBox, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, Slot, QTimer

from ui import TLabel, TPushButton, TCheckBox, TAction
from strings import (
    A_STATUS_LABEL_KEY, A_OUTPUT_PATH_LABEL_KEY, A_OUTPUT_BROWSE_KEY, A_EXPORTER_CHECKBOX_KEYS,
    A_EXPORT_BUTTON_KEY, CONTEXT_MENU_ACTION_KEYS, A_EXPORTING_KEYS, A_EXPORTER_VERSION_LABEL_KEY
)

from .export_worker import ExportWorker
from .utils import open_new_ifc_viewer
from export_utils import *
from options import CONFIG_PATH

class ExporterWindow(QMainWindow):
    def __init__(self, ifc_model, title=None, parent=None, export_type="Assembly"):
        super().__init__(parent)

        self.resize(600, 600)

        self.ifc_model = ifc_model
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        # "Select the assemblies to be exported"
        self.status_label = TLabel(A_STATUS_LABEL_KEY, context="Exporter Status Label")
        self.status_label.setWordWrap(True)

        self.add_assembly_export_button()
        self.add_file_layout()

        layout.addLayout(self.file_layout)
        self.add_settings()
        layout.addLayout(self.settings_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.assembly_export_button)

        # Table View
        self.assembly_table = QTableView()
        self.model = ExporterTableModel(assemblies=self.find_assemblies())
        self.assembly_table.setModel(self.model)

        self.title = title
        if self.title:
            self.setWindowTitle(f"{self.model.rowCount()} {export_type}(s) found in {self.title}")
        else:
            self.setWindowTitle("Exporter")

        self.assembly_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assembly_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.assembly_table.setSortingEnabled(True)
        self.assembly_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.assembly_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.assembly_table.customContextMenuRequested.connect(lambda pos, v=self.assembly_table: self.show_context_menu(pos, v))

        for i in range(4):
            self.assembly_table.setColumnWidth(i, 150)

        layout.addWidget(self.assembly_table)
        self.setCentralWidget(central_widget)

        # Loading spinner
        self.spinner_frames = ["|", "/", "-", "\\"]
        self.current_frame = 0

        # Set a timer to update the spinning animation while exporting
        self.spinner_timer = QTimer()
        self.spinner_timer.setInterval(100)
        self.spinner_timer.timeout.connect(self.update_spinner)

    def load_recent_paths(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    data = json.load(f)
                    return data.get("recent_exported_files", ["IFC-Exporter.ifc"])
            except Exception:
                return ["IFC-Exporter.ifc"]
        return ["IFC-Exporter.ifc"]

    def add_assembly_export_button(self):
        # "Export"
        self.assembly_export_button = TPushButton(A_EXPORT_BUTTON_KEY, self, context="Output Path Selector")
        self.assembly_export_button.clicked.connect(self.export_button_clicked)

    def add_file_layout(self):
        self.recent_paths = self.load_recent_paths()

        file_layout = QHBoxLayout()

        # "Output Path:"
        self.file_path_label = TLabel(A_OUTPUT_PATH_LABEL_KEY, self, context="Output Path Selector")
        self.file_path_combo = QComboBox(self)
        self.file_path_combo.setEditable(True)
        self.file_path_combo.addItems(self.recent_paths)
        self.file_path_combo.setCurrentText(self.recent_paths[0])
        self.file_path_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.browse_button = TPushButton(A_OUTPUT_BROWSE_KEY, self, context="Output Path Selector")
        self.browse_button.clicked.connect(self.browse_export_path)
    
        file_layout.addWidget(self.file_path_label)
        file_layout.addWidget(self.file_path_combo)
        file_layout.addWidget(self.browse_button)

        self.file_layout = file_layout
    
    def add_settings(self):
        self.settings_layout = QVBoxLayout()
        self.add_toggles()
        self.add_version_selector()

    def add_toggles(self):
        # "Draw Graph"TODO: Improve graph support before enabling again
        # self.graph_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[0], self, context="Exporter Settings")
        # self.graph_toggle_checkbox.setChecked(False)

        # "Export Grids"
        self.grid_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[1], self, context="Exporter Settings")
        self.grid_toggle_checkbox.setChecked(False)

        # "Preserve original STEP IDs (BUGGY!)"
        self.preserve_id_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[2], self, context="Exporter Settings")
        self.preserve_id_toggle_checkbox.setChecked(False)

        # Open Exported File
        self.open_file_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[3], self, context="Exporter Settings")
        self.open_file_toggle_checkbox.setChecked(False)
        self.open_file_toggle_checkbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.toggle_layout = QHBoxLayout()
        #self.toggle_layout.addWidget(self.graph_toggle_checkbox)
        self.toggle_layout.addWidget(self.grid_toggle_checkbox) 
        self.toggle_layout.addWidget(self.preserve_id_toggle_checkbox)
        self.toggle_layout.addWidget(self.open_file_toggle_checkbox)

        self.settings_layout.addLayout(self.toggle_layout)

    def add_version_selector(self):
        # "IFC Version: "
        version_label = TLabel(A_EXPORTER_VERSION_LABEL_KEY, self, context="Exporter Settings")
        self.version_combo = QComboBox()

        version_layout = QHBoxLayout()
        version_layout.addWidget(version_label)
        version_layout.addWidget(self.version_combo)

        self.supported_schemas = [
            "IFC2X3", "IFC4", "IFC4X3",
        ]

        self.version_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.version_combo.addItems(self.supported_schemas)
        self.version_combo.setCurrentText(self.ifc_model.schema)
        self.settings_layout.addLayout(version_layout)

    def browse_export_path(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "Select destination file",
            self.file_path_combo.currentText(),
            "IFC Files (*.ifc);;All Files(*)"
        )
        if path:
            self.update_recent_paths(path)
    
    def update_recent_paths(self, new_path):
        if new_path in self.recent_paths:
            self.recent_paths.remove(new_path) # We want to keep this path but move it to the top

        self.recent_paths.insert(0, new_path) # Insert at top
        self.recent_paths = self.recent_paths[:10] # Keep the 10 most recent paths
        
        self.file_path_combo.clear()
        self.file_path_combo.addItems(self.recent_paths)
        self.file_path_combo.setCurrentText(new_path)

        # Save the recent paths to a file
        self.save_recent_paths()

    def save_recent_paths(self):
        try:
            with open(CONFIG_PATH, 'r') as f:
                data = json.load(f)

            data["recent_exported_files"] = self.recent_paths

            with open(CONFIG_PATH, 'w') as f:
                json.dump(data, f)

        except Exception as e:
            print("Error saving config:", e)

    def show_context_menu(self, position, view):
        index = view.indexAt(position)
        if not index.isValid():
            print(f"Context menu requested at invalid index {index}")
            return

        step_id = index.sibling(index.row(), 0).data()  # column 0 = "STEP ID"
        entity = self.ifc_model.by_id(int(step_id[1:])) # Get the entity selected by the user
        print(f"Showing context menu for {entity}\nat index {index}")

        if not entity:
            print(f"Context menu requested for invalid entity at index {index}")
        
        menu = QMenu()

        # A list of functions triggered by the buttons in the context menu
        context_menu_actions = [
            self.copy_step_line,
            self.copy_step_id,
            self.copy_guid,
            self.copy_row_text
        ]

        translator_context = "Entity Views Context Menu"
        for label, handler in zip(
            CONTEXT_MENU_ACTION_KEYS,
            context_menu_actions
        ): # Not every entity has a GUID so skip
            if "step" in label.lower(): # If the step id is needed, pass it in as an argument
                action = TAction(label, self, context=translator_context, triggered=handler, triggered_args=entity, format_args={"id": entity.id()})
            elif "GUID" in label: # If the GUID is needed, pass it in as an argument
                try:
                    action = TAction(label, self, context=translator_context, triggered=handler, triggered_args=entity, format_args={"guid": entity.GlobalId})
                except: # Not every entity has a GUID so skip
                    continue
            else: # No arguments needed
                action = TAction(label, self, context=translator_context, triggered=handler, triggered_args=(view, index.row()))

            menu.addAction(action)

        # Show the context menu
        menu.exec(view.viewport().mapToGlobal(position))
        
    def copy_step_line(self, entity):
        QApplication.clipboard().setText(str(entity))

    def copy_step_id(self, entity):
        QApplication.clipboard().setText('#' + str(entity.id()))

    def copy_guid(self, entity):
        QApplication.clipboard().setText(str(entity.GlobalId))

    def copy_row_text(self, view, row):
        model = view.model()
        column_count = model.columnCount()
        row_text = []

        for col in range(column_count):
            index = model.index(row, col)
            text = model.data(index, Qt.DisplayRole)
            if text:
                row_text.append(str(text))

        QApplication.clipboard().setText("\t".join(row_text))

    def export_button_clicked(self):
        if not self.spinner_timer.isActive():
            self.spinner_timer.start()
            # Add current file path to recent files
            export_path = self.file_path_combo.currentText()
            selected_rows = self.assembly_table.selectionModel().selectedRows()
            self.update_recent_paths(export_path)

            # "Exporting {entity_count} {entity_type}(s) to {file_path}"
            self.status_label.setText(A_EXPORTING_KEYS[0],
                                      format_args={"entity_count": len(selected_rows),
                                                   "entity_type": "IfcElementAssembly", # TODO: Display the user provided type
                                                   "file_path": export_path})
            # start export
            self.entities_to_export = [
                self.model.data(index, Qt.UserRole)
                for index in selected_rows
                if self.model.data(index, Qt.UserRole)
            ]

            self.export_worker = ExportWorker(self.entities_to_export, export_path,
                                        self.ifc_model, self.grid_toggle_checkbox.isChecked(),
                                        self.preserve_id_toggle_checkbox.isChecked())

            self.export_worker.progress.connect(self.update_export_progress)
            self.export_worker.finished.connect(self.export_finished)
            self.export_worker.start()

    @Slot(int)
    def update_export_progress(self, progress):
        # TODO: Display the progress somewhere (progress bar?)
        print(f"Export progress: {progress}")
        pass

    @Slot()
    def update_spinner(self):
        frame = self.spinner_frames[self.current_frame % len(self.spinner_frames)]
        current_text = self.status_label.text()

        if current_text[0] in self.spinner_frames:
            new_text = frame + current_text[1:]
        else:
            new_text = frame + current_text

        self.status_label.setText(new_text) # To prevent overriding the translated text
                                            # Only update the spinner
        self.current_frame += 1
 
    
    @Slot(list)
    def export_finished(self, results):
        # Optionally, display the selected assemblies in a graph
        # self.draw_graph() 

        export_path = results[0]

        # "Exported {entity_count} {entity_type}(s) to {file_path}"
        self.status_label.setText(A_EXPORTING_KEYS[1],
                    format_args={"entity_count": str(len(self.entities_to_export)),
                                "entity_type": "Assembly", # TODO: Display the user provided type
                                "file_path": export_path})

        # Convert results if necessary
        new_version = self.version_combo.currentText()
        if new_version != self.ifc_model.schema:
            new_path = os.path.splitext(export_path)[0]+"(CONVERTED).ifc"
            conversion_failed = convert_schema_to(export_path,
                                new_path, new_version)
            if conversion_failed:
                QMessageBox.critical(self, "Error", f"Conversion Failed")

            if self.open_file_toggle_checkbox.isChecked():
                open_new_ifc_viewer(new_path)
        else:
            if self.open_file_toggle_checkbox.isChecked():
                open_new_ifc_viewer(export_path)

        self.spinner_timer.stop()
    
