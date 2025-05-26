import sys
from ui import language_manager

from PySide6.QtWidgets import (
    QLabel, QPushButton, QVBoxLayout, QHBoxLayout,
    QDialog, QComboBox
)
from PySide6.QtCore import Signal

class OptionsDialog(QDialog):
    def __init__(self, title="Options"):
        super().__init__()
        self.setWindowTitle(self.tr(title))

        self.resize(600, 400)
        self.main_layout = QVBoxLayout(self)

        self.add_language_selector()
    
    def add_language_selector(self):
        self.language_selector = QComboBox()
        # Add languages to the list of selectable languages
        self.language_selector.addItem("English", "en")
        self.language_selector.addItem("日本語", "jp")
        # Send a signal to the main application when the user selects a language
        self.language_selector.currentIndexChanged.connect(self.emit_language_change)

        self.language_selector_layout = QHBoxLayout()
        self.language_label = QLabel("Language")
        self.language_selector_layout.addWidget(self.language_label)
        self.language_selector_layout.addWidget(self.language_selector)
        self.main_layout.addLayout(self.language_selector_layout)
    
    def emit_language_change(self):
        language_code = self.language_selector.currentData()
        language_manager.language_changed.emit(language_code) # notify the ui that the language changed