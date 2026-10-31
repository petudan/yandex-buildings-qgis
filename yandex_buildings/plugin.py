# -*- coding: utf-8 -*-
"""Главный класс расширения: меню, диалог, инструмент рамки, запуск задачи."""

import os
import re
import subprocess
import sys

from qgis.PyQt.QtGui import QIcon
from qgis.PyQt.QtWidgets import QAction, QMessageBox
from qgis.core import (
    QgsApplication, QgsCoordinateReferenceSystem, QgsCoordinateTransform,
    QgsProject, QgsVectorLayer, Qgis,
)

from .i18n import tr
from .maptool import RectangleMapTool, ColorPickTool

PLUGIN_DIR = os.path.dirname(__file__)
ICON_PATH = os.path.join(PLUGIN_DIR, "icon.png")

# Порог, после которого спрашиваем подтверждение
CONFIRM_TILES = 1500

# Заливка слоев стандартных категорий (по стабильному ключу,
# не зависит от языка интерфейса)
LAYER_COLORS = {
    "residential": ("#d97b6c", "#8f3f33"),
    "nonresidential": ("#9e9e9e", "#5f5f5f"),
    "public": ("#c9a35c", "#7d6231"),
    "educational": ("#9c8fc7", "#5d5382"),
    "medical": ("#e394a8", "#a04f63"),
    "cultural": ("#c2b280", "#7a6f50"),
}


def _find_python():
    """Ищет python для запуска pip (в QGIS sys.executable — это сам QGIS)."""
    candidates = [
        os.path.join(sys.exec_prefix, "python.exe"),
        os.path.join(sys.exec_prefix, "python3.exe"),
        os.path.join(sys.exec_prefix, "bin", "python3"),
        sys.executable,
    ]
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return sys.executable


class YandexBuildingsPlugin:

    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.menu_name = None
        self.dialog = None
        self.map_tool = None
        self.pick_tool = None
        self.pick_row = None
        self.prev_tool = None
        self.task = None

    # ------------------------------------------------------------------
    # Жизненный цикл расширения
    # ------------------------------------------------------------------

    def initGui(self):
        self.action = QAction(QIcon(ICON_PATH), tr("menu_action"),
                              self.iface.mainWindow())
        self.action.triggered.connect(self.show_dialog)
        self.menu_name = tr("menu_action")
        self.iface.addPluginToMenu(self.menu_name, self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.map_tool is not None:
            self.map_tool.clear()
            self.iface.mapCanvas().unsetMapTool(self.map_tool)
        if self.pick_tool is not None:
            self.iface.mapCanvas().unsetMapTool(self.pick_tool)
        self.iface.removePluginMenu(self.menu_name, self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.dialog is not None:
            self.dialog.close()

    def on_language_changed(self, _lang):
        """Переименовывает пункт меню и подсказку кнопки под новый язык."""
        self.iface.removePluginMenu(self.menu_name, self.action)
        self.menu_name = tr("menu_action")
        self.action.setText(self.menu_name)
        self.iface.addPluginToMenu(self.menu_name, self.action)

    # ------------------------------------------------------------------
    # Зависимости
    # ------------------------------------------------------------------

    def _ensure_deps(self):
        try:
            import cv2  # noqa: F401
            return True
        except ImportError:
            pass

        res = QMessageBox.question(
            self.iface.mainWindow(), tr("dep_title"), tr("dep_text"),
            QMessageBox.Yes | QMessageBox.No)
        if res != QMessageBox.Yes:
            QMessageBox.information(self.iface.mainWindow(),
                                    tr("dep_manual_title"), tr("dep_manual"))
            return False

        python = _find_python()
        try:
            kwargs = {}
            if os.name == "nt":
                kwargs["creationflags"] = 0x08000000  # CREATE_NO_WINDOW
            subprocess.check_call(
                [python, "-m", "pip", "install", "opencv-python-headless"],
                **kwargs)
            import importlib
            importlib.invalidate_caches()
            import cv2  # noqa: F401
            return True
        except Exception as e:
            QMessageBox.warning(self.iface.mainWindow(), tr("dep_fail_title"),
                                tr("dep_fail", err=e))
            return False

    # ------------------------------------------------------------------
    # Диалог, рамка, пипетка
    # ------------------------------------------------------------------

    def show_dialog(self):
        if not self._ensure_deps():
            return
        if self.dialog is None:
            from .dialog import ExtractDialog
            self.dialog = ExtractDialog(self.iface.mainWindow())
            self.dialog.setWindowIcon(QIcon(ICON_PATH))
            self.dialog.setModal(False)
            self.dialog.draw_button.clicked.connect(self.start_drawing)
            self.dialog.hide_rect_button.clicked.connect(self.hide_rectangle)
            self.dialog.run_button.clicked.connect(self.run_task)
            self.dialog.cancel_button.clicked.connect(self.cancel_task)
            self.dialog.pickColorRequested.connect(self.start_picking)
            self.dialog.languageChanged.connect(self.on_language_changed)
        self.dialog.show()
        self.dialog.raise_()

    def start_picking(self, row_idx):
        """Пипетка: следующий клик по карте добавит цвет в категорию."""
        self.pick_row = row_idx
        canvas = self.iface.mapCanvas()
        if self.pick_tool is None:
            self.pick_tool = ColorPickTool(canvas)
            self.pick_tool.pointPicked.connect(self.on_point_picked)
        self.prev_tool = canvas.mapTool()
        self.dialog.showMinimized()
        canvas.setMapTool(self.pick_tool)
        self.iface.messageBar().pushMessage(
            tr("pick_title"), tr("pick_hint"), level=Qgis.Info, duration=4)

    def on_point_picked(self, point):
        """Клик пипетки: скачиваем тайл в этой точке и берем цвет
        из него — точный цвет палитры Яндекса, без искажений холста."""
        from qgis.PyQt.QtCore import Qt
        from qgis.PyQt.QtWidgets import QApplication
        from . import core
        from .task import _fetch_tile

        canvas = self.iface.mapCanvas()
        canvas.unsetMapTool(self.pick_tool)
        if self.prev_tool is not None:
            canvas.setMapTool(self.prev_tool)
        self.dialog.showNormal()
        self.dialog.raise_()
        if self.pick_row is None:
            return
        row = self.pick_row
        self.pick_row = None

        crs_canvas = canvas.mapSettings().destinationCrs()
        crs_wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        if crs_canvas != crs_wgs:
            xform = QgsCoordinateTransform(crs_canvas, crs_wgs,
                                           QgsProject.instance())
            point = xform.transform(point)
        lon, lat = point.x(), point.y()

        zoom = self.dialog.zoom_spin.value()
        xg, yg = core.latlon_to_global_pixels(lat, lon, zoom)
        tx, ty = int(xg // 256), int(yg // 256)
        px, py = int(xg % 256), int(yg % 256)

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            data = _fetch_tile(tx, ty, zoom)
            rgb = core.tile_pixel_color(data, px, py) if data else None
        finally:
            QApplication.restoreOverrideCursor()

        if rgb is None:
            self.iface.messageBar().pushMessage(
                tr("pick_title"), tr("pick_no_tile"), level=Qgis.Warning,
                duration=5)
            return
        if all(abs(rgb[i] - c) <= 3 for i, c in enumerate((252, 252, 247))):
            self.iface.messageBar().pushMessage(
                tr("pick_title"), tr("pick_bg", rgb=rgb), level=Qgis.Warning,
                duration=6)
            return
        self.dialog.apply_picked_color(row, rgb)

    def hide_rectangle(self):
        """Убирает красную рамку области с карты (сама область остается)."""
        if self.map_tool is not None:
            self.map_tool.clear()
            self.iface.mapCanvas().refresh()

    def start_drawing(self):
        canvas = self.iface.mapCanvas()
        if self.map_tool is None:
            self.map_tool = RectangleMapTool(canvas)
            self.map_tool.rectangleCreated.connect(self.on_rectangle)
        self.prev_tool = canvas.mapTool()
        self.dialog.showMinimized()
        canvas.setMapTool(self.map_tool)

    def on_rectangle(self, rect):
        """Рамка нарисована: переводим в WGS-84 и возвращаем диалог."""
        canvas = self.iface.mapCanvas()
        crs_canvas = canvas.mapSettings().destinationCrs()
        crs_wgs = QgsCoordinateReferenceSystem("EPSG:4326")
        if crs_canvas != crs_wgs:
            xform = QgsCoordinateTransform(crs_canvas, crs_wgs,
                                           QgsProject.instance())
            rect = xform.transformBoundingBox(rect)

        self.dialog.set_bbox(rect.yMinimum(), rect.yMaximum(),
                             rect.xMinimum(), rect.xMaximum())

        if self.prev_tool is not None:
            canvas.unsetMapTool(self.map_tool)
            canvas.setMapTool(self.prev_tool)
        self.dialog.showNormal()
        self.dialog.raise_()

    # ------------------------------------------------------------------
    # Запуск и завершение задачи
    # ------------------------------------------------------------------

    def run_task(self):
        from . import core
        from .task import ExtractBuildingsTask

        d = self.dialog
        if d.bbox is None:
            QMessageBox.warning(d, tr("err_no_area_title"), tr("err_no_area"))
            return
        classes = d.get_classes()
        if classes is None:
            return

        lat_min, lat_max, lon_min, lon_max = d.bbox
        zoom = d.zoom_spin.value()
        tiles, mask_mb = core.estimate(lat_min, lat_max, lon_min, lon_max,
                                       zoom)
        limit = d.tiles_limit_spin.value()
        if tiles > limit:
            res = QMessageBox.warning(
                d, tr("limit_title"),
                tr("limit_text", zoom=zoom, tiles=tiles, limit=limit,
                   mb=mask_mb),
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No)
            if res != QMessageBox.Yes:
                return
        elif tiles > CONFIRM_TILES:
            res = QMessageBox.question(
                d, tr("big_title"), tr("big_text", tiles=tiles, mb=mask_mb),
                QMessageBox.Yes | QMessageBox.No)
            if res != QMessageBox.Yes:
                return

        base_path = d.get_output_path()
        root, ext = os.path.splitext(base_path)
        ext = ext or ".geojson"
        for i, cls in enumerate(classes):
            # стандартные категории — по ключу (имя файла не зависит
            # от языка), свои — по названию
            src = cls.get("key") or cls["name"]
            suffix = re.sub(r"[^\w\-]+", "_", src.lower(),
                            flags=re.UNICODE).strip("_") or f"class{i + 1}"
            cls["out_path"] = f"{root}_{suffix}{ext}"

        # Перевод фильтров из метров в пиксели по зуму и широте области
        mpp = core.ground_resolution((lat_min + lat_max) / 2.0, zoom)
        min_area_px = int(d.min_area_spin.value() / (mpp * mpp))
        min_width_px = d.min_width_spin.value() / mpp
        eps_cap_px = max(3.0, 0.8 / mpp)   # допуск упрощения ~0.8 м

        self.task = ExtractBuildingsTask(
            d.bbox, zoom, classes, min_area_px,
            10 ** 9,  # лимит уже подтвержден пользователем в диалоге
            label_radius=d.label_radius_spin.value(),
            rect_threshold=0.82 if d.rect_check.isChecked() else 0.0,
            min_width=min_width_px,
            offset=(float(d.offset_x_spin.value()),
                    float(d.offset_y_spin.value())),
            eps_cap=eps_cap_px)
        self.task.progressChanged.connect(
            lambda: d.progress.setValue(int(self.task.progress())))
        self.task.taskCompleted.connect(self.on_task_completed)
        self.task.taskTerminated.connect(self.on_task_failed)

        d.set_running(True)
        d.status_label.setText(tr("status_loading", tiles=tiles))
        QgsApplication.taskManager().addTask(self.task)

    @staticmethod
    def _class_colors(key, ranges):
        """Цвета слоя: для стандартных — из таблицы, для пользовательских
        категорий — сам цвет здания (середина первого диапазона)."""
        if key in LAYER_COLORS:
            return LAYER_COLORS[key]
        if ranges:
            lo, hi = ranges[0]
            mid = [(int(l) + int(h)) // 2 for l, h in zip(lo, hi)]
            fill = "#{:02x}{:02x}{:02x}".format(*mid)
            outline = "#{:02x}{:02x}{:02x}".format(
                *(max(0, int(v * 0.55)) for v in mid))
            return fill, outline
        return "#d97b6c", "#8f3f33"

    def cancel_task(self):
        """Отмена запущенной загрузки/обработки."""
        if self.task is not None:
            self.dialog.status_label.setText(tr("status_cancelling"))
            self.dialog.cancel_button.setEnabled(False)
            self.task.cancel()

    def on_task_completed(self):
        from qgis.core import QgsFillSymbol, QgsSingleSymbolRenderer

        d = self.dialog
        task = self.task
        d.set_running(False)
        d.progress.setValue(100)

        crs = QgsCoordinateReferenceSystem("EPSG:3395")
        parts = []
        all_valid = True
        for cls in task.classes:
            name = cls["name"]
            n_found = task.n_features.get(name, 0)
            parts.append(f"{name.lower()}: {n_found}")
            if n_found == 0:
                continue  # пустой слой не добавляем
            layer = QgsVectorLayer(cls["out_path"],
                                   tr("layer_name", name=name.lower()), "ogr")
            if not layer.isValid():
                all_valid = False
                continue
            if layer.crs() != crs:
                layer.setCrs(crs)
            fill, outline = self._class_colors(cls.get("key"),
                                               cls.get("ranges"))
            symbol = QgsFillSymbol.createSimple({
                "color": fill, "outline_color": outline,
                "outline_width": "0.3"})
            renderer = layer.renderer()
            if renderer is not None:
                renderer.setSymbol(symbol)
            else:
                layer.setRenderer(QgsSingleSymbolRenderer(symbol))
            layer.triggerRepaint()
            QgsProject.instance().addMapLayer(layer)

        msg = tr("result_found", parts=", ".join(parts))
        if task.n_failed:
            msg += tr("result_failed_tiles", n=task.n_failed)
        if not all_valid:
            msg += tr("result_bad_layers")
        d.status_label.setText(msg)
        self.iface.messageBar().pushMessage(
            tr("msgbar_title"), msg,
            level=Qgis.Success if all_valid else Qgis.Warning, duration=7)
        self.task = None

    def on_task_failed(self):
        d = self.dialog
        task = self.task
        d.set_running(False)
        err = task.error if task and task.error else tr("task_failed")
        d.status_label.setText(err)
        self.iface.messageBar().pushMessage(
            tr("msgbar_title"), err, level=Qgis.Warning, duration=7)
        self.task = None
