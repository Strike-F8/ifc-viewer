import sys
import os
import json
import ifcopenshell

from assembly_viewer import AssemblyViewerWindow
from db import DBWorker, SqlEntityTableModel
from options import OptionsWindow
from ui import LanguageManager, TAction, language_manager

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QTableView, QHBoxLayout, QVBoxLayout, QWidget, QLabel,
    QToolBar, QMessageBox, QFileDialog, QMenu, QLineEdit, QSplitter, QPushButton, QAbstractItemView, QHeaderView
)
from PySide6.QtGui import QAction, QStandardItemModel, QStandardItem, QFont
from PySide6.QtCore import Qt, QThread, Signal, Slot, QTimer, QTranslator

CONFIG_PATH = os.path.join(os.path.dirname(__file__),"config.json") # Save the recent files list
DB_URI = "file:memdb1?mode=memory&cache=shared" # In memory database to be shared between threads

# TODO: Clearer labels for the main 3 views for ease of use
# TODO: Multiple language support
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
   
class IfcViewer(QMainWindow):
    def __init__(self, ifc_file=None):
        super().__init__()
        self.setWindowTitle("IFC Reference Viewer")
        self.file_path = ifc_file
        self.filter_cache = []

        if ifc_file:
            self.ifc_model = self.load_ifc(self.file_path)
        else:
            self.ifc_model = None

        self.max_recent_files = 5
        self.recent_files = self.load_recent_files()

        self.middle_model = None # Set this up later when the ifc file is loaded
        self.middle_view = QTableView()
        self.middle_view.setSelectionBehavior(QAbstractItemView.SelectRows)
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

        # Lazy load children upon expanding a root item
        self.left_view.expanded.connect(self.lazy_load_inverse_references)
        self.right_view.expanded.connect(self.lazy_load_forward_references)

        # Update the views when selecting an item in the middle or left views
        self.left_view.selectionModel().currentChanged.connect(self.handle_entity_selection)

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
        
        self.spinner_timer = QTimer()
        self.spinner_timer.setInterval(100)
        self.spinner_timer.timeout.connect(self.update_spinner)

    def add_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.LeftToolBarArea, toolbar)
        toolbar.addAction(TAction("Open File", self, triggered=self.open_ifc_file, tooltip="Load a new IFC file"))
        toolbar.addAction(TAction("Load Entities", self, triggered=self.start_load_db_task, tooltip="Display the IFC file contents"))
        toolbar.addAction(TAction("Assembly Exporter", self, triggered=self.show_assemblies_window, tooltip="Open a new window for exporting assemblies"))
        toolbar.addAction(TAction("Options", self, triggered=self.show_options_window, tooltip="Show the options window"))

    def add_status_label(self):
        self.status_label = QLabel("＜ーChoose an IFC file to open")
        self.status_label.setMinimumHeight(20)
        self.status_label.setMaximumHeight(35)

    def add_file_menu(self):
        self.menubar = self.menuBar()
        file_menu = self.menubar.addMenu("File")

        file_menu.addAction(QAction("Open", self, triggered=self.open_ifc_file))
        file_menu.addAction(QAction("New Window", self, triggered=self.open_new_window))

        self.recent_menu = QMenu("Recent Files", self)
        file_menu.addMenu(self.recent_menu)
        self.update_recent_files_menu()

    def add_filter_bar(self):
        self.filter_bar = QLineEdit(self)
        self.filter_bar.setPlaceholderText("Press ENTER to filter entities...")
        self.filter_bar.textChanged.connect(self.apply_filter)
    
    def add_filter_button(self):
        self.filter_button = QPushButton(self)
        self.filter_button.setText("Filter")
        self.filter_button.clicked.connect(self.apply_filter)

    def apply_filter(self):
        filter_term = self.filter_bar.text()
        self.middle_model.set_filter(filter_term)
        
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
        # Copy the step line of the current item
        copy_step_line_action = QAction(f"Copy STEP Line #{entity.id()}", menu)
        copy_step_line_action.triggered.connect(lambda: self.copy_step_line(entity))
        menu.addAction(copy_step_line_action)

        # Copy the step id of the current item
        copy_step_id_action = QAction(f"Copy STEP ID #{entity.id()}", menu) 
        copy_step_id_action.triggered.connect(lambda: self.copy_step_id(entity))
        menu.addAction(copy_step_id_action)

        # Copy the GUID of the current item
        try:
            copy_guid_action = QAction(f"Copy GUID {entity.GlobalId}")
            copy_guid_action.triggered.connect(lambda: self.copy_guid(entity))
            menu.addAction(copy_guid_action)
        except:
            pass # Some entities do not have GUID so skip

        # Copy the current item
        copy_row_action = QAction("Copy This Row", menu)
        copy_row_action.triggered.connect(lambda: self.copy_row_text(view, index.row()))
        menu.addAction(copy_row_action)

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
        self.status_label.setText(f"Now loading: {os.path.basename(file_path)}")
        self.spinner_timer.start()

        self.load_ifc_worker = SimpleIFCWorker(task_fn=lambda: ifcopenshell.open(file_path))
        self.load_ifc_worker.progress.connect(self.update_spinner)
        self.load_ifc_worker.finished.connect(self.ifc_file_loaded)
        self.load_ifc_worker.start()
    
    def start_load_db_task(self):
        if not self.spinner_timer.isActive():
            self.status_label.setText("Now loading IFC model into view")
            self.spinner_timer.start()

            self.load_db_worker = DBWorker(self.ifc_model)
            self.load_db_worker.progress.connect(self.update_spinner)
            self.load_db_worker.finished.connect(self.load_db_finished)
            self.load_db_worker.start()

    @Slot()
    def load_db_finished(self):
        self.spinner_timer.stop()
        self.status_label.setText(f"Finished loading {os.path.basename(self.file_path)}")
        self.middle_model = SqlEntityTableModel(self.ifc_model, self.file_path)
        self.middle_view.setModel(self.middle_model)
        self.middle_view.selectionModel().currentChanged.connect(self.handle_entity_selection)
   
    @Slot(int)
    def update_spinner(self):
        frame = self.spinner_frames[self.current_frame % len(self.spinner_frames)]
        self.status_label.setText(f"{frame} Now loading: {os.path.basename(self.file_path)}")
        self.current_frame += 1
    
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
            
                status_text = f"Loaded \"{os.path.basename(self.file_path)}\"\nPress the \"Load Entities\" button to view the contents"
                self.status_label.setText(status_text)
            except Exception as e:
                QMessageBox.critical(self, "Error", f"Failed to open IFC file:\n{str(e)}")
        
    def search_db(self, text):
        cursor = self.middle_model.search(text)
        return cursor.fetchall()

    def create_entity_label(self, entity):
        # get the attributes and attribute labels from the entity
        label = "#{entity.id()} {entity.is_a()}".ljust(30)
        try:# Try to add the guid if it exists
            label += "GUID: {entity.GlobalId}"
        except:
            label += "GUID: None"
        
        try:# Try to add the name if it exists
            label += " | Name: {entity.Name}"
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
            with open(CONFIG_PATH, 'w') as f:
                json.dump({"recent_files": self.recent_files}, f)
        except Exception as e:
            print("Error saving config:", e)

    def open_ifc_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Open IFC File", "", "IFC Files (*.ifc)")
        if path:
            self.load_ifc(path)

    def open_new_window(self):
        self.new_window = IfcViewer()
        self.new_window.show() 

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
        
        self.status_label.setText(f"Selected entity #{entity.id()}")

    def populate_right_view(self, entity):
        self.right_model.removeRows(0, self.right_model.rowCount())

        root_item = self.create_lazy_item(entity)
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsEditable)
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

            visited = set()
            visited.add(entity.id())

            children = []
            info = entity.get_info() # Get the labels and values of the entity's attributes

            for attr_label, attr in info.items():
                # display all attributes in the root item up to 200 characters
                root_label = item.text()
                if len(root_label) < 200 and str(attr_label) != "id" and str(attr_label) != "type":
                    item.setText(root_label + f" | {str(attr_label)}: {str(attr)}")

                if isinstance(attr, ifcopenshell.entity_instance):
                    if attr.id() not in visited:
                        children.append(attr)
                elif isinstance(attr, (list, tuple)):
                    for sub in attr:
                        if isinstance(sub, ifcopenshell.entity_instance) and sub.id() not in visited:
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
                info = entity.get_info()
                for key, value in info.items():
                    if key == "id" or key == "type":
                        continue
                    label = "{key}: {value}"
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
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

        # Add placeholder child so it's expandable
        item.appendRow(QStandardItem("Loading..."))
        return item
    
    def lazy_load_inverse_references(self, index):
        item = self.left_model.itemFromIndex(index)
        # Display the root entity's attributes on the root
        item.setText(self.create_entity_label(item.data()))

        if not item:
            return

        # Check if already loaded
        if item.hasChildren() and item.child(0).text() == "Loading...":
            item.removeRows(0, item.rowCount())  # Remove placeholder

            entity = item.data()
            if not entity:
                return

            visited = set()
            visited.add(entity.id())

            # Get and sort referencing entities by ID
            references = sorted(self.ifc_model.get_inverse(entity), key=lambda ref: ref.id())

            for ref in references:
                if ref.id() not in visited:
                    child_item = self.create_lazy_item(ref)
                    child_item.setText(self.create_entity_label(child_item.data()))
                    item.appendRow(child_item)

# ==============================
# Assembly exporting functions
# ==============================

    def show_assemblies_window(self):
        if not self.spinner_timer.isActive(): # If the application isn't currently loading or displaying an IFC file
            self.assembly_viewer = AssemblyViewerWindow(title=self.file_path, ifc_model=self.ifc_model)
            self.assembly_viewer.show()

# ==============================
# Options window
# ==============================

    def show_options_window(self):
        if not self.spinner_timer.isActive():
            self.options_window = OptionsWindow(title="IFCViewer Options")
            self.options_window.show()

if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = QApplication(sys.argv)
    font = QFont("Consolas", 11)
    app.setFont(font)
    viewer = IfcViewer(file_path)
    viewer.resize(1200, 600)
    viewer.show()
    sys.exit(app.exec())
