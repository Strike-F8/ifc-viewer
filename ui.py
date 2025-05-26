from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QToolBar
)
from functools import partial

class LanguageManager(QObject):
    language_changed = Signal(str)

language_manager = LanguageManager() # The global language manager
                                     # Must be imported by other files to be used

# A toolbar that translates itself upon receiving a language changed signal
class TToolBar(QToolBar):
    def __init__(self):
        super().__init__()
        language_manager.language_changed.connect(self.translate)
        self.setWindowTitle(self.tr("Main Toolbar"))
        
        self.create_actions() # Set the text for the actions on the toolbar

        self.addAction(self.open_file_action)
        self.addAction(self.load_entities_action)
        self.addAction(self.show_assembly_exporter_action)
        self.addAction(self.show_options_action)

    def create_actions(self):
        if not self.open_file_action:
            self.open_file_action = QAction(self.tr("Open File"), self, triggered=self.open_ifc_file)
            self.load_entities_action = QAction(self.tr("Load Entities"), self, triggered=self.start_load_db_task) # Large files take a long time 
            self.show_assembly_exporter_action = QAction(self.tr("Assembly Exporter"), self, triggered=self.show_assemblies_window)
            self.show_options_action = QAction(self.tr("Options"), self, triggered=self.show_options_window)

    def translate(self):
        self.open_file_action.setText(self.tr(self.open_file_action.text()))
        self.load_entities_action.setText(self.tr(self.load_entities_action.text()))
        self.show_assembly_exporter_action.setText(self.tr(self.show_assembly_exporter_action.text()))
        self.show_options_action.setText(self.tr(self.show_options_action.text()))


# A QAction that translates itself upon receiving a language changed signal
class TAction(QAction):
    def __init__(self, 
                 text_key=None,
                 parent=None,
                 *,
                 icon=None,
                 triggered=None,
                 triggered_args=None,
                 tooltip=None,
                 format_args=None,
                 **kwargs):
        """
        A self-translating QAction replacement.

        Parameters:
            text_key (str): The translation key for the text (may include placeholders).
            tooltip (str): The translation key for the tooltip (may include placeholders).
            format_args (tuple|dict): Format arguments for placeholders.
            icon (QIcon): Optional icon.
            triggered (callable): Function to call when triggered.
            triggered_args (tuple|any): Arguments to pass to triggered function.
            **kwargs: All other QAction kwargs like shortcut, checkable, etc.
        """
        self._text_key = text_key
        self._tooltip_key = tooltip
        self._format_args = format_args

        # Initialize with or without icon
        if icon:
            super().__init__(icon, "", parent)
        else:
            super().__init__("", parent)

        # Handle other kwargs like shortcut, checkable, etc.
        for key, value in kwargs.items():
            if hasattr(self, key):
                setattr(self, key, value)
            else:
                self.setProperty(key, value)

        # Connect signal
        if triggered:
            if triggered_args is not None:
                if not isinstance(triggered_args, tuple):
                    triggered_args = (triggered_args,)
                self.triggered.connect(partial(triggered, *triggered_args))
            else:
                self.triggered.connect(triggered)

        # Connect to language change signal
        language_manager.language_changed.connect(self.translate)
        self.translate()

    def translate(self):
        if self._text_key:
            translated = self.tr(self._text_key)
            if self._format_args:
                try:
                    translated = translated.format(*self._format_args) \
                        if isinstance(self._format_args, tuple) else \
                        translated.format(**self._format_args)
                except Exception as e:
                    print(f"[Translation format error]: {e}")
            self.setText(translated)

        if self._tooltip_key:
            tooltip_translated = self.tr(self._tooltip_key)
            try:
                tooltip_translated = tooltip_translated.format(*self._format_args) \
                    if isinstance(self._format_args, tuple) else \
                    tooltip_translated.format(**self._format_args)
            except Exception as e:
                print(f"[Tooltip format error]: {e}")
            self.setToolTip(tooltip_translated)