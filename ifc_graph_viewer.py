import networkx as nx

from PySide6.QtCore import *
from PySide6.QtGui import *
from PySide6.QtWidgets import *
class GraphNode(QGraphicsEllipseItem):
    def __init__(self, x, y, radius, entity, label):
        super().__init__(QRectF(x, y, radius, radius))
        self.setBrush(QBrush(QColor("skyblue")))
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.entity = entity
        self.label = label

        self.text = QGraphicsTextItem(label, self)
        self.text.setPos(x + radius + 5, y - 5)

    def mousePressEvent(self, event):
        info = self.entity.get_info()
        detail = "\n".join(f"{k}: {v}" for k, v in info.items())
        QMessageBox.information(None, f"Entity {self.label}", detail)

class IFCGraphViewer(QGraphicsView):
    _isScrolling = _isSpacePressed = False
    def __init__(self, ifc_graph, center_entities, parent=None):
        super(IFCGraphViewer, self).__init__(parent)

        self.center_entities = center_entities
        self.G = ifc_graph
        self.scene = QGraphicsScene(self)

        self.draw_graph() # draw the entities in the graphics view
        self.setScene(self.scene) # display the graphics view

        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
        )
        # Important! Without this, self.translate() will not work!
        self.setTransformationAnchor(self.ViewportAnchor.NoAnchor)

        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)

        screen = QApplication.screenAt(QCursor.pos())
        geo = screen.availableGeometry()
        geo.setSize(geo.size() * .7)
        geo.moveCenter(screen.availableGeometry().center())
        self.setGeometry(geo)

        self.setSceneRect(-32000, -32000, 64000, 64000)

        self.fitInView(self.scene.itemsBoundingRect())

    def mousePressEvent(self, event):
        if (
            event.button() == Qt.MouseButton.MiddleButton
            or self._isSpacePressed
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self._isScrolling = True
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            self.scrollPos = event.position()
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._isScrolling:
            newPos = event.position()
            delta = newPos - self.scrollPos
            t = self.transform()
            self.translate(delta.x() / t.m11(), delta.y() / t.m22())
            self.scrollPos = newPos
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._isScrolling:
            self._isScrolling = False
            if self._isSpacePressed:
                self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
            else:
                self.viewport().unsetCursor()
        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._isSpacePressed = True
            self.viewport().setCursor(Qt.CursorShape.OpenHandCursor)
        else:
            super().keyPressEvent(event)

    def keyReleaseEvent(self, event):
        if event.key() == Qt.Key.Key_Space and not event.isAutoRepeat():
            self._isSpacePressed = False
            if not self._isScrolling:
                self.viewport().unsetCursor()
        else:
            super().keyReleaseEvent(event)
    
    # zoom with mouse wheel
    def wheelEvent(self, event):
        # TODO: Fix zoom while panning
        scroll_direction = event.angleDelta().y()
        zoom_factor = 1 + (scroll_direction/1000)
        self.setTransformationAnchor(self.ViewportAnchor.AnchorUnderMouse)
        self.scale(zoom_factor, zoom_factor)
        self.setTransformationAnchor(self.ViewportAnchor.NoAnchor) # return to no anchor to allow for panning

    def draw_graph(self):
        self.scene.clear()
        subgraph = nx.ego_graph(self.G, self.center_entities[0], radius=2)  # Limit to N-hops
        pos = nx.spring_layout(subgraph, scale=600, k=150, iterations=50)


        # Draw nodes
        for node_id, (x, y) in pos.items():
            entity = self.G.nodes[node_id]["entity"]
            label = f"{entity.is_a()} #{entity.id()}"
            node_item = GraphNode(x, y, 30, entity, label)
            self.scene.addItem(node_item)

        # Draw edges
        for source, target in self.G.edges:
            x1, y1 = pos[source]
            x2, y2 = pos[target]
            self.scene.addLine(x1 + 15, y1 + 15, x2 + 15, y2 + 15)