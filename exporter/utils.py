import os
import sys
import ifcopenshell
import subprocess
import platform

from _collections_abc  import Iterable
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt

def is_compiled():
    return "__compiled__" in globals()

def open_new_ifc_viewer(file_path=None):
    system = platform.system()

    if is_compiled():
        target = sys.argv[0]
        args = [target]
    else:
        target = os.path.abspath("IFCViewer.py")
        args = [sys.executable, target]

    if file_path:
        args.append(str(file_path))

    print("Launching:", target, "with args:", args)

    if system == "Windows":
        subprocess.Popen(args, creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP, close_fds=True)
    elif system == "Darwin":
        subprocess.Popen(args, close_fds=True)
    else:
        subprocess.Popen(args, preexec_fn=os.setpgrp, close_fds=True)

        
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

def p_find_ifc_rel_aggregates(product):
    for relation in product.Decomposes:
        if relation.is_a("IfcRelAggregates"):
            return relation
    could_not_find("IfcRelAggregates", product)
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
                return [material, assoc]
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

def get_children_recursive(entity, children=None):
    if children is None:
        children = []

    for attr, value in entity.get_info().items():
        if attr in ("id", "type", "Name", "Description", "GlobalId"):
            continue

        if isinstance(value, ifcopenshell.entity_instance):
            children.append(value)
            get_children_recursive(value, children)
        elif isinstance(value, Iterable) and not isinstance(value, (str, bytes)):
            for v in value:
                if isinstance(v, ifcopenshell.entity_instance):
                    children.append(v)
                    get_children_recursive(v, children)

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

# =====================
# CONTEXT MENU
# =====================

def copy_step_line(entity):
    QApplication.clipboard().setText(str(entity))

def copy_step_id(entity):
    QApplication.clipboard().setText('#' + str(entity.id()))

def copy_guid(entity):
    QApplication.clipboard().setText(str(entity.GlobalId))

def copy_row_text(view, row):
    model = view.model()
    column_count = model.columnCount()
    row_text = []

    for col in range(column_count):
        index = model.index(row, col)
        text = model.data(index, Qt.DisplayRole)
        if text:
            row_text.append(str(text))

    QApplication.clipboard().setText("\t".join(row_text))