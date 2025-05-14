from collections import defaultdict
from collections.abc import Iterable
import ifcopenshell
from PySide6.QtWidgets import (
    QTableView, QLabel, QHeaderView, QDockWidget, QMainWindow, QWidget, QVBoxLayout,
    QAbstractItemView, QPushButton
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel

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

        self.title = title
        self.ifc_model = ifc_model
        if self.title:
            self.setWindowTitle(f"Assemblies found in {self.title}")
        else:
            self.setWindowTitle("Assembly Viewer")

        self.resize(600, 400)

        self.ifc_model = ifc_model
        central_widget = QWidget()
        layout = QVBoxLayout(central_widget)

        self.instructions = QLabel("Select the assemblies to be exported")
        self.instructions.setWordWrap(True)

        self.add_assembly_export_button()

        layout.addWidget(self.instructions)
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

    def add_assembly_export_button(self):
        self.assembly_export_button = QPushButton("Export", self)
        self.assembly_export_button.clicked.connect(self.export_assemblies)

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
        for entity in selected_entities:
            # Add the forward references of the starting entity to the graph
            self.add_forward_references_to_graph(entity)
            # Add the reverse references of the starting entity to the graph
            self.add_reverse_references_to_graph(entity)

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
        #       TODO: Preferably with a file save dialog
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
            elif str(value) == "RelatedObjects":
                for item in value:
                    if isinstance(item, ifcopenshell.entity_instance):
                        self.G.add_edge(entity.id(), item.id())
                        self.add_forward_references_to_graph(item)
    
    def add_reverse_references_to_graph(self, entity):
        self.G.add_node(entity.id(), entity=entity)

        for referrer in self.ifc_model.get_inverse(entity):
            self.add_reverse_references_to_graph(referrer)
            self.add_forward_references_to_graph(referrer)

    def export_assemblies_to_file(self):
        output_path = "assemblies.ifc"

        print(f"Exporting {len(self.G)} entities to {output_path}")
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding

        output_model = ifcopenshell.file(schema="IFC2X3")

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
        parents = self.ifc_model.get_inverse(assembly)
        for parent in parents:
            if parent.is_a() == "IfcRelDefinesByProperties":
                property_set = parent.RelatingPropertyDefinition
                for property in property_set.HasProperties:
                    if property.is_a("IfcPropertySingleValue"):
                        if property.Name == "AssemblyMark":
                            return property.NominalValue.wrappedValue

        return "NO ASSEMBLY MARK"