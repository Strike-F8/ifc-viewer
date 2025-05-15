import sys
import os
import json
import ifcopenshell
import concurrent.futures

from assembly_viewer import AssemblyViewerWindow

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QTableView, QHBoxLayout, QVBoxLayout, QWidget,
    QToolBar, QMessageBox, QFileDialog, QMenu, QLineEdit, QSplitter, QPushButton, QAbstractItemView
)
from PySide6.QtGui import QAction, QStandardItemModel, QStandardItem, QFont
from PySide6.QtCore import Qt, QAbstractTableModel, QEvent

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
# TODO: When exporting assemblies, get all geometry including openings and materials
# TODO: Improve filtering for large files (Instead of hiding/showing, just show the relevant rows?)
# TODO: Review character limit for middle view (shorten long lists of references but keep everything else?)
#       e.g. #123=IfcElement('ASDFNAWEKFN',$,$,(#1, #2, #3,...+32refs), #10, #200)

class _UpdateFilterEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, results):
        super().__init__(self.EVENT_TYPE)
        self.results = results

class EntityViewModel(QAbstractTableModel):
    def __init__(self, entities=None):
        super().__init__()
        self.headers = ["STEP ID", "Type", "GUID", "Name", "Entity"]
        self.entities = entities
        self.data_list = []

    def rowCount(self, parent=None):
        return len(self.data_list)

    def columnCount(self, parent=None):
        return len(self.data_list[0]) if self.data_list else 0

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = index.row()
        col = index.column()
        if 0 <= row < len(self.data_list):
            return str(self.data_list[row][col])  # For display, show string versions of each column
        return None
    
    def get_entity(self, row):
        if 0 <= row < len(self.data_list):
            return self.data_list[row][4]
        return None

    def headerData(self, section, orientation, role):
        if role == Qt.DisplayRole and orientation == Qt.Horizontal:
            return self.headers[section]
        return None
    
    def clear(self):
        self.beginResetModel()
        self.data_list = []
        self.endResetModel()

    # Add the entities to the middle view
    def populate_entities(self, entities):
        self.beginResetModel()
        self.entities = sorted(entities, key=lambda e: e.id())  # Sort by STEP ID
        self.data_list = []
        self.filter_cache = []

        for entity in self.entities:
            info = entity.get_info()
            step_id = "#" + str(entity.id())
            global_id = info.get("GlobalId", "")
            name = info.get("Name", "")
            ifc_type = entity.is_a()
            self.data_list.append([step_id, ifc_type, global_id, name, entity])

            # Build a lowercase searchable string
            label = f"{step_id} {ifc_type} {global_id} {name}".lower()
            self.filter_cache.append(label)

        self.endResetModel()

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

        self.middle_model = EntityViewModel(self.ifc_model)

        self.middle_view = QTableView()
        self.middle_view.setModel(self.middle_model)
        self.middle_view.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.middle_view.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.middle_view.setSortingEnabled(True)
        self.middle_view.resizeColumnsToContents()
        self.middle_view.horizontalHeader().setStretchLastSection(True)
        self.middle_view.verticalHeader().setVisible(False)

        self.left_view = QTreeView()
        self.left_model = QStandardItemModel()
        self.left_model.setHorizontalHeaderLabels(['References -> Entity'])
        self.left_view.setModel(self.left_model)

        self.right_view = QTreeView()
        self.right_model = QStandardItemModel()
        self.right_model.setHorizontalHeaderLabels(['Entity <- Referenced By'])
        self.right_view.setModel(self.right_model)

        self.add_toolbar()
        self.add_file_menu()
        self.add_search_bar()
        self.add_search_button()

        # Lazy load children upon expanding a root item
        self.left_view.expanded.connect(self.lazy_load_inverse_references)
        self.right_view.expanded.connect(self.lazy_load_forward_references)

        # Update the views when selecting an item in the middle or left views
        self.middle_view.selectionModel().currentChanged.connect(self.handle_entity_selection)
        self.left_view.selectionModel().currentChanged.connect(self.handle_entity_selection)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(self.left_view)
        splitter.addWidget(self.middle_view)
        splitter.addWidget(self.right_view)

        center_layout = QVBoxLayout()
        search_layout = QHBoxLayout()
        search_layout.addWidget(self.search_bar)
        search_layout.addWidget(self.search_button)
        center_layout.addLayout(search_layout)
        center_layout.addWidget(splitter)
        container = QWidget()
        container.setLayout(center_layout)
        self.setCentralWidget(container)

        # prevent autoscrolling when clicking on an item
        self.middle_view.setAutoScroll(False)
        self.middle_view.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.middle_view.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)

        # threading for faster search
        self.executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    def add_toolbar(self):
        toolbar = QToolBar("Main Toolbar")
        self.addToolBar(Qt.LeftToolBarArea, toolbar)

        toolbar.addAction(QAction("Open File", self, triggered=self.open_ifc_file))
        toolbar.addAction(QAction("Display Entities", self, triggered=self.load_entities)) # Large files take a long time 
                                                                                        # so only load entities when the user clicks the button
        toolbar.addAction(QAction("Assembly Exporter", self, triggered=self.show_assemblies_window))

    def add_file_menu(self):
        self.menubar = self.menuBar()
        file_menu = self.menubar.addMenu("File")

        file_menu.addAction(QAction("Open", self, triggered=self.open_ifc_file))
        file_menu.addAction(QAction("New Window", self, triggered=self.open_new_window))

        self.recent_menu = QMenu("Recent Files", self)
        file_menu.addMenu(self.recent_menu)
        self.update_recent_files_menu()

    def add_search_bar(self):
        self.search_bar = QLineEdit(self)
        self.search_bar.setPlaceholderText("Press ENTER to filter entities...")
        self.search_bar.returnPressed.connect(self.start_filtering)
    
    def add_search_button(self):
        self.search_button = QPushButton(self)
        self.search_button.setText("Filter")
        self.search_button.clicked.connect(self.start_filtering)

    def load_entities(self):
        self.middle_model.clear()
        self.middle_model.populate_entities(list(self.ifc_model))

    def start_filtering(self):
        search_text = self.search_bar.text().lower()
        cache = list(self.middle_model.filter_cache)
        future = self.executor.submit(self.filter_rows, search_text, cache)
        future.add_done_callback(self.on_filter_finished)

    def filter_rows(self, search_text, cache):
        return [search_text in cached for cached in cache]

    def on_filter_finished(self, future):
        results = future.result()
        QApplication.postEvent(self, _UpdateFilterEvent(results))

    def customEvent(self, event):
        if isinstance(event, _UpdateFilterEvent):
            for row, visible in enumerate(event.results):
                self.middle_view.setRowHidden(row, not visible)
    
    
    def load_ifc(self, file_path):
        self.setWindowTitle(file_path)
        try:
            self.ifc_model = ifcopenshell.open(file_path)
            self.file_path = file_path

            self.middle_model.clear()
            self.left_model.removeRows(0, self.left_model.rowCount())
            self.right_model.removeRows(0, self.right_model.rowCount())

            self.load_entities()

            if file_path in self.recent_files:
                self.recent_files.remove(file_path)
            self.recent_files.insert(0, file_path)
            self.recent_files = self.recent_files[:self.max_recent_files]
            self.update_recent_files_menu()
            self.save_recent_files()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open IFC file:\n{str(e)}")

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
            # Get the selected entity
            entity = self.middle_model.get_entity(index.row())
            # Update the left and right views
            self.populate_left_view(entity)
            self.populate_right_view(entity)
        elif sender == self.left_view.selectionModel():
            # Get the selected entity
            entity = self.left_model.itemFromIndex(index).data()
            # Update the right view
            self.populate_right_view(entity)

    def populate_right_view(self, entity):
        self.right_model.removeRows(0, self.right_model.rowCount())

        root_item = self.create_lazy_item(entity)
        self.right_model.appendRow(root_item)

    def lazy_load_forward_references(self, index):
        item = self.right_model.itemFromIndex(index)
        if not item:
            return

        # Already loaded?
        if item.hasChildren() and item.child(0).text() == "Loading...":
            item.removeRows(0, item.rowCount())  # Remove dummy

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
                    item.appendRow(child_item)
            else:
                # No entity references — show named attributes
                info = entity.get_info()
                for key, value in info.items():
                    if key == "id" or key == "type":
                        continue
                    label = f"{key}: {value}"
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
                parent_item.appendRow(child)
            else:
                parent_item.appendRow(QStandardItem(str(attr)))

    def load_entity_children(self, parent_item, entity):
        self.expand_entity_tree(parent_item, entity, lazy=True)

    def populate_left_view(self, entity):
        self.left_model.removeRows(0, self.left_model.rowCount())
        
        root_item = self.create_lazy_item(entity)
        self.left_model.appendRow(root_item)

    def create_lazy_item(self, ent):
        item = QStandardItem(f"#{ent.id()} - {ent.is_a()} | Name: {ent.get_info().get('Name', 'N/A')}")
        item.setData(ent)

        # Add dummy child so it's expandable
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
            item.removeRows(0, item.rowCount())  # Remove dummy

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
        self.assembly_viewer = AssemblyViewerWindow(title=self.file_path, ifc_model=self.ifc_model)
        self.assembly_viewer.show()

if __name__ == "__main__":
    file_path = sys.argv[1] if len(sys.argv) > 1 else None
    app = QApplication(sys.argv)
    font = QFont("Consolas", 11)
    app.setFont(font)
    viewer = IfcViewer(file_path)
    viewer.resize(1200, 600)
    viewer.show()
    sys.exit(app.exec())