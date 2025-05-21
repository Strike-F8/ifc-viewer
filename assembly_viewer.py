from collections import defaultdict
from collections.abc import Iterable
import ifcopenshell

from PySide6.QtWidgets import (
    QTableView, QLabel, QHeaderView, QDockWidget, QMainWindow, QWidget, QVBoxLayout, QCheckBox,
    QAbstractItemView, QPushButton, QFileDialog, QHBoxLayout, QComboBox, QComboBox, QSizePolicy
)
from PySide6.QtCore import Qt, QModelIndex, QAbstractTableModel, QSettings

import networkx as nx
from ifc_graph_viewer import IFCGraphViewer

def is_iterable(obj):
    return isinstance(obj, Iterable) and not isinstance(obj, (str, bytes))

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
    
    def add_toggles(self):
        self.graph_toggle_checkbox = QCheckBox("Draw Graph")        
        self.graph_toggle_checkbox.setChecked(False)

        self.grid_toggle_checkbox = QCheckBox("Export Grids")
        self.grid_toggle_checkbox.setChecked(False)

        self.toggle_layout = QHBoxLayout()

        self.grid_toggle_checkbox.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_layout.addWidget(self.graph_toggle_checkbox)
        self.toggle_layout.addWidget(self.grid_toggle_checkbox) 

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

    # Triggered by the export button
    def export_assemblies(self):
        # 1. Get the list of selected assemblies
        selected_indexes = self.assembly_table.selectionModel().selectedRows()
        selected_entities = []

        # Use the indexes to get the actual entities that were selected
        for index in selected_indexes:
            entity = self.model.data(index, Qt.UserRole)
            if entity:
                selected_entities.append(entity)

        print("Exporting the following assemblies:")
        for entity in selected_entities:
            print(entity)
            
        # Create the output model that will be used to export the assemblies
        self.output_model = ifcopenshell.file(schema=self.ifc_model.schema) # Ideally, this program is schema agnostic

        self.G.clear() # Reset the graph for the new export
        assembly_objects = []
        for assembly in selected_entities:
            # add the current assembly to the graph
            self.G.add_node(assembly.id(), entity=assembly, color='red') # Color as red because it is one of the assemblies selected by the user

            # Get the IfcRelContainedInSpatialStructure for each assembly
            self.find_ifc_rel_contained_in_spatial_structure(assembly, selected_entities)

            # Get the IfcRelDefinesByProperties entities for each assembly
            self.find_ifc_rel_defines_by_properties(assembly, selected_entities)

            # Find the objects that make up the current assembly 
            assembly_objects.extend(self.find_assembly_objects(assembly))

        for object in assembly_objects:
            # Get the materials for each object
            self.find_material(object, assembly_objects)
            # Get the voids\opening elements for each object
            self.find_voids_elements(object)

            # Get the children of each object (Geometry)
            children = self.get_children(object)
            for child in children:
                self.G.add_node(child.id(), entity=child)
                self.G.add_edge(object.id(), child.id())
            
            # Get the IfcRelDefinesByProperties of each object
            self.find_ifc_rel_defines_by_properties(object, assembly_objects)

        # 3. TODO: Save related entities with their original step ids (Does not seem to be possible with ifcopenshell)
        # 4. Output to a new IFC file
        self.export_assemblies_to_file()

        # Optionally, visualize graph using graphics view
        if self.graph_toggle_checkbox.isChecked():
            self.viewer = IFCGraphViewer(self.G, selected_entities)
            # Add to a dockable widget
            if self.title:
                dock = QDockWidget(f"Graph of {self.title}", self)
            else:
                dock = QDockWidget("Graph view", self)
                
            dock.setWidget(self.viewer)
            self.addDockWidget(Qt.RightDockWidgetArea, dock)

    def find_ifc_rel_aggregates(self, assembly):
        ifc_rel_aggregates = None
        
        for entity in assembly.IsDecomposedBy:
            if entity.is_a("IfcRelAggregates"):
                ifc_rel_aggregates = entity
                print(f"Found {ifc_rel_aggregates}\nfor {assembly}")
                break

        if ifc_rel_aggregates:
            self.G.add_node(ifc_rel_aggregates.id(), entity=ifc_rel_aggregates)
            self.G.add_edge(assembly.id(), ifc_rel_aggregates.id())
            return ifc_rel_aggregates

        return None
    
    def find_assembly_objects(self, assembly):
        # Find the IfcRelAggregates entity that references this assembly
        ifc_rel_aggregates = self.find_ifc_rel_aggregates(assembly)

        related_objects = ifc_rel_aggregates.RelatedObjects

        for object in related_objects:
            self.G.add_node(object.id(), entity=object)
            self.G.add_edge(object.id(), ifc_rel_aggregates.id())
        
        return related_objects

    def find_voids_elements(self, object):
        rel_voids_elements = object.HasOpenings
        for rel_voids_element in rel_voids_elements:
            # Add the IfcRelVoidsElement to the graph
            self.G.add_node(rel_voids_element.id(), entity=rel_voids_element)
            self.G.add_edge(object.id(), rel_voids_element.id())
            voids_element = rel_voids_element.RelatedOpeningElement
            self.G.add_node(voids_element.id(), entity=voids_element)
            self.G.add_edge(rel_voids_element.id(), voids_element.id())
    
    # Find the referencing IfcRelContainedInSpatialStructure entities of the given entity
    # These referencing entities reference many other objects that we may not want
    # so the user can pass in a list of related objects to be included. All others are removed
    def find_ifc_rel_contained_in_spatial_structure(self, entity, entities=None):
        relations = entity.ContainedInStructure
        print(f"{entity} is contained in:")
        for relation in relations:
            print(relation)
            # Remove the references to entities we did not select
            if entities:
                related_elements = relation.RelatedElements
                intersection = list(set(related_elements).intersection(entities))
                print(f"Only keeping these references:\n{intersection}")
                relation.RelatedElements = intersection
                self.output_model.add(relation)
                relation.RelatedElements = related_elements # Revert the related elements in the original model to prevent corruption
            self.G.add_node(relation.id(), entity=relation)
            self.G.add_edge(entity.id(), relation.id())

    # Find the referencing IfcRelDefinesByProperties entities of the given entity
    # These referencing entities reference many other objects that we may not want
    # so the user can pass in a list of related objects to be included. All others are removed
    def find_ifc_rel_defines_by_properties(self, entity, entities=None):
        relations = entity.IsDefinedBy
        print(f"{entity} is defined by:")
        for relation in relations:
            print(relation)
            # Remove the references to entities we are not exporting
            if entities:
                related_objects = relation.RelatedObjects
                intersection = list(set(related_objects).intersection(entities))
                print(f"Only keeping these references:\n{intersection}")
                relation.RelatedObjects = intersection
                self.output_model.add(relation)
                relation.RelatedObjects = related_objects # Revert the related objects in the original model to prevent corruption
            self.G.add_node(relation.id(), entity=relation)
            self.G.add_edge(entity.id(), relation.id())
    
    def find_material(self, object, objects=None):
        # get the IfcRelAssociatesMaterial entity that references this object
        ifc_rel_associates_material = None
        for entity in object.HasAssociations:
            if entity.is_a("IfcRelAssociatesMaterial"):
                ifc_rel_associates_material = entity
                print(f"Found {ifc_rel_associates_material}\nfor {object}")
                # Remove the references to objects we are not exporting
                if objects:
                    related_objects = entity.RelatedObjects
                    intersection = list(set(related_objects).intersection(objects))
                    entity.RelatedObjects = intersection
                    print(f"Only keeping these references:\n{intersection}")
                    self.output_model.add(entity)
                    entity.RelatedObjects = related_objects # Revert the change to prevent corruption in the original model
                self.G.add_node(entity.id(), entity=entity)
                self.G.add_edge(object.id(), entity.id())
                break

        if ifc_rel_associates_material:
            material = ifc_rel_associates_material.RelatingMaterial
            self.G.add_node(material.id(), entity=material)
            self.G.add_edge(ifc_rel_associates_material.id(), material.id())
            return material

        return "NO MATERIAL"

    def export_assemblies_to_file(self):
        output_path = self.file_path_combo.currentText()

        print(f"Exporting {len(self.G)} entities to {output_path}")
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding

        # Get IfcProject
        project = self.ifc_model.by_type("IfcProject")[0] # by_type() returns a list but there is only one IfcProject so we take the first element
        children = self.get_children(project)
        parents = list(self.ifc_model.get_inverse(project))
        # Combine the forward and reverse references of the IfcProject entity
        entities_to_add = children + parents

        # Add the IfcProject entity and its directly related entities
        for entity in entities_to_add:
            self.output_model.add(entity)
        
        # Get IfcBuilding
        building = self.ifc_model.by_type("IfcBuilding")[0]        
        children = self.get_children(building)
        parents = list(self.ifc_model.get_inverse(building))
        entities_to_add = children + parents

        # add the IfcBuilding entity and its directly related entities
        for entity in entities_to_add:
            self.output_model.add(entity)

        # Add the assemblies we want to export
        for node_id, node_attributes in self.G.nodes(data=True):
            entity = node_attributes.get("entity")
            print(f"Outputting {entity}")
            self.output_model.add(entity)
        
        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle_checkbox.isChecked():
            for entity in self.output_model.by_type("IfcGridAxis"):
                self.output_model.remove(entity)
            for entity in self.output_model.by_type("IfcGrid"):
                self.output_model.remove(entity)
        
        self.output_model.write(output_path)
            
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