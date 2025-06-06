import os
import sys
import ifcopenshell
from _collections_abc import Iterable

# Open a new main window in a separate process from the file menu
def open_new_ifc_viewer(file_path=None):
    if getattr(sys, 'frozen', False):
        # We're in a compiled binary, use our own executable
        target = os.path.join(os.path.dirname(sys.executable), "IFCViewer.exe")
        if file_path:
            args = [str(target), str(file_path)]
        else:
            args = [str(target)]
        os.spawnv(os.P_DETACH, target, args)
    else:
        # We're running as a .py file, launch it with Python
        target = os.path.abspath("IFCViewer.py")
        if file_path:
            args = [str(sys.executable), str(target), str(file_path)]
        else:
            args = [str(sys.executable), str(target)]
        os.spawnv(os.P_DETACH, sys.executable, args)
        
# =====================
# IFC UTILS
# =====================

def could_not_find(ifc_type, entity):
    print(f"Could not find {ifc_type} for #{entity.id()}={entity.is_a()}")

# This method gets a relating entity that references the given entity.
# However, the relating entity also references many other entities
# so we remove the references we are not planning to export before adding
# it to the output model. Lastly, revert the change to the reference list
# to prevent corruption in the original model
# Unlike other util methods, this one does not return any entities
# It adds the result to the model passed in by the caller
def clone_relation_with_filtered_targets(relation, attr_name, allowed_targets, dest_model, preserve_id=False):
    original = getattr(relation, attr_name)
    intersection = list(set(original).intersection(allowed_targets))
    setattr(relation, attr_name, intersection)
    add_to_model(relation, dest_model, preserve_id)
    setattr(relation, attr_name, original)

def add_to_model(entity, model, preserve_id=False):
    # TODO: Check for version discrepancy
    if not preserve_id:
        return model.add(entity)
    else:
        attributes = entity.get_info()
        try:
            return model.create_entity(**attributes)
        except Exception as e:
            print(e)
            return -1

def add_list_to_model(entities, model, preserve_ids=False):
    if entities:
        for entity in entities:
            add_to_model(entity, model, preserve_ids)
    
# Given an assembly (or any entity referenced by an IfcRelAggregates entity)
# return the IfcRelAggregates entity
def find_ifc_rel_aggregates(assembly):
    for relation in assembly.IsDecomposedBy:
        if relation.is_a("IfcRelAggregates"):
            return relation
    could_not_find("IfcRelAggregates", assembly)
    return None

# Return the objects that make up a given assembly as a list
def find_assembly_objects(rel_agg):
    if rel_agg:
        return rel_agg.RelatedObjects
    else:
        could_not_find("Related Objects", rel_agg)
        return None

# Return the IfcRelVoidsElements associated with a given object as a list
def find_rel_voids_elements(object):
    return object.HasOpenings    

# Find the openings contained within an IfcRelVoidsElements
def find_opening(rel_voids):
    return rel_voids.RelatedOpeningElement

# Every assembly is referenced by an IfcRelContainedInSpatialStructure entity
# which provides spatial data within the model for the assembly
# However, this referencing entity also references other assemblies
# so we make sure only to keep the references of assemblies we want to export
def add_ifc_rel_contained_in_spatial_structure(entity, allowed_entities, model, preserve_id=False):
    for relation in entity.ContainedInStructure:
        clone_relation_with_filtered_targets(relation, "RelatedElements", allowed_entities, model, preserve_id)

def add_ifc_rel_defines_by_properties(entity, allowed_entities, model, preserve_id=False):
    for relation in entity.IsDefinedBy:
        clone_relation_with_filtered_targets(relation, "RelatedObjects", allowed_entities, model, preserve_id)

# Given an entity and model, add the IfcRelAssociatesMaterial and IfcMaterial of the object to the model
# Also return the IfcMaterial
def add_material(entity, allowed_entities, model, preserve_id=False):
    for assoc in entity.HasAssociations:
        if assoc.is_a("IfcRelAssociatesMaterial"):
            clone_relation_with_filtered_targets(assoc, "RelatedObjects", allowed_entities, model, preserve_id)

            material = assoc.RelatingMaterial
            if material:
                return material
    could_not_find("IfcMaterial", entity)
    return None

def get_children(entity):
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

def get_children_recursive(entity):
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
            children.extend(get_children_recursive(value))
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for v in value:
                if isinstance(v, ifcopenshell.entity_instance):
                    children.append(v)
                    children.extend(get_children_recursive(v))

    return children

# Return the parents one level up and the recursive children of a given entity type
def find_related_entities(entity_type, model):
    entities = model.by_type(entity_type)
    entities_to_add = []
    for entity in entities:
        children = get_children_recursive(entity)
        parents = list(model.get_inverse(entity))
        # Combine the forward and reverse references of the IfcProject entity
        entities_to_add.extend(children + parents)

        return entities_to_add

def remove_grids(model):
    for entity in model.by_type("IfcGridAxis"):
        model.remove(entity)
    for entity in model.by_type("IfcGrid"):
        model.remove(entity)

# Read the forward references of entities in a model and check if they are missing
def check_references(model):
    for entity in model:
        for attr in entity.get_info().keys():
            if attr in ("id", "type", "Name", "Description", "GlobalId"):
                continue
            try:
                val = getattr(entity, attr)
            except AttributeError:
                continue
            if isinstance(val, ifcopenshell.entity_instance):
                try:
                    temp = model.by_id(val.id())
                except:
                    add_to_model(val, model)
                    children = get_children_recursive(val)
                    for child in children:
                        if add_to_model(child, model) == -1: # Stop adding if children already exist TODO: often skips important entities
                            break
                    print(f"{val.id()}: was missing so added to model\n+ {len(children)} children")
            elif isinstance(val, Iterable) and not isinstance(val, (str, bytes)):
                for v in val:
                    try:
                        if isinstance(v, ifcopenshell.entity_instance):
                            temp = model.by_id(v.id())
                    except:
                        add_to_model(v, model)
                        children = get_children_recursive(v)
                        for child in children:
                            if add_to_model(child, model) == -1:
                                break
                        print(f"{v.id()}: was missing so added to model\n+ {len(children)} children")
