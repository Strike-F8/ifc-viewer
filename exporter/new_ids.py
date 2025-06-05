import ifcopenshell
from PySide6.QtCore import QThread, Signal
from _collections_abc import Iterable

class NewIDExportWorker(QThread):
    progress = Signal(int)
    finished = Signal(list)

    def __init__(self, entities_to_export, export_path, original_model,
                 grid_toggle=False):
        super().__init__()
        self.entities_to_export = entities_to_export
        self.export_path = export_path
        self.ifc_model = original_model
        self.grid_toggle = grid_toggle

    # Triggered by the export button
    def run(self):
        print("NewIDExportWorker:")
        print("Exporting the following assemblies")
        for entity in self.entities_to_export:
            print(entity.id())
        print(f"{len(self.entities_to_export)} entities")

        # Create the output model that will be used to export the assemblies
        self.output_model = ifcopenshell.file(schema=self.ifc_model.schema) # Ideally, this program is schema agnostic

        assembly_objects = []
        for assembly in self.entities_to_export:
            # add the current assembly to the new model
            self.add_to_output_model(assembly)

            # Get the IfcRelContainedInSpatialStructure for each assembly
            self.find_ifc_rel_contained_in_spatial_structure(assembly, self.entities_to_export)

            # Get the IfcRelDefinesByProperties entities for each assembly
            self.find_ifc_rel_defines_by_properties(assembly, self.entities_to_export)

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
                self.add_to_output_model(child)
            
            # Get the IfcRelDefinesByProperties of each object
            self.find_ifc_rel_defines_by_properties(object, assembly_objects)

        # 3. TODO: Save related entities with their original step ids (Does not seem to be possible with ifcopenshell)
        # 4. Output to a new IFC file
        self.export_assemblies_to_file()

    def find_ifc_rel_aggregates(self, assembly):
        ifc_rel_aggregates = None
        
        for entity in assembly.IsDecomposedBy:
            if entity.is_a("IfcRelAggregates"):
                ifc_rel_aggregates = entity
                #print(f"Found {ifc_rel_aggregates}\nfor {assembly}")
                break

        if ifc_rel_aggregates:
            self.add_to_output_model(ifc_rel_aggregates)
            return ifc_rel_aggregates

        return None
    
    def find_assembly_objects(self, assembly):
        # Find the IfcRelAggregates entity that references this assembly
        ifc_rel_aggregates = self.find_ifc_rel_aggregates(assembly)

        related_objects = ifc_rel_aggregates.RelatedObjects

        for object in related_objects:
            self.add_to_output_model(object)
        
        return related_objects

    def find_voids_elements(self, object):
        rel_voids_elements = object.HasOpenings
        for rel_voids_element in rel_voids_elements:
            # Add the IfcRelVoidsElement to the graph
            self.add_to_output_model(rel_voids_element)
            voids_element = rel_voids_element.RelatedOpeningElement
            self.add_to_output_model(voids_element)
    
    # Find the referencing IfcRelContainedInSpatialStructure entities of the given entity
    # These referencing entities reference many other objects that we may not want
    # so the user can pass in a list of related objects to be included. All others are removed
    def find_ifc_rel_contained_in_spatial_structure(self, entity, entities=None):
        relations = entity.ContainedInStructure
        #print(f"{entity} is contained in:")
        for relation in relations:
            #print(relation)
            # Remove the references to entities we did not select
            if entities:
                related_elements = relation.RelatedElements
                intersection = list(set(related_elements).intersection(entities))
                #print(f"Only keeping these references:\n{intersection}")
                relation.RelatedElements = intersection
                self.add_to_output_model(relation)
                relation.RelatedElements = related_elements # Revert the related elements in the original model to prevent corruption
            else:
                self.add_to_output_model(relation)

    # Find the referencing IfcRelDefinesByProperties entities of the given entity
    # These referencing entities reference many other objects that we may not want
    # so the user can pass in a list of related objects to be included. All others are removed
    def find_ifc_rel_defines_by_properties(self, entity, entities=None):
        relations = entity.IsDefinedBy
        #print(f"{entity} is defined by:")
        for relation in relations:
            #print(relation)
            # Remove the references to entities we are not exporting
            if entities:
                related_objects = relation.RelatedObjects
                intersection = list(set(related_objects).intersection(entities))
                #print(f"Only keeping these references:\n{intersection}")
                relation.RelatedObjects = intersection
                self.add_to_output_model(relation)
                relation.RelatedObjects = related_objects # Revert the related objects in the original model to prevent corruption
            else:
                self.add_to_output_model(relation)
    
    def find_material(self, object, objects=None):
        # get the IfcRelAssociatesMaterial entity that references this object
        ifc_rel_associates_material = None
        for entity in object.HasAssociations:
            if entity.is_a("IfcRelAssociatesMaterial"):
                ifc_rel_associates_material = entity
                #print(f"Found {ifc_rel_associates_material}\nfor {object}")
                # Remove the references to objects we are not exporting
                if objects:
                    related_objects = entity.RelatedObjects
                    intersection = list(set(related_objects).intersection(objects))
                    entity.RelatedObjects = intersection
                    #print(f"Only keeping these references:\n{intersection}")
                    self.add_to_output_model(entity)
                    entity.RelatedObjects = related_objects # Revert the change to prevent corruption in the original model
                else:
                    self.add_to_output_model(entity)
                break

        if ifc_rel_associates_material:
            material = ifc_rel_associates_material.RelatingMaterial
            self.add_to_output_model(material)
            return material

        return "NO MATERIAL"

    def export_assemblies_to_file(self):
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
            self.add_to_output_model(entity)
        
        # Get IfcBuilding
        building = self.ifc_model.by_type("IfcBuilding")[0]        
        children = self.get_children(building)
        parents = list(self.ifc_model.get_inverse(building))
        entities_to_add = children + parents

        # add the IfcBuilding entity and its directly related entities
        for entity in entities_to_add:
            self.output_model.add(entity)

        # Add the assemblies we want to export
        # Remove IfcGrid and IfcGridAxis
        if not self.grid_toggle:
            for entity in self.output_model.by_type("IfcGridAxis"):
                self.output_model.remove(entity)
            for entity in self.output_model.by_type("IfcGrid"):
                self.output_model.remove(entity)
        
        self.output_model.write(self.export_path)
        self.finished.emit([self.export_path])
            
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

    def add_to_output_model(self, entity):
        # TODO: copy the entity in a way that is version agnostic
        # Right now, the output model must be the same version as the original
        self.output_model.add(entity)
        