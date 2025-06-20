import ifcopenshell
from PySide6.QtCore import QThread, Signal
from .utils import *

class AssemblyExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, entities_to_export, export_path, original_model,
                 grid_toggle=False, preserve_ids=False):
        super().__init__()
        self.entities_to_export = entities_to_export
        self.export_path = export_path
        self.ifc_model = original_model
        self.grid_toggle = grid_toggle
        self.preserve_ids = preserve_ids

    # Triggered by the export button
    def run(self):
        print("Beginning export...")
        if self.preserve_ids:
            print("Preserving original STEP IDs")
        else:
            print("Exporting with new STEP IDs")
            
        print("Exporting the following assemblies")
        for entity in self.entities_to_export:
            print(entity.id())
        print(f"{len(self.entities_to_export)} entities")

        # Create the output model that will be used to export the assemblies
        self.output_model = ifcopenshell.file(schema=self.ifc_model.schema) # Ideally, this program is schema agnostic

        assembly_objects = []
        for assembly in self.entities_to_export:
            # add the current assembly to the new model
            add_to_model(assembly, self.output_model, self.preserve_ids)

            # Get the IfcRelContainedInSpatialStructure for each assembly
            add_ifc_rel_contained_in_spatial_structure(assembly, self.entities_to_export, self.output_model, self.preserve_ids)

            # Get the IfcRelDefinesByProperties entities for each assembly
            add_ifc_rel_defines_by_properties(assembly, self.entities_to_export, self.output_model, self.preserve_ids)

            # Find the objects that make up the current assembly 
            rel_agg = find_ifc_rel_aggregates(assembly)

            if rel_agg:
                add_to_model(rel_agg, self.output_model, self.preserve_ids)
                assembly_objects.extend(find_assembly_objects(rel_agg))

        for object in assembly_objects:
            # Get the materials for each object
            add_material(object, assembly_objects, self.output_model, self.preserve_ids)
            # Get the voids\opening elements for each object
            rel_voids = find_rel_voids_elements(object)
            add_list_to_model(rel_voids, self.output_model, self.preserve_ids)

            for rel_void in rel_voids:
                add_to_model(find_opening(rel_void), self.output_model, self.preserve_ids)

            # Get the children of each object (Geometry)
            add_list_to_model(get_children(object), self.output_model, self.preserve_ids)
            
            # Get the IfcRelDefinesByProperties of each object
            add_ifc_rel_defines_by_properties(object, assembly_objects, self.output_model, self.preserve_ids)

        # 3. TODO: Save related entities with their original step ids (Does not seem to be possible with ifcopenshell)
        # 4. Output to a new IFC file
        self.export_assemblies_to_file()
        self.finished.emit([self.export_path])

    def export_assemblies_to_file(self):
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding

        # TODO: Check why the result is different when preserving IDs
        # TODO: Check if all the IDs are preserved. Some may be different
        entity_types = [
        "IfcProject",
        "IfcBuilding"
        ]

        for type in entity_types:
            add_list_to_model(find_related_entities(type, self.ifc_model), self.output_model, self.preserve_ids)
        
        # Not every necessary reference is included when preserving original IDs so go through the model
        # checking if there are missing references
        if self.preserve_ids:
            check_references(self.output_model)

        # Add the assemblies we want to export
        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle:
            remove_grids(self.output_model)

        self.output_model.write(self.export_path)

class PhaseExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, entities_to_export, export_path, original_model,
                 grid_toggle=False, preserve_ids=False):
        super().__init__()
        self.entities_to_export = entities_to_export
        self.export_path = export_path
        self.ifc_model = original_model
        self.grid_toggle = grid_toggle
        self.preserve_ids = preserve_ids

    # Triggered by the export button
    def run(self):
        print("Beginning export...")
        if self.preserve_ids:
            print("Preserving original STEP IDs")
        else:
            print("Exporting with new STEP IDs")
            
        print("Exporting the following phases")
        for entity in self.entities_to_export:
            print(entity.id())
        print(f"{len(self.entities_to_export)} entities")

        # Create the output model that will be used to export the assemblies
        self.output_model = ifcopenshell.file(schema=self.ifc_model.schema) # Ideally, this program is schema agnostic

        # Check if the list of phases is made up of layers or properties
        if self.entities_to_export[0].is_a("IfcPresentationLayerAssignment"):
            self.output_phases_as_layers()
        else:
            self.output_phases_as_properties()

    def output_phases_as_layers(self):
        phase_objects = []
        for phase in self.entities_to_export:
            # add the current phase to the new model
            add_to_model(phase, self.output_model, self.preserve_ids)

            # Find the geometry referenced by the layer
            geometry_entities = phase.AssignedItems
            # Find the objects corresponding to the geometry
            for geometry in geometry_entities:
                phase_objects.append(geometry.OfProductRepresentation[0].ShapeOfProduct[0])
            add_list_to_model(phase_objects, self.output_model, self.preserve_ids)

            # TODO: Different logic if the phase is not a layer
                    
        relation_cache = [] # Keep track of relations that were already added so we don't add them again
        for object in phase_objects:
            # Get the material for each object
            materials = add_material(object, phase_objects, self.output_model, self.preserve_ids)
            if materials[1] not in relation_cache:
                relation_cache.append(materials[1])
                add_list_to_model(materials, self.output_model, self.preserve_ids)
                
            # Get the voids\opening elements for each object
            rel_voids = find_rel_voids_elements(object)
            add_list_to_model(rel_voids, self.output_model, self.preserve_ids)

            for rel_void in rel_voids:
                add_to_model(find_opening(rel_void), self.output_model, self.preserve_ids)

            # Get the children of each object (Geometry)
            add_list_to_model(get_children(object), self.output_model, self.preserve_ids)
            
            # Get the IfcRelDefinesByProperties of each object
            add_ifc_rel_defines_by_properties(object, phase_objects, self.output_model, self.preserve_ids)

            # Get the IfcRelAggregates of each object
            rel_agg = p_find_ifc_rel_aggregates(object)
            if rel_agg not in relation_cache:
                relation_cache.append(rel_agg)
                clone_relation_with_filtered_targets(rel_agg, "RelatedObjects", phase_objects, self.output_model, self.preserve_ids)
            
        # Get the IfcElementAssembly for each IfcRelAggregates
        assembly_cache = []
        for relation in relation_cache:
            if relation.is_a("IfcRelAggregates"):
                assembly = relation.RelatingObject
                if assembly not in assembly_cache:
                    assembly_cache.append(assembly)
                    add_to_model(assembly, self.output_model, self.preserve_ids)
        
        # Get the IfcRelContainedInSpatialStructure for each IfcElementAssembly
        structure_cache = []
        for relation in assembly_cache:
            structure = relation.ContainedInStructure[0]
            if structure not in structure_cache:
                structure_cache.append(structure)
                clone_relation_with_filtered_targets(structure, "RelatedElements", assembly_cache, self.output_model, self.preserve_ids)

        # 4. Output to a new IFC file
        self.export_assemblies_to_file()
        self.finished.emit([self.export_path])

    def output_phases_as_properties(self):
        # add the phases to the model
        add_list_to_model(self.entities_to_export, self.output_model, self.preserve_ids)

        # Get the IfcRelDefinesByProperties and objects corresponding to the phases
        rel_def_props_cache = []
        phase_objects = []
        rel_def_props = self.ifc_model.by_type("IfcRelDefinesByProperties")
        for rel in rel_def_props:
            property = rel.RelatingPropertyDefinition
            if property.is_a("IfcPropertySet"):
                for prop in property.HasProperties:
                    if prop in self.entities_to_export:
                        if rel not in rel_def_props_cache:
                            rel_def_props_cache.append(rel)
                            phase_objects.extend(rel.RelatedObjects)
                            add_to_model(rel, self.output_model, self.preserve_ids)
        
        relation_cache = [] # Keep track of relations that were already added so we don't add them again
        for object in phase_objects:
            # Get the material for each object
            materials = add_material(object, phase_objects, self.output_model, self.preserve_ids)
            if materials[1] not in relation_cache:
                relation_cache.append(materials[1])
                add_list_to_model(materials, self.output_model, self.preserve_ids)
                
            # Get the voids\opening elements for each object
            rel_voids = find_rel_voids_elements(object)
            add_list_to_model(rel_voids, self.output_model, self.preserve_ids)

            for rel_void in rel_voids:
                add_to_model(find_opening(rel_void), self.output_model, self.preserve_ids)

            # Get the children of each object (Geometry)
            add_list_to_model(get_children(object), self.output_model, self.preserve_ids)
            
            # Get the IfcRelDefinesByProperties of each object
            #add_ifc_rel_defines_by_properties(object, phase_objects, self.output_model, self.preserve_ids)

            # Get the IfcRelAggregates of each object
            rel_agg = p_find_ifc_rel_aggregates(object)
            if rel_agg not in relation_cache:
                relation_cache.append(rel_agg)
                clone_relation_with_filtered_targets(rel_agg, "RelatedObjects", phase_objects, self.output_model, self.preserve_ids)
                    
        # Get the IfcElementAssembly for each IfcRelAggregates
        assembly_cache = []
        for relation in relation_cache:
            if relation.is_a("IfcRelAggregates"):
                assembly = relation.RelatingObject
                if assembly not in assembly_cache:
                    assembly_cache.append(assembly)
                    add_to_model(assembly, self.output_model, self.preserve_ids)
        
        # Get the IfcRelContainedInSpatialStructure for each IfcElementAssembly
        structure_cache = []
        for relation in assembly_cache:
            structure = relation.ContainedInStructure[0]
            if structure not in structure_cache:
                structure_cache.append(structure)
                clone_relation_with_filtered_targets(structure, "RelatedElements", assembly_cache, self.output_model, self.preserve_ids)

        # 4. Output to a new IFC file
        self.export_assemblies_to_file()
        self.finished.emit([self.export_path])

    def export_assemblies_to_file(self):
        # Prepare the model for output
        # There are certain entities that are necessary for being read by other programs
        # IfcProject, IfcBuilding

        # TODO: Check why the result is different when preserving IDs
        # TODO: Check if all the IDs are preserved. Some may be different
        entity_types = [
        "IfcProject",
        "IfcBuilding"
        ]

        for type in entity_types:
            add_list_to_model(find_related_entities(type, self.ifc_model), self.output_model, self.preserve_ids)
        
        # Not every necessary reference is included when preserving original IDs so go through the model
        # checking if there are missing references
        if self.preserve_ids:
            check_references(self.output_model)

        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle:
            remove_grids(self.output_model)

        self.output_model.write(self.export_path)