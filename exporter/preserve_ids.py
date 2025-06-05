import ifcopenshell
from PySide6.QtCore import QThread, Signal
from _collections_abc import Iterable

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
        self.finished.emit([self.export_path])

    # ----------------------
    # Helper methods below
    # ----------------------

    # Add a given entity to the networkx graph
    # Call this method rather than inserting manually
#    def add_entity_to_graph(self, entity, source=None, color=None):
#        self.G.add_node(entity.id(), entity=entity, color=color or 'default')
#        if source:
#            self.G.add_edge(source.id(), entity.id())
#
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
       # print("OUTPUTTING FROM GRAPH")
       # for node_id, node_attributes in self.G.nodes(data=True):
       #     entity = node_attributes.get("entity")
       #     print(f"Outputting {entity}")
       #     if entity:
       #         self.add_to_output_model(entity)
        
        
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
