# -*- coding: utf-8 -*-
"""Диалог расширения. Интерфейс собран кодом, без .ui файла.

Все тексты берутся из i18n.tr() и обновляются в retranslate(),
поэтому язык переключается на лету, без перезапуска.
"""

import json
import os
import tempfile

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout, QLabel,
    QPushButton, QSpinBox, QDoubleSpinBox, QLineEdit, QProgressBar,
    QFileDialog, QDialogButtonBox, QMessageBox, QCheckBox, QInputDialog,
    QWidget, QScrollArea, QComboBox,
)
from qgis.core import QgsSettings

from .i18n import (tr, get_lang, set_lang, builtin_name, BUILTIN_KEYS,
                   LEGACY_NAMES)

SETTINGS_KEY = "yandex_buildings/classes_json"

_DEFAULT_RANGES = {
    "residential": ("230, 225, 220", "238, 233, 228"),
    "nonresidential": ("225, 225, 226", "233, 233, 234"),
    "public": ("228, 218, 200", "240, 230, 218"),
    "educational": ("209, 206, 222", "219, 216, 232"),
    "medical": ("246, 217, 225", "255, 227, 235"),
    "cultural": ("242, 241, 234", "248, 247, 241"),
}


def default_class_data():
    return [{"key": k, "name": "", "lo": _DEFAULT_RANGES[k][0],
             "hi": _DEFAULT_RANGES[k][1], "enabled": True}
            for k in BUILTIN_KEYS]


def display_name(d):
    """Название категории на текущем языке (свои — как ввел пользователь)."""
    key = d.get("key")
    return builtin_name(key) if key else d.get("name", "")


class ExtractDialog(QDialog):
    """Окно параметров: область, категории, параметры, вывод."""

    pickColorRequested = pyqtSignal(int)  # индекс категории для пипетки
    languageChanged = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(440)
        self.bbox = None  # (lat_min, lat_max, lon_min, lon_max)

        layout = QVBoxLayout(self)

        # --- Язык ---
        lang_row = QHBoxLayout()
        self.lang_label = QLabel()
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("Русский", "ru")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.setCurrentIndex(0 if get_lang() == "ru" else 1)
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addStretch()
        lang_row.addWidget(self.lang_label)
        lang_row.addWidget(self.lang_combo)
        layout.addLayout(lang_row)

        # --- Область ---
        self.area_group = QGroupBox()
        area_layout = QVBoxLayout(self.area_group)
        self.extent_label = QLabel()
        self.extent_label.setWordWrap(True)
        self.draw_button = QPushButton()
        self.hide_rect_button = QPushButton()
        btn_row = QHBoxLayout()
        btn_row.addWidget(self.draw_button)
        btn_row.addWidget(self.hide_rect_button)
        area_layout.addWidget(self.extent_label)
        area_layout.addLayout(btn_row)
        layout.addWidget(self.area_group)

        # --- Типы зданий ---
        self.cls_group = QGroupBox()
        cls_v = QVBoxLayout(self.cls_group)
        self.classes_hint = QLabel()
        cls_v.addWidget(self.classes_hint)
        self.rows_widget = QWidget()
        self.rows_layout = QVBoxLayout(self.rows_widget)
        self.rows_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.rows_widget)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMaximumHeight(230)
        scroll.setMinimumHeight(120)
        cls_v.addWidget(scroll)

        cls_btns = QHBoxLayout()
        self.add_btn = QPushButton()
        self.add_btn.clicked.connect(self.add_category)
        self.reset_btn = QPushButton()
        self.reset_btn.clicked.connect(self.reset_categories)
        cls_btns.addWidget(self.add_btn)
        cls_btns.addWidget(self.reset_btn)
        cls_btns.addStretch()
        cls_v.addLayout(cls_btns)
        layout.addWidget(self.cls_group)

        self.classes_data = self._load_classes_data()
        self.class_rows = []

        # --- Параметры ---
        self.params_group = QGroupBox()
        form = QFormLayout(self.params_group)

        self.zoom_label = QLabel()
        self.zoom_spin = QSpinBox()
        self.zoom_spin.setRange(19, 21)
        self.zoom_spin.setValue(21)
        form.addRow(self.zoom_label, self.zoom_spin)

        self.tiles_limit_label = QLabel()
        self.tiles_limit_spin = QSpinBox()
        self.tiles_limit_spin.setRange(100, 200000)
        self.tiles_limit_spin.setSingleStep(500)
        self.tiles_limit_spin.setValue(4000)
        form.addRow(self.tiles_limit_label, self.tiles_limit_spin)

        self.min_area_label = QLabel()
        self.min_area_spin = QSpinBox()
        self.min_area_spin.setRange(0, 100000)
        self.min_area_spin.setValue(10)
        form.addRow(self.min_area_label, self.min_area_spin)

        self.min_width_label = QLabel()
        self.min_width_spin = QDoubleSpinBox()
        self.min_width_spin.setRange(0.0, 50.0)
        self.min_width_spin.setSingleStep(0.5)
        self.min_width_spin.setValue(1.5)
        form.addRow(self.min_width_label, self.min_width_spin)

        self.offset_label = QLabel()
        self.offset_x_spin = QSpinBox()
        self.offset_x_spin.setRange(-30, 30)
        self.offset_y_spin = QSpinBox()
        self.offset_y_spin.setRange(-30, 30)
        self.right_label = QLabel()
        self.down_label = QLabel()
        off_row = QHBoxLayout()
        off_row.addWidget(self.right_label)
        off_row.addWidget(self.offset_x_spin)
        off_row.addWidget(self.down_label)
        off_row.addWidget(self.offset_y_spin)
        form.addRow(self.offset_label, off_row)

        self.label_radius_label = QLabel()
        self.label_radius_spin = QSpinBox()
        self.label_radius_spin.setRange(0, 30)
        self.label_radius_spin.setValue(10)
        form.addRow(self.label_radius_label, self.label_radius_spin)

        self.rect_check = QCheckBox()
        self.rect_check.setChecked(True)
        form.addRow("", self.rect_check)

        layout.addWidget(self.params_group)

        # --- Вывод ---
        self.out_group = QGroupBox()
        out_layout = QHBoxLayout(self.out_group)
        self.out_edit = QLineEdit()
        browse = QPushButton("...")
        browse.setFixedWidth(32)
        browse.clicked.connect(self._browse)
        out_layout.addWidget(self.out_edit)
        out_layout.addWidget(browse)
        layout.addWidget(self.out_group)

        # --- Прогресс и кнопки ---
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        layout.addWidget(self.progress)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.buttons = QDialogButtonBox()
        self.run_button = self.buttons.addButton(
            "Run", QDialogButtonBox.AcceptRole)
        self.cancel_button = self.buttons.addButton(
            "Cancel", QDialogButtonBox.ActionRole)
        self.cancel_button.setEnabled(False)
        self.close_button = self.buttons.addButton(
            "Close", QDialogButtonBox.RejectRole)
        self.buttons.rejected.connect(self.close)
        layout.addWidget(self.buttons)

        self.retranslate()

    # ------------------------------------------------------------------
    # Язык
    # ------------------------------------------------------------------

    def _on_lang_changed(self, index):
        lang = self.lang_combo.itemData(index)
        set_lang(lang)
        self.retranslate()
        self.languageChanged.emit(lang)

    def retranslate(self):
        """Обновляет все тексты интерфейса на текущем языке."""
        self.setWindowTitle(tr("window_title"))
        self.lang_label.setText(tr("language"))

        self.area_group.setTitle(tr("grp_area"))
        self._update_extent_label()
        self.draw_button.setText(tr("btn_draw"))
        self.hide_rect_button.setText(tr("btn_hide_rect"))

        self.cls_group.setTitle(tr("grp_classes"))
        self.classes_hint.setText(tr("classes_hint"))
        self.add_btn.setText(tr("btn_add_cat"))
        self.reset_btn.setText(tr("btn_reset_cat"))
        if self.class_rows:
            self._sync_rows_to_data()
        self._rebuild_rows()

        self.params_group.setTitle(tr("grp_params"))
        self.zoom_label.setText(tr("lbl_zoom"))
        self.zoom_spin.setToolTip(tr("tip_zoom"))
        self.tiles_limit_label.setText(tr("lbl_tiles_limit"))
        self.tiles_limit_spin.setToolTip(tr("tip_tiles_limit"))
        self.min_area_label.setText(tr("lbl_min_area"))
        self.min_area_spin.setToolTip(tr("tip_min_area"))
        self.min_width_label.setText(tr("lbl_min_width"))
        self.min_width_spin.setToolTip(tr("tip_min_width"))
        self.offset_label.setText(tr("lbl_offset"))
        self.right_label.setText(tr("lbl_right"))
        self.down_label.setText(tr("lbl_down"))
        self.offset_x_spin.setToolTip(tr("tip_offset"))
        self.offset_y_spin.setToolTip(tr("tip_offset"))
        self.label_radius_label.setText(tr("lbl_label_radius"))
        self.label_radius_spin.setToolTip(tr("tip_label_radius"))
        self.rect_check.setText(tr("chk_rect"))
        self.rect_check.setToolTip(tr("tip_rect"))

        self.out_group.setTitle(tr("grp_output"))
        self.out_edit.setPlaceholderText(tr("out_placeholder"))

        self.run_button.setText(tr("btn_run"))
        self.cancel_button.setText(tr("btn_cancel"))
        self.cancel_button.setToolTip(tr("tip_cancel"))
        self.close_button.setText(tr("btn_close"))

    def _update_extent_label(self):
        if self.bbox is None:
            self.extent_label.setText(tr("area_not_set"))
        else:
            lat0, lat1, lon0, lon1 = self.bbox
            self.extent_label.setText(tr("area_coords", lat0=lat0, lat1=lat1,
                                         lon0=lon0, lon1=lon1))

    # ------------------------------------------------------------------
    # Категории: загрузка, сохранение, строки интерфейса
    # ------------------------------------------------------------------

    @staticmethod
    def _load_classes_data():
        raw = QgsSettings().value(SETTINGS_KEY, "")
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, list) and data:
                    # миграция с версий до 1.17: стандартные категории
                    # хранились русским названием, без ключа
                    for d in data:
                        if "key" not in d:
                            key = LEGACY_NAMES.get(d.get("name", ""))
                            d["key"] = key
                            if key:
                                d["name"] = ""
                    return data
            except (ValueError, TypeError, AttributeError):
                pass
        return default_class_data()

    def save_classes(self):
        self._sync_rows_to_data()
        QgsSettings().setValue(SETTINGS_KEY, json.dumps(self.classes_data))

    def _sync_rows_to_data(self):
        for i, (name, check, lo_edit, hi_edit) in enumerate(self.class_rows):
            if i >= len(self.classes_data):
                break
            self.classes_data[i]["enabled"] = check.isChecked()
            self.classes_data[i]["lo"] = lo_edit.text()
            self.classes_data[i]["hi"] = hi_edit.text()

    def _rebuild_rows(self):
        while self.rows_layout.count():
            item = self.rows_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self.class_rows = []
        for idx, d in enumerate(self.classes_data):
            name = display_name(d)
            roww = QWidget()
            row = QHBoxLayout(roww)
            row.setContentsMargins(0, 0, 0, 0)
            check = QCheckBox(name)
            check.setChecked(bool(d.get("enabled", True)))
            check.setMinimumWidth(120)
            lo_edit = QLineEdit(d.get("lo", ""))
            hi_edit = QLineEdit(d.get("hi", ""))
            for e in (lo_edit, hi_edit):
                e.editingFinished.connect(self.save_classes)
            check.toggled.connect(self.save_classes)
            pick = QPushButton("⊕")
            pick.setFixedWidth(28)
            pick.setToolTip(tr("tip_pick"))
            pick.clicked.connect(
                lambda _, i=idx: self.pickColorRequested.emit(i))
            rm = QPushButton("✕")
            rm.setFixedWidth(28)
            rm.setToolTip(tr("tip_delete"))
            rm.clicked.connect(lambda _, i=idx: self.delete_category(i))
            row.addWidget(check)
            row.addWidget(lo_edit)
            row.addWidget(QLabel("—"))
            row.addWidget(hi_edit)
            row.addWidget(pick)
            row.addWidget(rm)
            self.rows_layout.addWidget(roww)
            self.class_rows.append((name, check, lo_edit, hi_edit))
        # прижимаем строки кверху, чтобы они не растягивались по высоте
        self.rows_layout.addStretch()

    def add_category(self):
        name, ok = QInputDialog.getText(self, tr("dlg_new_cat_title"),
                                        tr("dlg_new_cat_label"))
        name = (name or "").strip()
        if not ok or not name:
            return
        if any(display_name(d) == name for d in self.classes_data):
            QMessageBox.warning(self, tr("dlg_cat_exists_title"),
                                tr("dlg_cat_exists", name=name))
            return
        self._sync_rows_to_data()
        self.classes_data.append(
            {"key": None, "name": name, "lo": "", "hi": "", "enabled": True})
        self._rebuild_rows()
        self.save_classes()

    def delete_category(self, idx):
        name = display_name(self.classes_data[idx])
        res = QMessageBox.question(
            self, tr("dlg_del_title"), tr("dlg_del", name=name),
            QMessageBox.Yes | QMessageBox.No)
        if res != QMessageBox.Yes:
            return
        self._sync_rows_to_data()
        del self.classes_data[idx]
        self._rebuild_rows()
        self.save_classes()

    def reset_categories(self):
        res = QMessageBox.question(
            self, tr("dlg_reset_title"), tr("dlg_reset"),
            QMessageBox.Yes | QMessageBox.No)
        if res != QMessageBox.Yes:
            return
        self.classes_data = default_class_data()
        self._rebuild_rows()
        self.save_classes()

    def apply_picked_color(self, idx, rgb, tol=5):
        """Добавляет цвет с пипетки диапазоном +-tol в категорию idx."""
        if not 0 <= idx < len(self.class_rows):
            return
        name, check, lo_edit, hi_edit = self.class_rows[idx]
        lo = ", ".join(str(max(0, v - tol)) for v in rgb)
        hi = ", ".join(str(min(255, v + tol)) for v in rgb)
        lo_t, hi_t = lo_edit.text().strip(), hi_edit.text().strip()
        lo_edit.setText(f"{lo_t}; {lo}" if lo_t else lo)
        hi_edit.setText(f"{hi_t}; {hi}" if hi_t else hi)
        check.setChecked(True)
        self.save_classes()
        self.status_label.setText(tr("picked_status", r=rgb[0], g=rgb[1],
                                     b=rgb[2], name=name))

    def closeEvent(self, event):
        self.save_classes()
        super().closeEvent(event)

    # ------------------------------------------------------------------

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, tr("dlg_save_geojson"), "buildings_yandex.geojson",
            "GeoJSON (*.geojson)")
        if path:
            self.out_edit.setText(path)

    def set_bbox(self, lat_min, lat_max, lon_min, lon_max):
        self.bbox = (lat_min, lat_max, lon_min, lon_max)
        self._update_extent_label()

    def get_output_path(self):
        path = self.out_edit.text().strip()
        if not path:
            fd, path = tempfile.mkstemp(
                suffix=".geojson", prefix="buildings_yandex_")
            os.close(fd)
            self.out_edit.setText(path)
        return path

    @staticmethod
    def _parse_rgb(text):
        vals = tuple(int(v) for v in text.split(","))
        if len(vals) != 3 or any(not 0 <= v <= 255 for v in vals):
            raise ValueError(text)
        return vals

    def get_classes(self):
        """
        Возвращает список включенных классов
        [{"name", "key", "ranges": [(lower, upper), ...]}] или None.
        name — название на текущем языке, key — ключ стандартной
        категории (None для пользовательских).
        """
        self.save_classes()
        classes = []
        for i, (name, check, lo_edit, hi_edit) in enumerate(self.class_rows):
            if not check.isChecked():
                continue
            lo_parts = [p for p in
                        (s.strip() for s in lo_edit.text().split(";")) if p]
            hi_parts = [p for p in
                        (s.strip() for s in hi_edit.text().split(";")) if p]
            if not lo_parts and not hi_parts:
                QMessageBox.warning(self, tr("err_empty_cat_title"),
                                    tr("err_empty_cat", name=name))
                return None
            try:
                if not lo_parts or len(lo_parts) != len(hi_parts):
                    raise ValueError
                ranges = [(self._parse_rgb(lo), self._parse_rgb(hi))
                          for lo, hi in zip(lo_parts, hi_parts)]
            except ValueError:
                QMessageBox.warning(self, tr("err_title"),
                                    tr("err_rgb", name=name))
                return None
            classes.append({"name": name,
                            "key": self.classes_data[i].get("key"),
                            "ranges": ranges})
        if not classes:
            QMessageBox.warning(self, tr("err_no_classes_title"),
                                tr("err_no_classes"))
            return None
        return classes

    def set_running(self, running):
        self.run_button.setEnabled(not running)
        self.draw_button.setEnabled(not running)
        self.cancel_button.setEnabled(running)
        if running:
            self.progress.setValue(0)
