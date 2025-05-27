from PySide6.QtCore import QObject, Signal, QCoreApplication
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
# A QAction that translates itself upon receiving a language changed signal
class TAction(QAction):
    def __init__(self, text_key=None, parent=None, *,
                 context=None, icon=None, triggered=None, triggered_args=None,
                 tooltip=None, format_args=None, **kwargs):
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
        self._context = context or self.__class__.__name__

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
        tr = QCoreApplication.translate
        if self._text_key:
            translated = tr(self._context, self._text_key)
            if self._format_args:
                try:
                    translated = translated.format(*self._format_args) \
                        if isinstance(self._format_args, tuple) else \
                        translated.format(**self._format_args)
                except Exception as e:
                    print(f"[Translation format error]: {e}")
            self.setText(translated)

        if self._tooltip_key:
            tooltip_translated = tr(self._context, self._tooltip_key)
            try:
                tooltip_translated = tooltip_translated.format(*self._format_args) \
                    if isinstance(self._format_args, tuple) else \
                    tooltip_translated.format(**self._format_args)
            except Exception as e:
                print(f"[Tooltip format error]: {e}")
            self.setToolTip(tooltip_translated)