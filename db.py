import apsw
import functools
import re
from PySide6.QtCore import Qt, QAbstractTableModel, QModelIndex, QThread, Signal

DB_URI = "file:memdb1?mode=memory&cache=shared" # In memory database to be shared between threads
                                                # SQLite is not thread safe and in memory databases are
                                                # garbage collected upon closing the connection so this type of
                                                # shared in-memory database allows a background thread to load
                                                # the elements without blocking the main thread as long as the insert
                                                # is finished before attempting to read.

COLUMNS = ["STEP ID", "Ifc Type", "GUID", "Name", "STEP Line"]
COLUMNS_SQL = ", ".join(f'"{col}"' for col in COLUMNS) # Define the columns here and use this variable throughout the program

STEP_ID_IDX = 0
IFC_TYPE_IDX = 1
GUID_IDX = 2
NAME_IDX = 3
STEP_LINE_IDX = 4

# The DBWorker class populates the database used to display entities in the middle view.
# SQLite is not thread safe but using the shared in memory database as defined in DB_URI,
# DBWorker creates a connection solely used for inserting all the entities.
# Once the insert is done, the main thread is notified so it can start reading.
# TODO: Show the database populating in realtime (WAL mode?)
class DBWorker(QThread):
    progress = Signal(int)
    finished = Signal()

    def __init__(self, ifc_model):
        super().__init__()
        self.ifc_model = ifc_model

    def run(self):
        conn = apsw.Connection(DB_URI)
        cursor = conn.cursor()
        # DB optimizations for faster inserts
        # Perform these before apsw creates a transaction
        cursor.execute("PRAGMA journal_mode = OFF")
        cursor.execute("PRAGMA synchronous = OFF")
        cursor.execute("PRAGMA locking_mode = EXCLUSIVE")
        cursor.execute("PRAGMA temp_store = MEMORY")
        cursor.execute("PRAGMA cache_size = -10000000")
        cursor.close()

        with apsw.Connection(DB_URI) as conn: # Create a connection solely for inserting the elements in this background thread
            cursor = conn.cursor()

            try:
                cursor.execute("DROP TABLE IF EXISTS base_entities")
                cursor.execute("DROP TABLE IF EXISTS fts_entities")
            except Exception as e:
                print(e)

            # Create the base table
            try:
                cursor.execute(f"CREATE TABLE base_entities (id INTEGER PRIMARY KEY,{COLUMNS_SQL})")
            except Exception as e:
                print(f"failed to create base_entities\n{e}")

            # populate the base table
            try:
                def row_generator(): # Use a generator rather than a list for lower memory usage
                    for entity in list(self.ifc_model):
                        info = entity.get_info()
                        yield [
                            entity.id(),                    # STEP ID
                            entity.is_a(),                  # Ifc Type
                            info.get("GlobalId", ""),       # GUID
                            info.get("Name", ""),           # Name
                            self.generate_step_line(str(entity)) # If the step line contains a long list of references, truncate the list and keep everything else
                        ]

                # Execute all inserts in one batch
                cursor.executemany(f"INSERT INTO base_entities ({COLUMNS_SQL}) VALUES (?, ?, ?, ?, ?)", row_generator())

                # Create the virtual table for filtering
                try:
                    cursor.execute(f"""CREATE VIRTUAL TABLE fts_entities USING fts5(
                        {COLUMNS_SQL},
                        content='base_entities',
                        content_rowid='id',
                        tokenize='trigram remove_diacritics 1',
                        )
                    """)
                except Exception as e:
                    print(f"failed to create fts_entities\n{e}")

                cursor.execute("INSERT INTO fts_entities(fts_entities) VALUES ('rebuild')")
                
                self.finished.emit()
                cursor.close()

            except Exception as e:
                print(f"Failed to populate DB\n{e}")
                self.finished.emit()
                cursor.close()

    # If the step line contains a long list of references, truncate it to lighten the load on the middle view
    def generate_step_line(self, step_line, max_refs=2):
        if len(step_line) < 200:
            return step_line

        def replacer(match):
            refs = [r.strip() for r in match.group(1).split(',')]
            truncated = refs[:max_refs]
            removed_count = len(refs) - max_refs
            if removed_count > 0:
                return f"({','.join(truncated)}...+{removed_count} more)"
            else:
                return f"({','.join(truncated)})"

        return re.sub(r'\((#\d+(?:,\s*#\d+)*)\)', replacer, step_line, count=1)

# The SQLEntityTableModel class serves as the backend for the middle view.
# Previously, it inserted the entities into the database. Now, it is only created
# after the background thread is done inserting into the database.
class SqlEntityTableModel(QAbstractTableModel):
    row_count_changed = Signal(int)

    def __init__(self, ifc_model, file_path):
        super().__init__()
        self.file_path = file_path # The file path of the ifc file
        self.ifc_model = ifc_model # The ifc_model loaded into memory

        self.db = apsw.Connection(DB_URI)

        # Default filter
        self._filter = ""
        self._row_ids = []
        self._sort_column = "STEP ID" # Sort by step id
        self._sort_order = "ASC"

        self._load_rows()

    # Display the entities contained in the database
    # Optionally filter and sort by conditions provided by the user
    def _load_rows(self):
        if self._filter:
            query = f"""
                SELECT rowid FROM fts_entities
                WHERE fts_entities MATCH '"{self._filter}"'
                ORDER BY "{self._sort_column}" {self._sort_order}
            """
            rows = self.db.execute(query)
        else:
            query = f"""
                SELECT id FROM base_entities
                ORDER BY "{self._sort_column}" {self._sort_order}
            """
            rows = self.db.execute(query)

        self._row_ids = [row[0] for row in rows]
        self._row_count = len(self._row_ids)
        self.row_count_changed.emit(self._row_count)

    # Get the filter text inputted by the user and display the data again
    def set_filter(self, filter_text):
        self._filter = filter_text.strip()
        self._load_rows()
        self._get_row.cache_clear()
        self.layoutChanged.emit()

    # Sorts the database view
    def sort(self, column, order):
        self._sort_column = COLUMNS[column]
        if order == Qt.AscendingOrder:
            self._sort_order = "ASC"
        else:
            self._sort_order = "DESC"
        self._load_rows()
        self._get_row.cache_clear()
        self.layoutChanged.emit()

    def rowCount(self, parent=QModelIndex()):
        return self._row_count

    def columnCount(self, parent=QModelIndex()):
        return len(COLUMNS)

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if role != Qt.DisplayRole:
            return None
        if orientation == Qt.Horizontal:
            return COLUMNS[section]
        return str(section + 1)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid() or role != Qt.DisplayRole:
            return None

        row = self._get_row(index.row())
        if not row:
            return None

        col = index.column()

        if col == STEP_ID_IDX:
            return f"#{row[STEP_ID_IDX]}"

        return row[col]

    # Gets a row from the database by id
    # TODO: The cache probably helps but we should get the rows in batches instead of individually
    @functools.lru_cache(maxsize=4096) # _get_row is called many times so use a cache to optimize performance
    def _get_row(self, index):
        if index >= len(self._row_ids):
            return None

        rowid = self._row_ids[index]
        cursor = self.db.cursor()
        cursor.execute(f"SELECT {COLUMNS_SQL} FROM base_entities WHERE id = ?", (rowid,))
        return cursor.fetchone()