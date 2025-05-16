import sys
import os
import json
import ifcopenshell
import concurrent.futures
import sqlite3
import functools

from assembly_viewer import AssemblyViewerWindow

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QTreeView, QTableView, QHBoxLayout, QVBoxLayout, QWidget,
    QToolBar, QMessageBox, QFileDialog, QMenu, QLineEdit, QSplitter, QPushButton, QAbstractItemView, QHeaderView
)
from PySide6.QtGui import QAction, QStandardItemModel, QStandardItem, QFont
from PySide6.QtCore import Qt, QAbstractTableModel, QEvent, QModelIndex, QThread, Signal

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.json")
# TODO: When exporting assemblies, get all geometry including openings and materials
# TODO: Implement SQLite for better performance with large ifc files

class _UpdateFilterEvent(QEvent):
    EVENT_TYPE = QEvent.Type(QEvent.registerEventType())

    def __init__(self, results):
        super().__init__(self.EVENT_TYPE)
        self.results = results

class SqlEntityTableModel(QAbstractTableModel):
    def __init__(self, ifc_model, file_path):
        super().__init__()
        db_path = f"db/{os.path.basename(file_path)}.sqlite3"
        self.file_path = file_path
        self.ifc_model = ifc_model
        os.makedirs("db", exist_ok=True) # Make the db folder if it doesn't exist

        self.db = sqlite3.connect(db_path) # Save a database with the name of the ifc file
        self.db.row_factory = sqlite3.Row
        self._columns = ["STEP ID", "Ifc Type", "GUID", "Name", "STEP Line"]
        self.columns_sql = ", ".join(f'"{col}"' for col in self._columns) # Define the columns here only to prevent discrepancies

        self.populate_db()

        self._filter = ""
        self._row_ids = []
        self._sort_column = "\"STEP ID\""
        self._sort_order = "ASC"

        self._load_row_ids()

    def _load_row_ids(self):
        if self._filter:
            query = f"""
                SELECT rowid FROM fts_entities
                WHERE fts_entities MATCH ?
            """
            params = (self._filter,)
        else:
            query = "SELECT id FROM base_entities"
            params = ()

        query += f" ORDER BY {self._sort_column} {self._sort_order}"

        self._row_ids = [row[0] for row in self.db.execute(query, params)]
        self._row_count = len(self._row_ids)

    def set_filter(self, filter_text):
        self._filter = filter_text
        self._load_row_ids()
        self._get_row.cache_clear()
        self.layoutChanged.emit()

    def set_sort(self, column_name, ascending=True):
        if column_name in self._columns:
            self._sort_column = column_name
            self._sort_order = "ASC" if ascending else "DESC"
            self._load_row_ids()
            self._get_row.cache_clear()
            self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return self._row_count

    def columnCount(self, parent=QModelIndex()):
        return len(self._columns)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return self._columns[section].capitalize()
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None
        row = self._get_row(index.row())
        if not row:
            return None
        return row[self._columns[index.column()]]

    @functools.lru_cache(maxsize=4096)
    def _get_row(self, row_index):
        if row_index >= len(self._row_ids):
            return None
        row_id = self._row_ids[row_index]
        return self.db.execute(
            f"SELECT {self.columns_sql} FROM base_entities WHERE id = ?",
            (row_id,)
        ).fetchone()


    def populate_db(self):
        try:
            self.db.execute("DROP TABLE IF EXISTS base_entities")
            self.db.execute("DROP TABLE IF EXISTS fts_entities")
        except Exception as e:
            print(e)

        # Create the base table and virtual table
        try:
            self.db.execute(f"CREATE TABLE base_entities (id INTEGER PRIMARY KEY,{self.columns_sql})")
        except Exception as e:
            print(f"failed to create base_entities\n{e}")

        try:
            self.db.execute(f"""CREATE VIRTUAL TABLE fts_entities USING fts5(
                {self.columns_sql},
                content='base_entities',
                content_rowid='id'
                )
            """)
        except Exception as e:
            print(f"failed to create fts_entities\n{e}")

        try:
            batch = []
            for entity in self.ifc_model:
                info = entity.get_info()
                batch.append([
                    f"#{entity.id()}",        # STEP ID
                    entity.is_a(),            # Ifc Type
                    info.get("GlobalId", ""), # GUID
                    info.get("Name", ""),     # Name
                    str(entity)               # STEP Line
                ])

            self.db.execute("PRAGMA journal_mode = OFF")
            self.db.execute("PRAGMA synchronous = OFF")

            self.db.executemany(f"INSERT INTO base_entities ({self.columns_sql}) VALUES (?, ?, ?, ?, ?)", batch)
            
            self.db.execute("INSERT INTO fts_entities(fts_entities) VALUES ('rebuild')")
            self.db.commit()
        except Exception as e:
            print(f"Failed to populate DB\n{e}")

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
        self.middle_view.setSortingEnabled(False)
        self.middle_view.verticalHeader().setDefaultSectionSize(20)
        self.middle_view.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        self.middle_view.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)

        self.middle_view.setWordWrap(False)
        for i in range(4): # TODO: Check column width
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
        self.add_file_menu()
        self.add_search_bar()
        self.add_search_button()

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
        #toolbar.addAction(QAction("Display Entities", self, triggered=self.load_entities)) # Large files take a long time 
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
    
    # When clicking on an entity in either of the three views, show a context menu that allows the user to copy
    # the original step line of the entity
    def show_context_menu(self, position, view):
        index = view.indexAt(position)
        if not index.isValid():
            return

        entity = None

        if view == self.middle_view:
            # Get the selected entity
            entity = self.middle_model.get_entity(index.row())
        else:
            # Get the selected entity
            entity = view.model().itemFromIndex(index).data()

        if not entity:
            return
        
        menu = QMenu()
        copy_action = QAction(f"Copy STEP Line #{entity.id()}", menu)
        copy_action.triggered.connect(lambda: self.copy_step_line(entity))
        menu.addAction(copy_action)
        copy_row_action = QAction("Copy This Row", menu)
        copy_row_action.triggered.connect(lambda: self.copy_row_text(view, index.row()))
        menu.addAction(copy_row_action)
        menu.exec(view.viewport().mapToGlobal(position))
        
    def copy_step_line(self, entity):
        clipboard = QApplication.clipboard()
        clipboard.setText(str(entity))

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
        try:
            self.ifc_model = ifcopenshell.open(file_path)
            self.file_path = file_path

            self.left_model.removeRows(0, self.left_model.rowCount())
            self.right_model.removeRows(0, self.right_model.rowCount())

            if file_path in self.recent_files:
                self.recent_files.remove(file_path)
            self.recent_files.insert(0, file_path)
            self.recent_files = self.recent_files[:self.max_recent_files]
            self.update_recent_files_menu()
            self.save_recent_files()

        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to open IFC file:\n{str(e)}")

        self.middle_model = SqlEntityTableModel(ifc_model=self.ifc_model, file_path=self.file_path)
        self.middle_view.setModel(self.middle_model)
        self.middle_view.selectionModel().currentChanged.connect(self.handle_entity_selection)

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
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsEditable)
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
                    child_item.setFlags(child_item.flags() & ~Qt.ItemIsEditable)
                    item.appendRow(child_item)
            else:
                # No entity references — show named attributes
                info = entity.get_info()
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
        root_item.setFlags(root_item.flags() & ~Qt.ItemIsEditable)
        self.left_model.appendRow(root_item)

    def create_lazy_item(self, ent):
        item = QStandardItem(f"#{ent.id()} - {ent.is_a()} | Name: {ent.get_info().get('Name', 'N/A')}")
        item.setData(ent)
        item.setFlags(item.flags() & ~Qt.ItemIsEditable)

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