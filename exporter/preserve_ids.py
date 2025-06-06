import ifcopenshell
from PySide6.QtCore import QThread, Signal
from _collections_abc import Iterable
from .utils import *

class PreserveIDExportWorker(QThread):
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
        # Get selected entities
        print("PreserveIDExportWorker:")
        print("Exporting the following assemblies:")
        for entity in self.entities_to_export:
            print(entity.id())
        print(f"{len(self.entities_to_export)} entities")

        # TODO: Add an ifc version selector
        self.output_model = ifcopenshell.file(schema="IFC4X3")

        # Add assemblies and their objects
        objects = []
        for assembly in self.entities_to_export:
            add_to_model(assembly, self.output_model, preserve_id=True)
            rel_agg = find_ifc_rel_aggregates(assembly)
            add_to_model(rel_agg, self.output_model, preserve_id=True)
            temp = find_assembly_objects(rel_agg)
            add_list_to_model(temp, self.output_model, preserve_id=True)
            objects.extend(temp)

        # Find related entities for each assembly
        for element in self.entities_to_export:
            add_ifc_rel_contained_in_spatial_structure(element, self.entities_to_export, self.output_model)
        
        # Find related entities for each object
        for object in objects:
            add_ifc_rel_defines_by_properties(object, self.entities_to_export, self.output_model)
            add_material(object, self.entities_to_export, self.output_model)
            rel_voids = find_rel_voids_elements(object)
            add_list_to_model(rel_voids, self.output_model, preserve_id=True)

            for rel_void in rel_voids:
                add_list_to_model(find_opening(rel_void), self.output_model, preserve_id=True)

            add_list_to_model(get_children_recursive(object), self.output_model, preserve_id=True)

        self.export_assemblies_to_file()
        self.finished.emit([self.export_path])

    # Add a given entity to the networkx graph
    # Call this method rather than inserting manually
#    def add_entity_to_graph(self, entity, source=None, color=None):
#        self.G.add_node(entity.id(), entity=entity, color=color or 'default')
#        if source:
#            self.G.add_edge(source.id(), entity.id())
#
       
    def export_assemblies_to_file(self):
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding, IfcSite

        entity_types = [
            "IfcProject",
            "IfcBuilding",
            "IfcSite",
            "IfcOrganization",
            "IfcPerson"
        ]

        for type in entity_types:
            add_list_to_model(find_related_entities(type, self.ifc_model), self.output_model, preserve_id=True)

       # Add the assemblies we want to export
       # print("OUTPUTTING FROM GRAPH")
       # for node_id, node_attributes in self.G.nodes(data=True):
       #     entity = node_attributes.get("entity")
       #     print(f"Outputting {entity}")
       #     if entity:
       #         self.add_to_output_model(entity)
        
        check_references(self.output_model) # Check if forward references are missing

        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle:
            remove_grids(self.output_model)

        self.output_model.write(self.export_path)