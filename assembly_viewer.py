from collections import defaultdict
from collections.abc import Iterable
import ifcopenshell

from PySide6.QtWidgets import (
    QTableView, QLabel, QHeaderView, QDockWidget, QMainWindow, QWidget, QVBoxLayout,
    QAbstractItemView, QPushButton, QFileDialog, QHBoxLayout, QComboBox, QComboBox, QSizePolicy
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, QSettings

import networkx as nx
from ifc_graph_viewer import IFCGraphViewer

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
        # Initialize app settings
        self.init_settings()

        self.title = title
        if self.title:
            self.setWindowTitle(f"Assemblies found in {self.title}")
        else:
            self.setWindowTitle("Assembly Viewer")

        self.resize(600, 400)

        self.ifc_model = ifc_model
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        self.status_label = QLabel("Select the assemblies to be exported")
        self.status_label.setWordWrap(True)

        self.add_assembly_export_button()
        self.add_file_layout()

        layout.addLayout(self.file_layout)
        layout.addWidget(self.status_label)
        layout.addWidget(self.assembly_export_button)

        # Table View
        self.assembly_table = QTableView()
        self.model = AssemblyTableModel(assemblies=self.find_assemblies())
        self.assembly_table.setModel(self.model)

        self.assembly_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.assembly_table.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.assembly_table.setSortingEnabled(True)
        self.assembly_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)

        layout.addWidget(self.assembly_table)
        self.setCentralWidget(central_widget)

        # Create a directed graph to represent the forward and reverse references for the assemblies to be exported
        self.G = nx.DiGraph()
    
    def init_settings(self):
        self.settings = QSettings("Taiwa", "IFCAssemblyExporter")
        self.recent_paths = self.settings.value("recent_paths", ["assemblies.ifc"])

    def add_assembly_export_button(self):
        self.assembly_export_button = QPushButton("Export", self)
        self.assembly_export_button.clicked.connect(self.export_assemblies)

    def add_file_layout(self):
        self.recent_paths = ["assemblies.ifc"]

        file_layout = QHBoxLayout()

        self.file_path_label = QLabel("Output Path:", self)
        self.file_path_combo = QComboBox(self)
        self.file_path_combo.setEditable(True)
        self.file_path_combo.addItems(self.recent_paths)
        self.file_path_combo.setCurrentText(self.recent_paths[0])
        self.file_path_combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

        self.browse_button = QPushButton("Browse...", self)
        self.browse_button.clicked.connect(self.browse_output_path)
    
        file_layout.addWidget(self.file_path_label)
        file_layout.addWidget(self.file_path_combo)
        file_layout.addWidget(self.browse_button)

        self.file_layout = file_layout
    
    def browse_output_path(self):
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
        self.settings.setValue("recent_paths", self.recent_paths)

    def export_assemblies(self):
        # 1. Get the list of selected assemblies
        selected_indexes = self.assembly_table.selectionModel().selectedRows()
        selected_entities = []

        for index in selected_indexes:
            entity = self.model.data(index, Qt.UserRole)
            if entity:
                selected_entities.append(entity)

        print("Exporting the following assemblies:")
        for entity in selected_entities:
            print(entity)
            
        # 2. Find the related entities for every assembly
        #       i.e. Referenced and referencing entities

        # TODO: Get all related entities including openings, voids, materials etc.
        #       without getting unselected entities as well
        #       Right now, this function only gets the overall geometry of the assembly parts

        self.G.clear() # Reset the graph for the new export
        assembly_objects = None
        for entity in selected_entities:
            # NEW: Make a list of objects that make up the assembly
            # Get the properties of each object
            # i.e. Geometry, materials, openings
            
            assembly_objects = self.find_assembly_objects(entity) 
            
            # OLD: recursively find entities related to the assemblies
            # Add the forward references of the starting entity to the graph
            #self.add_forward_references_to_graph(entity)
            # Add the reverse references of the starting entity to the graph
            #self.add_reverse_references_to_graph(entity)

        # Find related entities for each object
        for object in assembly_objects:
            self.find_material(object)
            self.add_forward_references_to_graph(object)
            self.add_reverse_references_to_graph(object)
        
        # TODO: Remove unnecessary references from IfcRelAssociatesMaterial

        # Visualize graph using Pyside graph
        self.viewer = IFCGraphViewer(self.G)

        # Add to a dockable widget
        if self.title:
            dock = QDockWidget(f"Graph of {self.title}", self)
        else:
            dock = QDockWidget("Graph view", self)
            
        dock.setWidget(self.viewer)
        self.addDockWidget(Qt.RightDockWidgetArea, dock)

        # 3. TODO: Save related entities with their original step ids
        # 4. Output to a new IFC file
        self.export_assemblies_to_file()

    def add_forward_references_to_graph(self, entity):
        self.G.add_node(entity.id(), entity=entity)

        for attr_name in entity.get_info().keys():
            if attr_name in ("id", "type", "Name", "Description", "GlobalId"): # skip attributes that we know are not references
                continue
            value = getattr(entity, attr_name, None)
            if isinstance(value, ifcopenshell.entity_instance):
                self.G.add_edge(entity.id(), value.id())
                self.add_forward_references_to_graph(value)
            elif str(value) == "RelatedObjects": # TODO: Traverse into every type of iterable. Not just RelatedObjects
                for item in value:
                    if isinstance(item, ifcopenshell.entity_instance):
                        self.G.add_edge(entity.id(), item.id())
                        self.add_forward_references_to_graph(item)
    
    def add_reverse_references_to_graph(self, entity):
        self.G.add_node(entity.id(), entity=entity)

        for referrer in self.ifc_model.get_inverse(entity):
            self.add_reverse_references_to_graph(referrer)
            self.add_forward_references_to_graph(referrer)
    
    def find_ifc_rel_aggregates(self, assembly):
        ifc_rel_aggregates = None
        
        for entity in self.ifc_model.get_inverse(assembly):
            if entity.is_a() == "IfcRelAggregates":
                ifc_rel_aggregates = entity
                print(f"Found {ifc_rel_aggregates}\nfor {assembly}")
                break

        if ifc_rel_aggregates:
            self.G.add_node(ifc_rel_aggregates.id(), entity=ifc_rel_aggregates)
            self.G.add_edge(assembly.id(), ifc_rel_aggregates.id())

        return ifc_rel_aggregates

    def find_assembly_objects(self, assembly):
        # Find the IfcRelAggregates entity that references this assembly
        ifc_rel_aggregates = self.find_ifc_rel_aggregates(assembly)

        related_objects = ifc_rel_aggregates.RelatedObjects

        for object in related_objects:
            self.G.add_node(object.id(), entity=object)
            self.G.add_edge(object.id(), ifc_rel_aggregates.id())
        
        return related_objects

    def find_material(self, object):
        # get the IfcRelAssociatesMaterial entity that references this object
        ifc_rel_associates_material = None
        for entity in self.ifc_model.get_inverse(object):
            if entity.is_a() == "IfcRelAssociatesMaterial":
                ifc_rel_associates_material = entity
                print(f"Found {ifc_rel_associates_material}\nfor {object}")
                self.G.add_node(entity.id(), entity=entity)
                self.G.add_edge(object.id(), entity.id())
                break

       # TODO: Truncate the reference list in ifc_rel_associates_material to only include the objects we are exporting 
        if ifc_rel_associates_material:
            material = ifc_rel_associates_material.RelatingMaterial
            self.G.add_node(material.id(), entity=material)
            self.G.add_edge(ifc_rel_associates_material.id(), material.id())
            return ifc_rel_associates_material.RelatingMaterial

        return "NO MATERIAL"

    def export_assemblies_to_file(self):
        output_path = self.file_path_combo.currentText()

        print(f"Exporting {len(self.G)} entities to {output_path}")
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding

        output_model = ifcopenshell.file(schema=self.ifc_model.schema) # Ideally, this program is schema agnostic

        # Get IfcProject
        project = self.ifc_model.by_type("IfcProject")[0] # by_type() returns a list but there is only one IfcProject so we take the first element
        children = self.get_children(project)
        parents = list(self.ifc_model.get_inverse(project))
        # Combine the forward and reverse references of the IfcProject entity
        entities_to_add = children + parents

        # Add the IfcProject entity and its directly related entities
        for entity in entities_to_add:
            output_model.add(entity)
        
        # Get IfcBuilding
        building = self.ifc_model.by_type("IfcBuilding")[0]        
        children = self.get_children(building)
        parents = list(self.ifc_model.get_inverse(building))
        entities_to_add = children + parents

        # add the IfcBuilding entity and its directly related entities
        for entity in entities_to_add:
            output_model.add(entity)

        # Add the assemblies we want to export
        for node in self.G.nodes:
            output_model.add(self.G.nodes[node]['entity'])
        
        # Remove IfcGrid and IfcGridAxis
        # TODO: Make this a toggle
        for entity in list(output_model):
            if entity.is_a() in ("IfcGridAxis", "IfcGrid"):
                output_model.remove(entity)
            
        output_model.write(output_path)
            
    def get_children(self, entity):
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
            elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
                children.extend([v for v in value if isinstance(v, ifcopenshell.entity_instance)])
        return children
    
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