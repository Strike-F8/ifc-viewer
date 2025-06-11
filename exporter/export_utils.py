from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt
import ifcopenshell

# =========================
# ASSEMBLY UTILITIES
# =========================

class AssemblyTableModel(QAbstractTableModel):
    def __init__(self, objects, parent=None, headers=["STEP ID",
                                                      "Assembly Mark",
                                                      "GlobalId",
                                                      "Name",
                                                      "Type"]):
        super().__init__(parent)
        self.headers = headers
        self.data_list = []
        self.objects = objects # The list of objects to display in the exporter
        self.populate_objects()

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
    
    def populate_objects(self):
        # Add the objects to the main list of the exporter
        for mark, entities in self.objects.items():
            for entity in entities:
                info = entity.get_info()
                step_id = "#" + str(entity.id())
                global_id = info.get("GlobalId", "")
                name = info.get("Name", "")
                ifc_type = entity.is_a()
                self.data_list.append([step_id, mark, global_id, name, ifc_type, entity])

# Find all assemblies in the ifc file
# Return the assemblies as a dictionary
# Key: Assembly mark, Value: IFCElementAssembly
def find_assemblies(model):
    # Each IfcElementAssembly represents one assembly
    # So does each IfcRelAggregates
    from collections import defaultdict

    assemblies = model.by_type("IfcElementAssembly")

    print(f"Found {len(assemblies)} assemblies")
    
    # store assemblies with their info i.e. assembly mark and step line id
    result = defaultdict(list)
    
    # Find the assembly mark for each assembly and add them to the result dictionary
    for assembly in assemblies:
        result[get_assembly_mark(assembly)].append(assembly)

    return result

# Returns the corresponding assembly mark for the given IfcElementAssembly
def get_assembly_mark(assembly):
    # TODO: If the assembly mark is not stored in a property, check the name of the IfcElementAssembly
    for parent in assembly.IsDefinedBy: # Use a precomputed reverse index instead of get_inverse
        if parent.is_a("IfcRelDefinesByProperties"):
            property_set = parent.RelatingPropertyDefinition
            for property in property_set.HasProperties:
                if property.is_a("IfcPropertySingleValue"):
                    if property.Name == "AssemblyMark":
                        return property.NominalValue.wrappedValue

    return "NO ASSEMBLY MARK"

# =========================
# PHASE UTILITIES
# =========================

class PhaseTableModel(QAbstractTableModel):
    def __init__(self, objects, parent=None):
        super().__init__(parent)

        self.headers = [
            "STEP ID",
            "Phase",
            "GlobalId",
            "Type"
            ]

        self.data_list = []
        self.objects = objects # The list of objects to display in the exporter
        self.populate_objects()

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
    
    def populate_objects(self):
        # Add the objects to the main list of the exporter
        # Takes in a dictionary of IfcPropertySingleValue or IfcPresentationLayerAssignment
        # Key: phase name or number, value: entity
        # TODO: Display both phase name and number if possible
        for phase, entity in self.objects.items():
            print(entity)
            info = entity.get_info()
            step_id = "#" + str(entity.id())
            global_id = info.get("GlobalId", "")
            ifc_type = entity.is_a()
            self.data_list.append([step_id, phase, global_id, ifc_type, entity])

# Return a list of all the phases within the given ifc model 
def find_phases(model):
    # Tekla often outputs phases as layers
    ifc_presentation_layer_assignments = model.by_type("IfcPresentationLayerAssignment")
    if len(ifc_presentation_layer_assignments) > 0:
        phases = []
        for layer in ifc_presentation_layer_assignments:
            name = layer.Name.lower()
            if "grid" not in name: # Grids are also sometimes output as layers so we remove them
                phases.append(layer)
        if len(phases) > 0:
            # dictionary of phases
            # Key: Phase Name, Value: List of entities that make up the phase
            result = {}
            for phase in phases:
                result[phase.Name] = phase
            return result
    
    print("Phases are not stored in layers!\nChecking properties next...")
    # If we didn't find any phases yet check another way of finding phases
    ifc_property_single_values = model.by_type("IfcPropertySingleValue")
    phases = {}
    for property in ifc_property_single_values:
        if property.Name.lower() == "phase":
            phases[str(property.NominalValue.wrappedValue)] = property
    if len(phases) > 0:
        return phases 

    print("Unable to find phases")
    return "Unable to find phases"

# Given an IfcPropertySingleValue that contains a phase number,
# Return all the info we can find about the phase
# Objects, etc.
def get_phase_by_property(ifc_property_single_value):
    attributes = ifc_property_single_value.get_info()
    print(f"Printing the attributes of {ifc_property_single_value}")
    for attribute in attributes:
        print(attribute)

# Given an IfcPresentationLayerAssignement that contains a phase name,
# Return all the info we can find about the phase
# Objects, etc.
def get_phase_by_layer(ifc_presentation_layer_assignment):
    attributes = ifc_presentation_layer_assignment.get_info()
    print(f"Printing the attributes of {ifc_presentation_layer_assignment.id()}")
    for attribute in attributes:
        print(attribute)

# =========================
# GENERAL UTILITIES
# =========================

# Convert one model to another schema
# Converting to an older schema will probably not work
def convert_schema_to(input_file, output_file, new_schema):
    #TODO: Create a help dialog with info about conversion
    old_model = ifcopenshell.open(input_file)
    new_model = ifcopenshell.file(schema=new_schema)

    for entity in old_model:
        add_to_output_model(entity, new_model)
    
    print(f"Writing new file to {output_file}")
    new_model.write(output_file)

# Instead of copying entities to the new model, create new entities with the same attributes
# Useful for changing IFC versions
def add_to_output_model(entity, new_model):
    attributes = entity.get_info()
    try:
        return new_model.create_entity(**attributes)
    except Exception as e:
        print(e)
        return -1