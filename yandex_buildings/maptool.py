# -*- coding: utf-8 -*-
"""Инструмент рисования прямоугольной области на карте."""

from qgis.PyQt.QtCore import pyqtSignal, Qt
from qgis.PyQt.QtGui import QColor
from qgis.gui import QgsMapTool, QgsRubberBand
from qgis.core import QgsRectangle, QgsPointXY, QgsWkbTypes


class RectangleMapTool(QgsMapTool):
    """Рисование bbox мышью: нажать — потянуть — отпустить."""

    rectangleCreated = pyqtSignal(QgsRectangle)

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.start_point = None
        self.rubber = QgsRubberBand(canvas, QgsWkbTypes.PolygonGeometry)
        self.rubber.setColor(QColor(227, 26, 28, 60))
        self.rubber.setStrokeColor(QColor(227, 26, 28))
        self.rubber.setWidth(2)
        self.setCursor(Qt.CrossCursor)

    def canvasPressEvent(self, e):
        self.start_point = self.toMapCoordinates(e.pos())
        self._draw(self.start_point, self.start_point)

    def canvasMoveEvent(self, e):
        if self.start_point is None:
            return
        self._draw(self.start_point, self.toMapCoordinates(e.pos()))

    def canvasReleaseEvent(self, e):
        if self.start_point is None:
            return
        end_point = self.toMapCoordinates(e.pos())
        rect = QgsRectangle(self.start_point, end_point)
        self.start_point = None
        if rect.width() > 0 and rect.height() > 0:
            self.rectangleCreated.emit(rect)

    def _draw(self, p1, p2):
        self.rubber.reset(QgsWkbTypes.PolygonGeometry)
        pts = [QgsPointXY(p1.x(), p1.y()),
               QgsPointXY(p2.x(), p1.y()),
               QgsPointXY(p2.x(), p2.y()),
               QgsPointXY(p1.x(), p2.y())]
        for i, p in enumerate(pts):
            self.rubber.addPoint(p, i == len(pts) - 1)
        self.rubber.show()

    def clear(self):
        self.rubber.reset(QgsWkbTypes.PolygonGeometry)

    def deactivate(self):
        super().deactivate()


class ColorPickTool(QgsMapTool):
    """
    Пипетка: клик возвращает координаты точки на карте. Сам цвет
    берется из скачанного тайла Яндекса (точный цвет палитры),
    а не с холста, где мелкие здания размыты масштабированием.
    """

    pointPicked = pyqtSignal(object)  # QgsPointXY в CRS холста

    def __init__(self, canvas):
        super().__init__(canvas)
        self.canvas = canvas
        self.setCursor(Qt.CrossCursor)

    def canvasReleaseEvent(self, e):
        self.pointPicked.emit(self.toMapCoordinates(e.pos()))
