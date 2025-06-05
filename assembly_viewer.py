import os
import json
from collections import defaultdict
from collections.abc import Iterable
import ifcopenshell

from PySide6.QtWidgets import (
    QTableView, QHeaderView, QDockWidget, QMainWindow, QWidget, QVBoxLayout, QApplication,
    QAbstractItemView, QFileDialog, QHBoxLayout, QComboBox, QComboBox, QSizePolicy, QMenu
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, QThread, Signal, Slot, QTimer

import networkx as nx
from ifc_graph_viewer import IFCGraphViewer

from ui import TLabel, TPushButton, TCheckBox, TAction
from strings import (
    A_STATUS_LABEL_KEY, A_OUTPUT_PATH_LABEL_KEY, A_OUTPUT_BROWSE_KEY, A_EXPORTER_CHECKBOX_KEYS,
    A_EXPORT_BUTTON_KEY, CONTEXT_MENU_ACTION_KEYS, A_EXPORTING_KEYS
)
def is_iterable(obj):
    return isinstance(obj, Iterable) and not isinstance(obj, (str, bytes))

from options import CONFIG_PATH
# TODO: Show a progress bar for export
# TODO: IFC version selector
# TODO: Open exported ifc in a new ifc viewer window

class ExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, entities_to_export, export_path, original_model,
                 grid_toggle=False):
        super().__init__()
        self.entities_to_export = entities_to_export
        self.export_path = export_path
        self.ifc_model = original_model
        self.grid_toggle = grid_toggle

    def run(self):
        # Create a directed graph to represent the forward and reverse references for the assemblies to be exported
        self.G = nx.DiGraph()
        # Get selected entities
        print("ExportWorker:")
        print("Exporting the following assemblies:")
        for entity in self.entities_to_export:
            print(entity.id())
        print(f"{len(self.entities_to_export)} entities")

        # TODO: Add an ifc version selector
        self.output_model = ifcopenshell.file(schema="IFC4X3")

        # Add assemblies and their objects
        objects = []
        for assembly in self.entities_to_export:
            self.add_to_output_model(assembly)
            temp = self.find_assembly_objects(assembly)
            for object in temp:
                self.add_to_output_model(object)
            objects.extend(temp)

        # Find related entities for each assembly
        for element in self.entities_to_export:
            self.find_ifc_rel_contained_in_spatial_structure(element, self.entities_to_export)
        
        # Find related entities for each object
        for object in objects:
            self.find_ifc_rel_defines_by_properties(entity=object, allowed_entities=self.entities_to_export)
            self.find_material(object, self.entities_to_export)
            self.find_voids_elements(object)

            for child in self.get_children_recursive(object):
                self.add_to_output_model(object)

        self.export_assemblies_to_file()
        self.finished.emit([self.G, self.export_path])

    # ----------------------
    # Helper methods below
    # ----------------------

    # Add a given entity to the networkx graph
    # Call this method rather than inserting manually
    def add_entity_to_graph(self, entity, source=None, color=None):
        self.G.add_node(entity.id(), entity=entity, color=color or 'default')
        if source:
            self.G.add_edge(source.id(), entity.id())

    # This method gets a relating entity that references the given entity.
    # However, the relating entity also references many other entities
    # so we remove the references we are not planning to export before adding
    # it to the output model. Lastly, revert the change to the reference list
    # to prevent corruption in the original model
    def clone_relation_with_filtered_targets(self, relation, attr_name, allowed_targets):
        original = getattr(relation, attr_name)
        intersection = list(set(original).intersection(allowed_targets))
        setattr(relation, attr_name, intersection)
        self.add_to_output_model(relation)
        setattr(relation, attr_name, original)

    def add_to_output_model(self, entity):
        attributes = entity.get_info()
        try:
            return self.output_model.create_entity(**attributes)
        except Exception as e:
            print(e)
            return -1

    # Find all objects that make up a given assembly
    def find_assembly_objects(self, assembly):
        rel_agg = self.find_ifc_rel_aggregates(assembly)
        if not rel_agg:
            return []

        objects = rel_agg.RelatedObjects
        for obj in objects:
            self.add_to_output_model(obj)
        return objects

    # Find the IfcRelAggregates entity that references the given assembly
    # This provides a list of all objects that make up the assembly
    def find_ifc_rel_aggregates(self, assembly):
        for relation in assembly.IsDecomposedBy:
            if relation.is_a("IfcRelAggregates"):
                self.add_to_output_model(relation)
                return relation
        return None

    # Find all voiding elements associated with the given object/element
    def find_voids_elements(self, element):
        for rel_void in element.HasOpenings:
            self.add_to_output_model(rel_void)
            children = self.get_children_recursive(rel_void)
            for child in children:
                self.add_to_output_model(child)

    # Every assembly is referenced by an IfcRelContainedInSpatialStructure entity
    # which provides spatial data within the model for the assembly
    # However, this referencing entity also references other assemblies
    # so we make sure only to keep the references of assemblies we want to export
    def find_ifc_rel_contained_in_spatial_structure(self, entity, allowed_entities):
        for relation in entity.ContainedInStructure:
            self.clone_relation_with_filtered_targets(relation, "RelatedElements", allowed_entities)

    def find_ifc_rel_defines_by_properties(self, entity, allowed_entities):
        for relation in entity.IsDefinedBy:
            self.clone_relation_with_filtered_targets(relation, "RelatedObjects", allowed_entities)

    def find_material(self, element, allowed_elements):
        for assoc in element.HasAssociations:
            if assoc.is_a("IfcRelAssociatesMaterial"):
                self.clone_relation_with_filtered_targets(assoc, "RelatedObjects", allowed_elements)

                material = assoc.RelatingMaterial
                if material:
                    self.add_to_output_model(material)
                return material
        return None
    
    def get_related_entities(self, entity_type):
        entities = self.ifc_model.by_type(entity_type)
        for entity in entities:
            self.add_to_output_model(entity)
            children = self.get_children_recursive(entity)
            parents = list(self.ifc_model.get_inverse(entity))
            # Combine the forward and reverse references of the IfcProject entity
            entities_to_add = children + parents

            # Add the IfcProject entity and its directly related entities
            for entity in entities_to_add:
                self.add_to_output_model(entity)
        
    def export_assemblies_to_file(self):
        print(f"Exporting {len(self.G)} entities to {self.export_path}")

        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding, IfcSite

        # Get IfcProject
        self.get_related_entities("IfcProject")
       
        # Get IfcBuilding
        self.get_related_entities("IfcBuilding")

        # Get IfcSite
        self.get_related_entities("IfcSite")

        self.get_related_entities("IfcOrganization")

        self.get_related_entities("IfcPerson")

        # Add the assemblies we want to export
        print("OUTPUTTING FROM GRAPH")
        for node_id, node_attributes in self.G.nodes(data=True):
            entity = node_attributes.get("entity")
            print(f"Outputting {entity}")
            if entity:
                self.add_to_output_model(entity)
        
        
        self.check_references() # Check if forward references are missing

        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle:
            for entity in self.output_model.by_type("IfcGridAxis"):
                self.output_model.remove(entity)
            for entity in self.output_model.by_type("IfcGrid"):
                self.output_model.remove(entity)
        self.output_model.write(self.export_path)

    def check_references(self):
        for entity in self.output_model:
            for attr in entity.get_info().keys():
                if attr in ("id", "type", "Name", "Description", "GlobalId"):
                    continue
                try:
                    val = getattr(entity, attr)
                except AttributeError:
                    continue
                if isinstance(val, ifcopenshell.entity_instance):
                    try:
                        temp = self.output_model.by_id(val.id())
                    except:
                        self.add_to_output_model(val)
                        children = self.get_children_recursive(val)
                        for child in children:
                            if self.add_to_output_model(child) == -1: # Stop adding if children already exist TODO: often skips important entities
                                break
                        print(f"{val.id()}: was missing so added to model\n+ {len(children)} children")
                elif isinstance(val, Iterable) and not isinstance(val, (str, bytes)):
                    for v in val:
                        try:
                            if isinstance(v, ifcopenshell.entity_instance):
                                temp = self.output_model.by_id(v.id())
                        except:
                            self.add_to_output_model(v)
                            children = self.get_children_recursive(v)
                            for child in children:
                                if self.add_to_output_model(child) == -1:
                                    break
                            print(f"{v.id()}: was missing so added to model\n+ {len(children)} children")
    
    def get_children_recursive(self, entity):
        children = []

        for attr in entity.get_info().keys():
            if attr in ("id", "type", "Name", "Description", "GlobalId"):
                continue
            try:
                value = getattr(entity, attr)
            except AttributeError:
                continue

            if isinstance(value, ifcopenshell.entity_instance):
                children.append(value)
                children.extend(self.get_children_recursive(value))
            elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                for v in value:
                    if isinstance(v, ifcopenshell.entity_instance):
                        children.append(v)
                        children.extend(self.get_children_recursive(v))

        return children

class AssemblyTableModel(QAbstractTableModel):
    def __init__(self, assemblies, parent=None):
        super().__init__(parent)
        self.headers = ["STEP ID", "Assembly Mark", "GlobalId", "Name", "Type"]
        self.data_list = []
        self.assemblies = assemblies
        self.populate_assemblies()

    def rowCount(self, parent=QModelIndex()):
        return len(self.data_list)

    def columnCount(self, parent=QModelIndex()):
        return len(self.headers)

    def data(self, index, role=Qt.DisplayRole):
        if not index.isValid():
            return None

        if role == Qt.DisplayRole:
            return self.data_list[index.row()][index.column()]

        if role == Qt.UserRole:
            return self.data_list[index.row()][-1]  # IFC entity stored in last column

        return None

    def headerData(self, section, orientation, role=Qt.DisplayRole):
        if orientation == Qt.Horizontal and role == Qt.DisplayRole:
            return self.headers[section]
        return None
    
    def populate_assemblies(self):
        for mark, entities in self.assemblies.items():
            for entity in entities:
                info = entity.get_info()
                step_id = "#" + str(entity.id())
                global_id = info.get("GlobalId", "")
                name = info.get("Name", "")
                ifc_type = entity.is_a()
                self.data_list.append([step_id, mark, global_id, name, ifc_type, entity])

class AssemblyViewerWindow(QMainWindow):
    def __init__(self, ifc_model, title=None, parent=None):
        super().__init__(parent)

        self.resize(600, 400)

        self.ifc_model = ifc_model
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        # "Select the assemblies to be exported"
        self.status_label = TLabel(A_STATUS_LABEL_KEY, context="Assembly Status Label")
        self.status_label.setWordWrap(True)

        self.add_assembly_export_button()
        self.add_toggles()
        self.add_file_layout()

        layout.addLayout(self.file_layout)
        layout.addLayout(self.toggle_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.assembly_export_button)

        # Table View
        self.assembly_table = QTableView()
        self.model = AssemblyTableModel(assemblies=self.find_assemblies())
        self.assembly_table.setModel(self.model)

        self.title = title
        if self.title:
            self.setWindowTitle(f"{self.model.rowCount()} Assemblies found in {self.title}")
        else:
            self.setWindowTitle("Assembly Viewer")

        self.assembly_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assembly_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.assembly_table.setSortingEnabled(True)
        self.assembly_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.assembly_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.assembly_table.customContextMenuRequested.connect(lambda pos, v=self.assembly_table: self.show_context_menu(pos, v))

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
                    return data.get("recent_exported_files", ["assemblies.ifc"])
            except Exception:
                return ["assemblies.ifc"]
        return ["assemblies.ifc"]

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
    
    def add_toggles(self):
        # "Draw Graph"
        self.graph_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[0], self, context="Exporter Checkboxes")
        self.graph_toggle_checkbox.setChecked(False)

        # "Export Grids"
        self.grid_toggle_checkbox = TCheckBox(A_EXPORTER_CHECKBOX_KEYS[1], self, context="Exporter Checkboxes")
        self.grid_toggle_checkbox.setChecked(False)

        self.toggle_layout = QHBoxLayout()

        self.grid_toggle_checkbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_layout.addWidget(self.graph_toggle_checkbox)
        self.toggle_layout.addWidget(self.grid_toggle_checkbox) 

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
            self.update_recent_paths(export_path)

            # TODO: Start loading UI
            # "Exporting {file_path}"
            self.status_label.setText(A_EXPORTING_KEYS[0])
            # start export
            self.entities_to_export = [
                self.model.data(index, Qt.UserRole)
                for index in self.assembly_table.selectionModel().selectedRows()
                if self.model.data(index, Qt.UserRole)
            ]

            self.export_worker = ExportWorker(self.entities_to_export, export_path,
                                        self.ifc_model, self.grid_toggle_checkbox.isChecked())
            self.export_worker.progress.connect(self.update_export_progress)
            self.export_worker.finished.connect(self.export_finished)
            self.export_worker.start()

    def update_export_progress(self, percent):
        self.progress_bar.setValue(percent)
 
    @Slot(int)
    def update_export_progress(self, progress):
        print(f"Export progress: {progress}")
        pass

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
 
    
    @Slot(list)
    def export_finished(self, results):
        self.G = results[0] # Get the networkx graph

        # Optionally, display the selected assemblies in a graph
        if self.graph_toggle_checkbox.isChecked():
            viewer = IFCGraphViewer(self.G, self.entities_to_export)
            dock = QDockWidget(f"Graph of {self.title}" if self.title else "Graph view", self)
            dock.setWidget(viewer)
            self.addDockWidget(Qt.RightDockWidgetArea, dock)
        
        self.spinner_timer.stop()
        # "Exported {entity_count} {entity_type}(s) to {file_path}"
        self.status_label.setText(A_EXPORTING_KEYS[1],
                                  format_args={"entity_count": str(len(self.entities_to_export)),
                                               "entity_type": "Assembly",
                                               "file_path": results[1]})
   
    # Find all assemblies in the ifc file
    # Return the assemblies as a dictionary
    # Key: Assembly mark, Value: Entity object
    def find_assemblies(self):
        # Each IfcElementAssembly represents one assembly
        # So does each IfcRelAggregates

        assemblies = self.ifc_model.by_type("IfcElementAssembly")

        print(f"Found {len(assemblies)} assemblies")
        
        # store assemblies with their info i.e. assembly mark and step line id
        result = defaultdict(list)
        
        # Find the assembly mark for each assembly and add them to the result dictionary
        for assembly in assemblies:
            result[self.get_assembly_mark(assembly)].append(assembly)

        return result
            
    def get_assembly_mark(self, assembly):
        for parent in assembly.IsDefinedBy: # Use a precomputed reverse index instead of get_inverse
            if parent.is_a("IfcRelDefinesByProperties"):
                property_set = parent.RelatingPropertyDefinition
                for property in property_set.HasProperties:
                    if property.is_a("IfcPropertySingleValue"):
                        if property.Name == "AssemblyMark":
                            return property.NominalValue.wrappedValue

        return "NO ASSEMBLY MARK"