# -*- coding: utf-8 -*-
"""
Фоновая задача QGIS: параллельная загрузка тайлов и обработка.
Выполняется в отдельном потоке, интерфейс QGIS не замирает,
задачу можно отменить из панели задач.
"""

import http.client
import json
import ssl
import threading
import time
import traceback
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed

from qgis.core import QgsTask

from . import core
from .i18n import tr

# Хост задан жестко: запросы уходят только по HTTPS на сервер тайлов
# Яндекса, подменить схему или адрес извне невозможно.
TILE_HOST = "core-renderer-tiles.maps.yandex.net"
TILE_PATH = "/tiles?l=map&x={x}&y={y}&z={z}&scale=1&lang=ru_RU"

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/124.0 Safari/537.36"),
    "Referer": "https://yandex.ru/maps/",
}

MAX_WORKERS = 8      # параллельных загрузок
RETRIES = 3

# Защищенный контекст: проверка сертификата и имени хоста включены
_SSL_CTX = ssl.create_default_context()
# Одно HTTPS-соединение на поток: keep-alive ускоряет загрузку
_local = threading.local()


def _proxy_for_tiles():
    """
    Системный прокси для HTTPS (переменные окружения или настройки
    Windows), как это делал urllib. Возвращает (host, port) или None.
    Только чтение настроек: сам urllib.request.urlopen не используется.
    """
    try:
        if urllib.request.proxy_bypass(TILE_HOST):
            return None
        proxy = urllib.request.getproxies().get("https")
    except Exception:
        return None
    if not proxy:
        return None
    parsed = urllib.parse.urlsplit(proxy if "://" in proxy
                                   else "http://" + proxy)
    if not parsed.hostname:
        return None
    return parsed.hostname, parsed.port or 8080


_PROXY = _proxy_for_tiles()


def _get_conn():
    conn = getattr(_local, "conn", None)
    if conn is None:
        if _PROXY:
            # HTTPS через прокси: туннель CONNECT до сервера тайлов,
            # сертификат Яндекса проверяется как обычно
            conn = http.client.HTTPSConnection(_PROXY[0], _PROXY[1],
                                               timeout=20, context=_SSL_CTX)
            conn.set_tunnel(TILE_HOST, 443)
        else:
            conn = http.client.HTTPSConnection(TILE_HOST, timeout=20,
                                               context=_SSL_CTX)
        _local.conn = conn
        _local.fresh = True
    return conn


def _drop_conn():
    conn = getattr(_local, "conn", None)
    if conn is not None:
        try:
            conn.close()
        except OSError:
            pass
        _local.conn = None


def _fetch_tile(tx, ty, zoom):
    """Скачивает один тайл с повторами. Возвращает bytes или None."""
    path = TILE_PATH.format(x=int(tx), y=int(ty), z=int(zoom))
    attempt = 0
    while attempt < RETRIES:
        conn = _get_conn()
        reused = not getattr(_local, "fresh", True)
        _local.fresh = False
        try:
            conn.request("GET", path, headers=HEADERS)
            resp = conn.getresponse()
            data = resp.read()
            if resp.will_close:
                _drop_conn()  # сервер закрывает соединение — не ждем ошибки
            if resp.status == 200 and data:
                return data
        except (OSError, http.client.HTTPException):
            _drop_conn()
            if reused:
                # сервер закрыл простаивавшее соединение — это не сбой:
                # сразу повторяем на новом, без паузы и без траты попытки
                continue
        attempt += 1
        if attempt < RETRIES:
            time.sleep(0.4 * attempt)
    return None


class ExtractBuildingsTask(QgsTask):
    """Загрузка тайлов -> маска -> полигоны -> GeoJSON."""

    def __init__(self, bbox4326, zoom, classes, min_area,
                 max_tiles=4000, label_radius=10, rect_threshold=0.82,
                 simplify=0.015, min_width=8, offset=(0.0, 0.0),
                 eps_cap=8.0):
        """
        classes — список словарей:
        {"name": str, "ranges": [((r,g,b), (r,g,b)), ...], "out_path": str}
        min_area и min_width здесь уже в пикселях (пересчет из метров
        делает вызывающая сторона).
        """
        super().__init__(tr("task_title"), QgsTask.CanCancel)
        self.bbox = bbox4326          # (lat_min, lat_max, lon_min, lon_max)
        self.zoom = zoom
        self.classes = classes
        self.min_area = min_area
        self.max_tiles = max_tiles
        self.label_radius = label_radius
        self.rect_threshold = rect_threshold
        self.simplify = simplify
        self.min_width = min_width
        self.offset = offset
        self.eps_cap = eps_cap

        self.error = None
        self.n_features = {}          # имя класса -> число зданий
        self.n_tiles = 0
        self.n_failed = 0

    def run(self):
        try:
            return self._run()
        except Exception:
            self.error = traceback.format_exc()
            return False

    def _run(self):
        lat_min, lat_max, lon_min, lon_max = self.bbox
        tx_min, tx_max, ty_min, ty_max = core.tile_range(
            lat_min, lat_max, lon_min, lon_max, self.zoom)

        coords = [(tx, ty)
                  for tx in range(tx_min, tx_max + 1)
                  for ty in range(ty_min, ty_max + 1)]
        self.n_tiles = len(coords)

        if self.n_tiles > self.max_tiles:
            self.error = tr("err_too_many", n=self.n_tiles,
                            limit=self.max_tiles)
            return False

        ranges = [c["ranges"] for c in self.classes]
        builder = core.MaskBuilder(tx_min, tx_max, ty_min, ty_max, ranges)

        # Загрузка параллельно; маска заполняется сразу, RGB не копится
        done = 0
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
            futures = {pool.submit(_fetch_tile, tx, ty, self.zoom): (tx, ty)
                       for tx, ty in coords}
            for fut in as_completed(futures):
                if self.isCanceled():
                    for f in futures:
                        f.cancel()
                    return False
                tx, ty = futures[fut]
                data = fut.result()
                if data is None or not builder.add_tile(tx, ty, data):
                    self.n_failed += 1
                done += 1
                self.setProgress(done / self.n_tiles * 80.0)

        if self.isCanceled():
            return False

        if self.n_failed >= self.n_tiles:
            self.error = tr("err_no_tiles", zoom=self.zoom)
            return False
        self.setProgress(82.0)

        n = len(self.classes)
        label = builder.label_mask()  # подписи/иконки/ореолы
        wall = builder.wall_mask()    # стены — нейтральны при лечении
        for i, cls in enumerate(self.classes, start=1):
            if self.isCanceled():
                return False
            binary = builder.class_mask(i)
            geojson = core.process_mask(binary, tx_min, ty_min,
                                        self.zoom, self.min_area,
                                        self.label_radius,
                                        self.rect_threshold, self.simplify,
                                        self.min_width, self.offset,
                                        allowed=label, eps_cap=self.eps_cap,
                                        wall=wall)
            for f in geojson["features"]:
                f["properties"]["type"] = cls["name"]
            self.n_features[cls["name"]] = len(geojson["features"])
            with open(cls["out_path"], "w", encoding="utf-8") as f:
                json.dump(geojson, f, ensure_ascii=False)
            self.setProgress(82.0 + i / n * 18.0)
        return True
