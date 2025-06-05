# Open a new window in a separate process from the file menu
def open_new_window():
    if getattr(sys, 'frozen', False):
        # We're in a compiled binary, use our own executable
        target = os.path.join(os.path.dirname(sys.executable), "IFCViewer.exe")
        args = [target]
        os.spawnv(os.P_DETACH, target, args)
    else:
        # We're running as a .py file, launch it with Python
        target = os.path.abspath("IFCViewer.py")
        args = [sys.executable, target]
        os.spawnv(os.P_DETACH, sys.executable, args)

import sys
import os
import json
import ifcopenshell

from exporter.assembly_viewer import AssemblyViewerWindow
from db              import DBWorker, SqlEntityTableModel
from options         import OptionsDialog

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QTableView, QHBoxLayout, QVBoxLayout, QWidget,
    QToolBar, QMessageBox, QFileDialog, QMenu, QSplitter, QAbstractItemView, QHeaderView,
    QProgressBar, QStackedLayout, QSizePolicy
)
from PySide6.QtGui  import QAction, QStandardItemModel, QStandardItem, QFont, QFontDatabase
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QTranslator

# Translation imports
from ui import (language_manager,
    TAction, TLabel, TPushButton, TLineEdit
)

from strings import (
    MAIN_TOOLBAR_ACTION_KEYS, MAIN_TOOLBAR_TOOLTIP_KEYS, CONTEXT_MENU_ACTION_KEYS,
    FILE_MENU_ACTION_KEYS, FILE_MENU_KEY, RECENT_FILES_MENU_KEY, MAIN_STATUS_LABEL_KEYS, ROW_COUNT_KEY,
    BUILDING_INDEX_KEY, FILTER_WIDGET_KEYS
)

from options import CONFIG_PATH
                                                
# TODO: Clearer labels for the main 3 views for ease of use

# This simple worker takes in a line from the main thread and executes it in the background
# It is used to execute ifcopenshell.open(file)
# Large files can take some time to open so open them in the background and show a spinner in the meantime
class SimpleIFCWorker(QThread):
    progress = Signal(int)
    finished = Signal(object)
    def __init__(self, task_fn):
        super().__init__()
        self.task_fn = task_fn

    def run(self):
        result = self.task_fn()
        self.finished.emit(result)
   
# Main window consisting of three main views
# The middle view connects to an SQLite database and displays entities from the IFC file
# The left view shows entities referencing the currently selected entity
# The right view shows entities referenced by the currently selected entity
class IfcViewer(QMainWindow):
    def __init__(self, ifc_file=None):
        super().__init__()
        self.translator = None # QTranslator: Allows the ui to be translated on demand
        language_manager.language_changed.connect(self.change_language) # Connect to the language manager in ui.py

        self.setWindowTitle("IFC Viewer")
        self.file_path = ifc_file

        # If an IFC file has already been provided, load it into memory
        if ifc_file:
            self.ifc_model = self.load_ifc(self.file_path)
        else:
            self.ifc_model = None

        self.max_recent_files = 10
        self.recent_files = self.load_recent_files()

        self.middle_model = None # Set this up later when the ifc file is loaded
        self.row_count = 0 # Count the number of rows displayed in the middle view
        self.middle_view = QTableView()
        self.middle_view.setSelectionBehavior(QAbstractItemView.SelectRows) # Select rows instead of cells
        self.middle_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.middle_view.setSortingEnabled(True) # Enable sort requests. However, the model, not the view, will handle the sort
        self.middle_view.verticalHeader().setDefaultSectionSize(20)
        self.middle_view.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.middle_view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        self.middle_view.setWordWrap(False)

        for i in range(4):
            self.middle_view.setColumnWidth(i, 100)
            
        self.middle_view.horizontalHeader().setStretchLastSection(True)
        self.middle_view.verticalHeader().setVisible(False)
        self.middle_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.middle_view.customContextMenuRequested.connect(lambda pos, v=self.middle_view: self.show_context_menu(pos, v))

        self.left_view = QTreeView()
        self.left_model = QStandardItemModel()
        self.left_model.setHorizontalHeaderLabels(['References -> Entity'])
        self.left_view.setModel(self.left_model)
        self.left_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.left_view.customContextMenuRequested.connect(lambda pos, v=self.left_view: self.show_context_menu(pos, v))

        self.right_view = QTreeView()
        self.right_model = QStandardItemModel()
        self.right_model.setHorizontalHeaderLabels(['Entity <- Referenced By'])
        self.right_view.setModel(self.right_model)
        self.right_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.right_view.customContextMenuRequested.connect(lambda pos, v=self.right_view: self.show_context_menu(pos, v))

        self.add_toolbar()
        self.add_status_label()
        self.add_file_menu()
        self.add_filter_bar()
        self.add_filter_button()
        self.add_count_and_progress_bar()

        # Lazy load children upon expanding a root item
        self.left_view.expanded.connect(self.lazy_load_inverse_references)
        self.right_view.expanded.connect(self.lazy_load_forward_references)

        # Update the views when selecting an item in the middle or left views
        self.left_view.selectionModel().currentChanged.connect(self.handle_entity_selection)

        # The three main views
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_view)
        splitter.addWidget(self.middle_view)
        splitter.addWidget(self.right_view)

        center_layout = QVBoxLayout()
        search_layout = QHBoxLayout()
        search_layout.addWidget(self.filter_bar)
        search_layout.addWidget(self.filter_button)
        center_layout.addWidget(self.status_label)
        center_layout.addLayout(search_layout)
        center_layout.addWidget(splitter)
        center_layout.addWidget(self.row_count_bar_stack_widget)

        container = QWidget()
        container.setLayout(center_layout)
        self.setCentralWidget(container)

        # prevent autoscrolling when clicking on an item
        self.middle_view.setAutoScroll(False)
        self.middle_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.middle_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        # Loading spinner
        self.spinner_frames = ["|", "/", "-", "\\"]
        self.current_frame = 0
        
        # Update the spinner every 100ms
        self.spinner_timer = QTimer()
        self.spinner_timer.setInterval(100)
        self.spinner_timer.timeout.connect(self.update_spinner)

    def add_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.LeftToolBarArea, toolbar)

        # A list functions triggered by buttons in the toolbar
        # Order must match the order of strings imported from strings.py
        main_toolbar_actions = [self.open_ifc_file,
            self.start_load_db_task,
            self.show_assemblies_window,
            self.show_options_window
        ]

        for label, tooltip, handler in zip(
            MAIN_TOOLBAR_ACTION_KEYS,
            MAIN_TOOLBAR_TOOLTIP_KEYS,
            main_toolbar_actions
        ):
            toolbar.addAction(TAction(label, self, context="Main Toolbar", tooltip=tooltip, triggered=handler))

    def add_status_label(self):
        # ＜ーChoose an IFC file to open
        self.status_label = TLabel(MAIN_STATUS_LABEL_KEYS[0], parent=self, context="Main Status Label")
        self.status_label.setMinimumHeight(20)
        self.status_label.setMaximumHeight(40)

    def add_file_menu(self):
        self.menubar = self.menuBar()
        file_menu = self.menubar.addMenu(FILE_MENU_KEY)

        file_menu_actions = [
            self.open_ifc_file, open_new_window
        ]

        for label, handler in zip(
            FILE_MENU_ACTION_KEYS,
            file_menu_actions
        ):
            file_menu.addAction(TAction(label, self, context="Main File Menu", triggered=handler))

        self.recent_menu = QMenu(RECENT_FILES_MENU_KEY, self)
        file_menu.addMenu(self.recent_menu)
        self.update_recent_files_menu()

    def add_filter_bar(self):
        # "Filter Entities..."
        self.filter_bar = TLineEdit(FILTER_WIDGET_KEYS[0], self, context="Filter Widget")
        self.filter_bar.textChanged.connect(self.apply_filter)
    
    def add_filter_button(self):
        # But maybe it should stay for user satisfaction
        # "Filter"
        self.filter_button = TPushButton(FILTER_WIDGET_KEYS[1], self, context="Filter Widget")
        self.filter_button.clicked.connect(self.apply_filter)

    def apply_filter(self):
        filter_term = self.filter_bar.text()
        self.middle_model.set_filter(filter_term)

    def add_count_and_progress_bar(self):
        self.row_count_bar_stack_widget = QWidget()
        self.row_count_bar_stack_widget.setMaximumHeight(25)
        # TODO: This is supposed to expand the widget only when necessary but it does not seem to do so
        self.row_count_bar_stack_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.row_count_bar_stack = QStackedLayout(self.row_count_bar_stack_widget)
        self.row_count_bar_stack.setAlignment(Qt.AlignCenter)

        self.row_count_label = TLabel(ROW_COUNT_KEY, context="Row Count", format_args={"items": self.row_count})
        self.row_count_label.setAlignment(Qt.AlignCenter)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet("QProgressBar { background: transparent; }")

        self.row_count_bar_stack.addWidget(self.row_count_label)
        self.row_count_bar_stack.addWidget(self.progress_bar)

        # Add the wrapped widget to the main layout
        self.row_count_bar_stack_widget.raise_()  # If needed to ensure z-order
        
    # When clicking on an entity in either of the three views, show a context menu that allows the user to copy
    # the original step line of the entity
    def show_context_menu(self, position, view):
        index = view.indexAt(position)
        if not index.isValid():
            return

        entity = None

        if view == self.middle_view:
            # Get the selected entity
            step_id = index.sibling(index.row(), 0).data()  # column 0 = "STEP ID"
            entity = self.ifc_model.by_id(int(step_id[1:])) # Get the entity selected by the user
        else:
            # Get the selected entity
            entity = view.model().itemFromIndex(index).data()

        if not entity:
            return
        
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
 
    def load_ifc(self, file_path):
        self.setWindowTitle(os.path.basename(file_path))
        self.file_path = file_path
        self.start_load_ifc_task(file_path)
   
    def start_load_ifc_task(self, file_path):
        if os.path.exists(file_path):
            self.load_ifc_worker = SimpleIFCWorker(task_fn=lambda: ifcopenshell.open(file_path))
        else:
            QMessageBox.critical(self, "Error", f"{file_path}\nnot found!")
            return
            
        # f"Now loading: {os.path.basename(file_path)}"
        self.status_label.setText(MAIN_STATUS_LABEL_KEYS[1], format_args={"file_path": os.path.basename(file_path)})
        self.spinner_timer.start()

        self.load_ifc_worker.progress.connect(self.update_spinner)
        self.load_ifc_worker.finished.connect(self.ifc_file_loaded)
        self.load_ifc_worker.start()
    
    def start_load_db_task(self):
        if not self.spinner_timer.isActive():
            # "Now loading IFC model into view"
            self.status_label.setText(MAIN_STATUS_LABEL_KEYS[2])
            self.spinner_timer.start()

            self.middle_model = None

            self.load_db_worker = DBWorker(self.ifc_model)
            self.load_db_worker.progress.connect(self.update_spinner)
            self.load_db_worker.progress.connect(self.update_progress_bar)
            self.load_db_worker.finished.connect(self.load_db_finished)
            self.load_db_worker.start()

            # Display progress bar
            self.row_count_bar_stack.setCurrentWidget(self.progress_bar)
            self.row_count_label.hide()
            self.progress_bar.show()
            self.progress_bar.setValue(0)

    def update_row_count(self):
        self.row_count = self.middle_model.rowCount()
        self.row_count_label.setText(ROW_COUNT_KEY, format_args={"items": self.row_count})

    @Slot(str)
    def load_db_finished(self, db_uri):
        self.spinner_timer.stop()
        # f"Finished loading {os.path.basename(self.file_path)}"
        self.status_label.setText(MAIN_STATUS_LABEL_KEYS[3], format_args={"file_path": os.path.basename(self.file_path)})

        self.middle_model = SqlEntityTableModel(self.ifc_model, self.file_path, db_path=db_uri)
        self.middle_view.setModel(self.middle_model)
        self.middle_model.row_count_changed.connect(self.update_row_count)
        self.update_row_count()
        self.middle_view.selectionModel().currentChanged.connect(self.handle_entity_selection)

        # Hide progress bar
        self.progress_bar.hide()
        self.row_count_label.show()
        self.row_count_bar_stack.setCurrentWidget(self.row_count_label)
   
    @Slot()
    def update_spinner(self):
        # TODO: Instead of a spinner, animate the text
        frame = self.spinner_frames[self.current_frame % len(self.spinner_frames)]
        current_text = self.status_label.text()

        if current_text[0] in self.spinner_frames:
            new_text = frame + current_text[1:]
        else:
            new_text = frame + current_text

        self.status_label.setText(new_text) # To prevent overriding the translated text
                                            # Only update the spinner
        self.current_frame += 1
    
    def update_progress_bar(self, percent):
        self.progress_bar.setValue(percent)
        if percent >= 99:
            self.progress_bar.hide()
            self.row_count_label.show()
            self.row_count_bar_stack.setCurrentWidget(self.row_count_label)
            self.row_count_label.setText(BUILDING_INDEX_KEY)
    
    @Slot(object)
    def ifc_file_loaded(self, result):
        self.spinner_timer.stop()
        if isinstance(result, str) and result.startswith("Error"):
            self.status_label.setText(result)
        else:
            try:
                self.ifc_model = result
                self.middle_view.setModel(None)
                self.left_model.removeRows(0, self.left_model.rowCount())
                self.right_model.removeRows(0, self.right_model.rowCount())

                if self.file_path in self.recent_files:
                    self.recent_files.remove(self.file_path)
                self.recent_files.insert(0, self.file_path)
                self.recent_files = self.recent_files[:self.max_recent_files]
                self.update_recent_files_menu()
                self.save_recent_files()
                # f"Loaded {os.path.basename(self.file_path)}"\nPress the \"Load Entities\" button to view the contents"
                self.status_label.setText(MAIN_STATUS_LABEL_KEYS[4], format_args={"file_path": os.path.basename(self.file_path)})
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open IFC file:\n{str(e)}")
        
    def search_db(self, text):
        cursor = self.middle_model.search(text)
        return cursor.fetchall()

    def create_entity_label(self, entity):
        # get the attributes and attribute labels from the entity
        label = f"#{entity.id()} {entity.is_a()}".ljust(30)
        try:# Try to add the guid if it exists
            label += f"GUID: {entity.GlobalId}"
        except:
            label += "GUID: None"
        
        try:# Try to add the name if it exists
            label += f" | Name: {entity.Name}"
        except:
            label += " | Name: None"

        return label

    def update_recent_files_menu(self):
        self.recent_menu.clear()
        for path in self.recent_files:
            self.recent_menu.addAction(QAction(path, self, triggered=lambda _, p=path: self.load_ifc(p)))

    def load_recent_files(self):
        if os.path.exists(CONFIG_PATH):
            try:
                with open(CONFIG_PATH, 'r') as f:
                    data = json.load(f)
                    return data.get("recent_files", [])
            except Exception:
                return []
        return []

    def save_recent_files(self):
        try:
            with open(CONFIG_PATH, "r") as f: # Read the data first so we can modify instead of overwriting
                data = json.load(f)
            
            data["recent_files"] = self.recent_files

            with open(CONFIG_PATH, 'w') as f:
                json.dump(data, f)
        except Exception as e:
            print("Error saving config:", e)

    def open_ifc_file(self):
        if self.spinner_timer.isActive(): # Do not allow the user to use the toolbar while loading
                                          # to prevent unexpected behavior
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open IFC File", "", "IFC Files (*.ifc)")
        if path:
            self.load_ifc(path)

    def handle_entity_selection(self, index):
        sender = self.sender()

        if sender == self.middle_view.selectionModel():
            # Assume using the step id displayed in the middle view to look up in the ifc model
            # is faster than looking up in the SQL database
            step_id = index.sibling(index.row(), 0).data()  # column 0 = "STEP ID"

            # Remove the preceding "#" when looking up by step id in the ifc model
            entity = self.ifc_model.by_id(int(step_id[1:])) # Get the entity selected by the user

            # Update the left and right views
            self.populate_left_view(entity)
            self.populate_right_view(entity)
        elif sender == self.left_view.selectionModel():
            # Get the selected entity
            entity = self.left_model.itemFromIndex(index).data()
            # Update the right view
            self.populate_right_view(entity)
        
        # f"Selected entity #{entity.id()}"
        self.status_label.setText(MAIN_STATUS_LABEL_KEYS[5], format_args={"id": str(entity.id())})

    def populate_right_view(self, entity):
        #TODO: Improve performance for huge lists
        self.right_model.removeRows(0, self.right_model.rowCount())

        root_item = self.create_lazy_item(entity)
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsEditable) # Disallow editing
        self.right_model.appendRow(root_item)

    def lazy_load_forward_references(self, index):
        item = self.right_model.itemFromIndex(index)
        if not item:
            return

        if item.hasChildren() and item.child(0).text() == "Loading...":
            item.removeRows(0, item.rowCount())  # Remove placeholder

            entity = item.data()
            if not entity:
                return

            children = []
            info = entity.get_info() # Get the labels and values of the entity's attributes

            for attr_label, attr in info.items():
                # display all attributes in the root item up to 200 characters
                root_label = item.text()
                if len(root_label) < 200 and str(attr_label) != "id" and str(attr_label) != "type":
                    item.setText(root_label + f" | {str(attr_label)}: {str(attr)}")

                if isinstance(attr, ifcopenshell.entity_instance):
                    children.append(attr)
                elif isinstance(attr, (list, tuple)):
                    for sub in attr:
                        if isinstance(sub, ifcopenshell.entity_instance) and sub.id():
                            children.append(sub)

            if children:
                # Sort by STEP ID before adding
                children = sorted(children, key=lambda e: e.id())
                for child in children:
                    child_item = self.create_lazy_item(child)
                    child_item.setFlags(child_item.flags() & ~Qt.ItemIsEditable)
                    item.appendRow(child_item)
            else:
                # No entity references — show named attributes
                for key, value in info.items():
                    if key == "id" or key == "type":
                        continue
                    label = f"{key}: {value}"
                    item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                    item.appendRow(QStandardItem(label))

    def expand_entity_tree(self, parent_item, entity, lazy=False):
        if not isinstance(entity, ifcopenshell.entity_instance):
            return

        for attr in entity:
            if isinstance(attr, ifcopenshell.entity_instance):
                child = QStandardItem(self.create_entity_label(attr))
                child.setData(attr)
                if lazy:
                    child.appendRow(QStandardItem("Loading..."))
                else:
                    self.expand_entity_tree(child, attr, lazy)
                child.setFlags(child.flags() & ~Qt.ItemIsEditable)
                parent_item.appendRow(child)
            else:
                child = QStandardItem(str(attr))
                child.setFlags(child.flags() & ~Qt.ItemIsEditable)
                parent_item.appendRow(child)

    def load_entity_children(self, parent_item, entity):
        self.expand_entity_tree(parent_item, entity, lazy=True)

    def populate_left_view(self, entity):
        self.left_model.removeRows(0, self.left_model.rowCount())
        
        root_item = self.create_lazy_item(entity)
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsEditable) # items in the view are editable by default so prevent editing
        self.left_model.appendRow(root_item)

    def create_lazy_item(self, ent):
        item = QStandardItem(f"#{ent.id()} - {ent.is_a()} | Name: {ent.get_info().get('Name', 'N/A')}")
        item.setData(ent)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable) # Set as non-editable

        # Add placeholder child so it's expandable
        item.appendRow(QStandardItem("Loading..."))
        return item
    
    def lazy_load_inverse_references(self, index):
        # Get the item the user is expanding
        item = self.left_model.itemFromIndex(index)

        if not item:
            return

        # Display the selected entity's attributes on its line
        item.setText(self.create_entity_label(item.data()))

        # Check if already loaded
        if item.hasChildren() and item.child(0).text() == "Loading...":
            item.removeRows(0, item.rowCount())  # Remove placeholder

            entity = item.data()
            if not entity:
                return

            # Get and sort referencing entities by ID
            references = sorted(self.ifc_model.get_inverse(entity), key=lambda ref: ref.id())

            for ref in references:
                child_item = self.create_lazy_item(ref)
                child_item.setText(self.create_entity_label(child_item.data()))
                item.appendRow(child_item)

# ==============================
# Assembly exporter
# ==============================

    def show_assemblies_window(self):
        if not self.spinner_timer.isActive(): # If the application isn't currently loading or displaying an IFC file
            self.assembly_viewer = AssemblyViewerWindow(title=os.path.basename(self.file_path), ifc_model=self.ifc_model)
            self.assembly_viewer.show()

# ==============================
# Options dialog
# ==============================

    def show_options_window(self):
        if not self.spinner_timer.isActive():
            self.options_dialog = OptionsDialog(title=self.tr("IFCViewer Options"))
            self.options_dialog.exec() # Block the main window while the options dialog is open

    def change_language(self, language_code):
        if self.translator:
            QApplication.instance().removeTranslator(self.translator)

        self.translator = QTranslator()
        if self.translator.load(f"translations/{language_code}.qm"):
            QApplication.instance().installTranslator(self.translator)
            print(f"Installed {language_code} translator to main app")
        else:
            print(f"Unable to install {language_code} translator")

if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = QApplication(sys.argv)
    font_id = QFontDatabase.addApplicationFont("fonts/Inter-VariableFont_opsz,wght.ttf")
    if font_id == -1:
        print("Failed to load variable font.")
        font = QFont("Consolas", 11)
    else:
        family = QFontDatabase.applicationFontFamilies(font_id)[0]
        print("Loaded font family:", family)

        font = QFont(family)
        font.setPointSize(12)

    app.setFont(font)
    viewer = IfcViewer(file_path)
    viewer.resize(1200, 600)
    viewer.show()
    sys.exit(app.exec())