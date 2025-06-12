from PySide6.QtWidgets import (
    QLabel, QWidget, QVBoxLayout, QSizePolicy
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QEnterEvent, QMouseEvent
from tui import *
from strings import STATS_PANEL_KEYS

class ClickableLabel(QLabel):
    clicked = Signal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setStyleSheet(self.default_style())

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)

    def enterEvent(self, event: QEnterEvent):
        self.setStyleSheet(self.hover_style())
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.setStyleSheet(self.default_style())
        super().leaveEvent(event)

    def default_style(self):
        return """
        QLabel {
            padding: 2px;
        }
        """

    def hover_style(self):
        return """
        QLabel {
            padding: 2px;
            text-decoration: underline;
        }
        """

class StatsPanel(QWidget):
    label_clicked = Signal(str)

    def __init__(self, ifc_version=None, entity_dict=None, time_to_load=None):
        super().__init__()

        # Layout setup
        self.layout = QVBoxLayout()
        self.setLayout(self.layout)

        # Optional: help layout manage vertical spacing
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.MinimumExpanding)
        self.setMinimumWidth(200)

        self.update_stats(ifc_version, entity_dict, time_to_load)

    def update_stats(self, ifc_version=None, entity_dict=None, time_to_load=None):
        # Clear layout
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        # "IFC Version: {version}"
        self.layout.addWidget(TLabel(STATS_PANEL_KEYS[0],
                                     self,
                                     context="Stats Panel",
                                     format_args={"version": ifc_version}))

        if time_to_load:
            # "Loaded in {time}"
            self.layout.addWidget(TLabel(STATS_PANEL_KEYS[2],
                                     self,
                                     context="Stats Panel",
                                     format_args={"time": round(time_to_load, 2)}))

        if entity_dict:
            self.layout.addWidget(TLabel(STATS_PANEL_KEYS[3],
                                         self,
                                         context="Stats Panel",
                                         format_args={"count": len(entity_dict)}))

            # Add the list of entity types
            for ifc_type, count in sorted(entity_dict.items()):
                label = ClickableLabel(f"{ifc_type}: {count}")
                label.clicked.connect(self.on_label_clicked)
                self.layout.addWidget(label)

        self.layout.addStretch()

    def on_label_clicked(self):
        label = self.sender()
        ifc_type = label.text().split(":")[0]
        print(f"IFC type: {ifc_type}")
        self.label_clicked.emit(ifc_type)
 