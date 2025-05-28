# IFC Viewer
PySide6 program for analyzing IFC files.  
Uses ifcopenshell for all backend analysis and SQLite for displaying, filtering, and sorting entities in the main view.  

Extends Qt UI Classes by implementing automatic translation so translation logic occurs almost exclusively in the UI logic rather than the main application.  

## Dependencies
#### ifcopenshell
#### PySide6
#### apsw
#### networkx

## Files
For easier maintenance and readability, the program is split up into the following files.
### 3columnifcview.py
This is the main view. It connects each part of the program but contains as little logic as possible.  

### strings.py
Contains all user-facing strings used in the program. They have been organized for easy translation as much as possible.

### assembly_viewer.py
A new window that displays all assemblies contained in the IFC file.
The user can select assemblies for export and view the relationships
between entities in the assembly on a graph.
However, assemblies always have a huge amount of relationships so the
graph is almost always hard to read and not very useful so it is set to off by default.
There are plans to improve this graph.

### ui.py
Contains the classes that extend Qt's built in ui classes.
The purpose of this is to provide classes that translate themselves
upon receiving translation signals while maintaining the ability to
serve as drop-in replacements Qt's built in classes.  
For example, QAction is extended by TAction. The TAction class  
can be instantiated with the exact same syntax as a QAction
but if you pass in a key that is recognized by QLinguist it should
translate itself when called to do so.

### db.py
The database backend for the middle view of the main window.  
Real world IFC files are enormous so rather than relying on Qt's models
to display the data, use SQLite to dynamically filter, sort, and return
elements from the database.  
While it can slow down with models that contain millions of entities,
it should remain fairly useable.

### options.py
An options dialog for changing various settings.  
Currently, it only changes the language.  
Changing the language emits a signal that classes in ui.py should
respond to by translating themselves.

### /translations
This folder contains the .ts and .qm files for supporting translation.

### config.json
The program generates a config.json file for keeping track of recently
opened IFC files between sessions.