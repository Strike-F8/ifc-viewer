# IFC Browser
PySide6 program for analyzing IFC files.  
Uses ifcopenshell for all backend analysis and SQLite for displaying, filtering, and sorting entities in the main view.  

Extends Qt UI Classes by implementing automatic translation so translation logic occurs almost exclusively in the UI logic rather than the main application.  

## Dependencies
#### Python 3.12
#### ifcopenshell
#### PySide6
#### apsw
#### networkx (Only for the graph which is not currently used)

## Files
For easier maintenance and readability, the program is split up into the following files.  

### IFCBrowser.py
This is the main view.  

### translations/strings.py
Contains all user-facing strings used in the program. They have been organized for easy translation as much as possible.  

### exporter/export_view.py
A new window that displays all assemblies (or possibly other types of items) contained in the IFC file.
The user can select assemblies for export and choose the export file path and various options for exporting.   

### exporter/ifc_graph_viewer.py
This file is not currently used for anything. It is supposed to show a graph illustrating the relationships between  
the entities the user chooses for export but the graph is hard to read and not very useful.  
At some point, I would like to make a proper graph.

### tui.py
Contains the classes that extend Qt's built in ui classes.
The purpose of this is to provide classes that translate themselves
upon receiving translation signals while maintaining the ability to
serve as drop-in replacements for Qt's built in classes.  
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
Changing the language emits a signal that classes in tui.py should
respond to by translating themselves.

### /translations
This folder contains the .ts and .qm files for supporting translation.

### /fonts
Contains a variable font that could possibly be used for animations or other fancy things but Qt doesn't seem to support that(?).

### config.json
The program generates a config.json file for keeping track of recently
opened and exported IFC files between sessions.

## Install
Download the release zip file and extract it. There are a large amount of necessary files within the archive but the actual executable is IFCBrowser.exe. It should run without any setup.

## Build
Ensure all previously mentioned dependencies are installed in your python environment. To prevent long compile times and ballooning file sizes, create a fresh virtual environment.  
```
conda create -n ifcbrowser
conda activate ifcbrowser
```  

Install Python 3.12. ifcopenshell does not yet support 3.13.

```
conda install python=3.12
```
Install dependencies
```
pip install ifcopenshell pyside6 apsw
```
At this point, you should be set to run IFCBrowser.py in your Python environment.
To build, install nuitka
```
pip install nuitka
```
And build using this command
```
nuitka --lto=yes --standalone --deployment --enable-plugin=pyside6 --include-data-files=translations/*.qm=translations/ --include-data-files=fonts/*.ttf=fonts/ --windows-console-mode=disable .\IFCBrowser.py
```
A fresh environment should create a .dist folder totalling to about 175 MB.