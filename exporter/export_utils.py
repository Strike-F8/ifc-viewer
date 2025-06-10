from PySide6.QtCore import QAbstractTableModel, QModelIndex, Qt

class ExporterTableModel(QAbstractTableModel):
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
        # Mark will be different depending on the entity type
        # Assemblies have AssemblyMark
        # Other objects may have PieceMark etc.
        for mark, entities in self.objects.items():
            for entity in entities:
                info = entity.get_info()
                step_id = "#" + str(entity.id())
                global_id = info.get("GlobalId", "")
                name = info.get("Name", "")
                ifc_type = entity.is_a()
                self.data_list.append([step_id, mark, global_id, name, ifc_type, entity])

# =========================
# ASSEMBLY UTILITIES
# =========================

# Find all assemblies in the ifc file
# Return the assemblies as a dictionary
# Key: Assembly mark, Value: Entity object
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
    for parent in assembly.IsDefinedBy: # Use a precomputed reverse index instead of get_inverse
        if parent.is_a("IfcRelDefinesByProperties"):
            property_set = parent.RelatingPropertyDefinition
            for property in property_set.HasProperties:
                if property.is_a("IfcPropertySingleValue"):
                    if property.Name == "AssemblyMark":
                        return property.NominalValue.wrappedValue

    return "NO ASSEMBLY MARK"