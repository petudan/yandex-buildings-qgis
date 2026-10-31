# -*- coding: utf-8 -*-
"""
Ядро обработки: математика тайлов Яндекса, построение маски зданий,
извлечение полигонов. Не зависит от QGIS — можно тестировать отдельно.

Оптимизация памяти по сравнению с прототипом:
  - большое RGB-изображение не склеивается вообще;
  - маска строится по каждому тайлу сразу после загрузки, RGB тут же
    освобождается; в памяти живет только одноканальная маска (1 байт
    на пиксель вместо ~7 у прототипа);
  - тайлы не сохраняются на диск.

Проекция: тайлы Яндекса лежат в эллиптическом Меркаторе (EPSG:3395),
поэтому и координаты результата считаются в EPSG:3395 (в прототипе
они ошибочно подписывались как EPSG:3857).
"""

import math

import numpy as np
import cv2

TILE_SIZE = 256
E = 0.0818191908426          # эксцентриситет WGS-84
ORIGIN_SHIFT = 20037508.342789244  # pi * 6378137

# Цвета зданий на карте Яндекса (RGB). Диапазоны можно править в диалоге.
DEFAULT_LOWER = (230, 225, 220)          # жилые (теплый бежевый)
DEFAULT_UPPER = (238, 233, 228)

DEFAULT_CLASSES = [
    # (название, список диапазонов [(lower, upper), ...]);
    # у класса может быть несколько диапазонов
    ("Жилые", [((230, 225, 220), (238, 233, 228))]),
    ("Нежилые", [((225, 225, 226), (233, 233, 234))]),
    ("Общественные", [((228, 218, 200), (240, 230, 218))]),
    ("Учебные", [((209, 206, 222), (219, 216, 232))]),       # сиреневый
    ("Медицинские", [((246, 217, 225), (255, 227, 235))]),   # розовый
    # почти белый теплый; верх по B=241 отсекает подложку промзон
    ("Культурные", [((242, 241, 234), (248, 247, 241))]),
]

# Значение в маске классов для пикселей подписей/иконок/текста.
# По этим пикселям разрешено «заращивать» вырезы в зданиях.
LABEL_ID = 250
# Пиксели стен (псевдо-3D бока зданий). Участвуют только в лечении
# вырезов через выпуклую оболочку, но не в морфологическом заращивании,
# чтобы корпуса, разделенные полосой стены, не склеивались.
WALL_ID = 249


# ----------------------------------------------------------------------
# Математика тайлов (эллиптический Меркатор Яндекса)
# ----------------------------------------------------------------------

def latlon_to_global_pixels(lat_deg, lon_deg, zoom):
    """Широта/долгота (WGS-84) -> глобальные пиксельные координаты сетки Яндекса."""
    map_size = TILE_SIZE * (2 ** zoom)
    rho = map_size / 2.0
    beta = math.radians(lat_deg)
    s = math.sin(beta)
    phi = (1 - E * s) / (1 + E * s)
    theta = math.tan(math.pi / 4 + beta / 2) * math.pow(phi, E / 2)
    x = rho * (1 + lon_deg / 180.0)
    y = rho * (1 - math.log(theta) / math.pi)
    return x, y


def tile_range(lat_min, lat_max, lon_min, lon_max, zoom):
    """Диапазон тайлов, покрывающий bbox. Возвращает (x_min, x_max, y_min, y_max)."""
    x1, y1 = latlon_to_global_pixels(lat_max, lon_min, zoom)  # верхний левый
    x2, y2 = latlon_to_global_pixels(lat_min, lon_max, zoom)  # нижний правый
    tx_min = int(min(x1, x2) // TILE_SIZE)
    tx_max = int(max(x1, x2) // TILE_SIZE)
    ty_min = int(min(y1, y2) // TILE_SIZE)
    ty_max = int(max(y1, y2) // TILE_SIZE)
    return tx_min, tx_max, ty_min, ty_max


def pixel_to_merc(x_pix, y_pix, tx_origin, ty_origin, zoom):
    """Пиксель склейки -> метры EPSG:3395."""
    map_size = TILE_SIZE * (2 ** zoom)
    x_global = tx_origin * TILE_SIZE + float(x_pix)
    y_global = ty_origin * TILE_SIZE + float(y_pix)
    x_m = x_global / map_size * 2 * ORIGIN_SHIFT - ORIGIN_SHIFT
    y_m = ORIGIN_SHIFT - y_global / map_size * 2 * ORIGIN_SHIFT
    return [x_m, y_m]


def ground_resolution(lat_deg, zoom):
    """Метров земли на один пиксель тайла на данной широте."""
    proj_res = 2 * ORIGIN_SHIFT / (TILE_SIZE * 2 ** zoom)
    phi = math.radians(lat_deg)
    k = math.cos(phi) / math.sqrt(1 - (E ** 2) * math.sin(phi) ** 2)
    return proj_res * k


def estimate(lat_min, lat_max, lon_min, lon_max, zoom):
    """Оценка объема работы: (число тайлов, память под маску в МБ)."""
    tx_min, tx_max, ty_min, ty_max = tile_range(lat_min, lat_max, lon_min, lon_max, zoom)
    nx = tx_max - tx_min + 1
    ny = ty_max - ty_min + 1
    tiles = nx * ny
    mask_mb = tiles * TILE_SIZE * TILE_SIZE / 1024.0 / 1024.0
    return tiles, mask_mb


def tile_pixel_color(png_bytes, px, py, radius=1):
    """Медианный цвет RGB окрестности пикселя тайла (для пипетки)."""
    if not png_bytes:
        return None
    buf = np.frombuffer(png_bytes, dtype=np.uint8)
    img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    if img is None:
        return None
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
    h, w = rgb.shape[:2]
    x0, x1 = max(0, px - radius), min(w, px + radius + 1)
    y0, y1 = max(0, py - radius), min(h, py + radius + 1)
    if x0 >= x1 or y0 >= y1:
        return None
    patch = rgb[y0:y1, x0:x1].reshape(-1, 3)
    med = np.median(patch, axis=0)
    return tuple(int(v) for v in med)


# ----------------------------------------------------------------------
# Построение маски по тайлам
# ----------------------------------------------------------------------

class MaskBuilder:
    """
    Собирает маску классов зданий, принимая тайлы по одному.

    ranges — список классов, каждый класс — список пар (lower, upper) RGB
    (у класса может быть несколько цветовых диапазонов). В маске каждому
    пикселю присваивается номер класса (1..N) или 0 (фон). Память — один
    байт на пиксель независимо от числа классов. При пересечении
    диапазонов приоритет у класса, который идет раньше в списке.
    """

    def __init__(self, tx_min, tx_max, ty_min, ty_max, ranges=None):
        if ranges is None:
            ranges = [[(DEFAULT_LOWER, DEFAULT_UPPER)]]
        self.tx_min = tx_min
        self.ty_min = ty_min
        self.width = (tx_max - tx_min + 1) * TILE_SIZE
        self.height = (ty_max - ty_min + 1) * TILE_SIZE
        self.ranges = [[(np.array(lo, dtype=np.uint8),
                         np.array(hi, dtype=np.uint8)) for lo, hi in rl]
                       for rl in ranges]
        self.mask = np.zeros((self.height, self.width), dtype=np.uint8)

    def add_tile(self, tx, ty, png_bytes):
        """Декодирует тайл и вписывает его маску. RGB сразу освобождается."""
        if not png_bytes:
            return False
        buf = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)  # BGR
        if img is None:
            return False
        rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
        px = (tx - self.tx_min) * TILE_SIZE
        py = (ty - self.ty_min) * TILE_SIZE
        h = min(rgb.shape[0], TILE_SIZE)
        w = min(rgb.shape[1], TILE_SIZE)
        region = self.mask[py:py + h, px:px + w]
        for idx, range_list in enumerate(self.ranges, start=1):
            for lo, hi in range_list:
                m = cv2.inRange(rgb, lo, hi)[:h, :w]
                region[(m > 0) & (region == 0)] = idx

        # Пиксели подписей: белый ореол текста, насыщенные иконки,
        # темный текст. По ним разрешено затягивать вырезы в зданиях.
        r = rgb[:h, :w].astype(np.int16)
        mx = r.max(axis=2)
        mn = r.min(axis=2)
        # Порог темного 130, а не выше: обводки зданий (~150-200) не должны
        # считаться подписями, иначе соседние здания склеиваются через них.
        label = (mn >= 249) | (mx - mn >= 40) | (mx <= 130)
        # «Холодные» пиксели: зеленый или синий канал заметно выше
        # красного. Все здания и фоны Яндекса теплые или нейтральные,
        # холодными бывают только смеси полупрозрачного бирюзового/синего
        # текста с крышей (и газоны, которые и так насыщенные).
        rr, gg, bb = r[..., 0], r[..., 1], r[..., 2]
        cold = (gg >= rr + 4) | (bb >= rr + 4)
        # Теплый полупрозрачный ореол текста поверх здания. Условие
        # r-b >= 3 отсекает нейтральные светлые фоны (асфальт дворов,
        # подложки территорий), точные цвета фона исключены явно.
        halo = ((mn >= 232) & (mx <= 254) & (rr - bb >= 3)
                & ~((rr == 252) & (gg == 252) & (bb == 247))
                & ~((rr == 246) & (gg == 246) & (bb == 242)))
        # Нейтральный ореол: на серых крышах полупрозрачный белый ореол
        # смешивается в нейтральный светлый серый, неотличимый по цвету
        # от асфальта дворов. Различаем по контексту: нейтральный светлый
        # пиксель считается ореолом, только если рядом (~6 px) есть
        # «ядро» подписи — темный текст, белый центр, иконка, холодный.
        core = label | cold
        neutral = ((mn >= 230) & (mx <= 250) & (mx - mn <= 10)
                   & ~((rr == 246) & (gg == 246) & (bb == 242)))
        near_core = cv2.dilate(core.astype(np.uint8),
                               cv2.getStructuringElement(
                                   cv2.MORPH_ELLIPSE, (13, 13))) > 0
        # Стены зданий: приглушенные умеренно насыщенные оттенки.
        # Проверяются РАНЬШЕ подписей: стены цветных зданий (сиреневые,
        # розовые) тоже «холодные»/«насыщенные», но должны остаться
        # стенами (heal-only), иначе корпуса склеятся через них.
        wall = (mn >= 190) & (mx <= 235) & (mx - mn <= 35)
        region[wall & (region == 0)] = WALL_ID
        region[(label | cold | halo | (neutral & near_core))
               & (region == 0)] = LABEL_ID
        return True

    def class_mask(self, idx):
        """Бинарная маска (0/255) класса с номером idx (1..N)."""
        return np.where(self.mask == idx, 255, 0).astype(np.uint8)

    def label_mask(self):
        """Маска (0/255) подписей, иконок и ореолов — для заращивания."""
        return np.where(self.mask == LABEL_ID, 255, 0).astype(np.uint8)

    def wall_mask(self):
        """Маска (0/255) пикселей стен зданий."""
        return np.where(self.mask == WALL_ID, 255, 0).astype(np.uint8)


# ----------------------------------------------------------------------
# Морфология, контуры, полигоны
# ----------------------------------------------------------------------

def clean_mask(mask, label_radius=10, allowed=None):
    """
    Морфологическая чистка.

    label_radius — радиус «заращивания» подписей в пикселях. Номера домов
    и иконки рисуются поверх зданий и выгрызают маску; закрытие
    эллиптическим ядром 2r+1 затягивает эти вырезы.

    allowed — бинарная маска пикселей подписей/иконок. Если задана,
    заращивание разрешено только по исходным пикселям здания и пикселям
    подписей: обычный фон не затягивается, поэтому вогнутые углы зданий
    не заплывают, а соседние здания не склеиваются через двор.
    """
    small = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))

    def rclose(src, kernel, iterations=1):
        """Закрытие, при allowed ограниченное пикселями здания и подписей.
        Тонкие разделители между соседними зданиями не затягиваются."""
        c = cv2.morphologyEx(src, cv2.MORPH_CLOSE, kernel,
                             iterations=iterations)
        if allowed is not None:
            c = cv2.bitwise_and(c, cv2.bitwise_or(src, allowed))
        return c

    # открытие убирает антиалиасные ниточки (заборы, обводки)
    m = cv2.morphologyEx(mask, cv2.MORPH_OPEN, small)
    m = rclose(m, small, 2)
    if label_radius > 0:
        k = 2 * label_radius + 1
        big = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
        m = rclose(m, big)
        # сгладить рваную границу после ограничения
        m = rclose(m, small, 2)
        m = cv2.morphologyEx(m, cv2.MORPH_OPEN, small)
    else:
        m = rclose(m, small, 3)
    return m


def absorb_labels(mask, label, min_contact=0.55, max_comp=150000):
    """
    Вливает в маску здания компоненты подписи, плотно окруженные крышей.

    Ряды подписей («Аптека», «Медцентр», «Мята» друг под другом) режут
    здание на горизонтальные полосы, которые не перекрыть радиусом
    заращивания. Если кайма компоненты подписи на min_contact и больше
    лежит на пикселях здания — она зажата между кусками крыши и
    поглощается. Названия улиц и подписи на фоне так не проходят:
    их кайма лежит на фоне.
    """
    lab_bin = (label > 0).astype(np.uint8)
    num, comps, stats, _ = cv2.connectedComponentsWithStats(lab_bin, 8)
    out = mask.copy()
    k = np.ones((3, 3), np.uint8)
    H, W = mask.shape
    for i in range(1, num):
        x, y, w, h, area = stats[i]
        if area < 30 or area > max_comp:
            continue
        x0, y0 = max(x - 2, 0), max(y - 2, 0)
        x1, y1 = min(x + w + 2, W), min(y + h + 2, H)
        roi = (comps[y0:y1, x0:x1] == i).astype(np.uint8)
        ring = (cv2.dilate(roi, k) > 0) & (roi == 0)
        ring_n = int(ring.sum())
        if ring_n == 0:
            continue
        contact = float((mask[y0:y1, x0:x1][ring] > 0).sum()) / ring_n
        if contact >= min_contact:
            out[y0:y1, x0:x1][roi > 0] = 255
    return out


def heal_label_bites(mask, label, wall=None, max_bg_share=0.35,
                     max_wall_edge=0.50):
    """
    Лечит большие вырезы от иконок и подписей через выпуклую оболочку.

    Для каждого контура берутся куски, которых не хватает до его выпуклой
    оболочки. Кусок заполняется при двух условиях сразу:
    1) доля обычного фона в нем не выше max_bg_share (фон — все, что
       не подпись и не стена);
    2) полоса куска, прилегающая к крыше, состоит не из стены,
       а из подписи/ореола (доля стены < max_wall_edge).
    Настоящий вырез прогрызен текстом прямо в крыше — вдоль крыши в нем
    лежит текст. Вогнутый угол здания отделен от крыши полосой стен
    (Яндекс рисует стену вдоль кромки крыши), поэтому у него
    приграничная полоса стенная — угол не заливается.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL,
                                   cv2.CHAIN_APPROX_SIMPLE)
    out = mask.copy()
    # расширяем подписи на 1 px: антиалиасная кайма букв не должна
    # считаться фоном и блокировать лечение мелких вырезов
    k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
    label = cv2.dilate(label, k3)
    for cnt in contours:
        if cv2.contourArea(cnt) < 50 or len(cnt) < 4:
            continue
        hull = cv2.convexHull(cnt)
        x, y, w, h = cv2.boundingRect(hull)
        shift = np.array([[x, y]])
        roi_cnt = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(roi_cnt, [cnt - shift], -1, 255, -1)
        roi_hull = np.zeros((h, w), dtype=np.uint8)
        cv2.drawContours(roi_hull, [hull - shift], -1, 255, -1)
        diff = cv2.bitwise_and(roi_hull, cv2.bitwise_not(roi_cnt))
        if not diff.any():
            continue
        n, comps = cv2.connectedComponents(diff)
        roi_label = label[y:y + h, x:x + w]
        roi_wall = wall[y:y + h, x:x + w] if wall is not None else None
        k3 = cv2.getStructuringElement(cv2.MORPH_RECT, (5, 5))
        roof_zone = cv2.dilate(roi_cnt, k3) > 0  # окрестность крыши
        for i in range(1, n):
            comp = comps == i
            carea = int(comp.sum())
            if carea == 0:
                continue
            lab_cnt = int((roi_label[comp] > 0).sum())
            wall_cnt = (int((roi_wall[comp] > 0).sum())
                        if roi_wall is not None else 0)
            bg_cnt = carea - lab_cnt - wall_cnt
            if bg_cnt > max_bg_share * carea:
                continue
            # полоса куска вдоль крыши: стена там или подпись?
            near = comp & roof_zone
            n_near = int(near.sum())
            if n_near == 0:
                continue  # кусок вообще не касается крыши
            if roi_wall is not None:
                wall_edge = float((roi_wall[near] > 0).sum()) / n_near
                if wall_edge > max_wall_edge:
                    continue  # отделен от крыши стеной — это угол
            out_roi = out[y:y + h, x:x + w]
            out_roi[comp] = 255
    return out


def _dominant_angle(pts):
    """
    Доминирующее направление ребер полигона (взвешенное длинами,
    с периодом 90°). Устойчиво к скругленным морфологией углам,
    в отличие от угла minAreaRect.
    """
    pts = np.asarray(pts, dtype=np.float64)
    d = np.roll(pts, -1, axis=0) - pts
    lens = np.hypot(d[:, 0], d[:, 1])
    if lens.sum() <= 0:
        return None
    ang = np.arctan2(d[:, 1], d[:, 0])
    vx = float((lens * np.cos(4 * ang)).sum())
    vy = float((lens * np.sin(4 * ang)).sum())
    if vx == 0 and vy == 0:
        return None
    return math.atan2(vy, vx) / 4.0


def _oriented_box(cnt):
    """Прямоугольник, выровненный по доминирующему направлению ребер."""
    pts = cv2.approxPolyDP(cnt, 2.0, True)[:, 0].astype(np.float64)
    ang = _dominant_angle(pts)
    if ang is None:
        return cv2.boxPoints(cv2.minAreaRect(cnt))
    c, s = math.cos(-ang), math.sin(-ang)
    rot = np.array([[c, -s], [s, c]])
    ctr = pts.mean(axis=0)
    rp = (pts - ctr) @ rot.T
    x0, y0 = rp.min(axis=0)
    x1, y1 = rp.max(axis=0)
    box = np.array([[x0, y0], [x1, y0], [x1, y1], [x0, y1]])
    back = np.array([[math.cos(ang), -math.sin(ang)],
                     [math.sin(ang), math.cos(ang)]])
    return box @ back.T + ctr


def _orthogonalize(pts, angle_tol=20.0, min_share=0.75):
    """
    Спрямляет полигон до прямых углов (как у зданий), если большинство
    его ребер идет вдоль двух перпендикулярных направлений.
    Возвращает новый массив точек или None, если форма не прямоугольная
    по характеру (например, скошенная крыша) или результат вырожден.
    """
    pts = np.asarray(pts, dtype=np.float64)
    if len(pts) < 4:
        return None
    rect = cv2.minAreaRect(pts.astype(np.float32))
    ang = _dominant_angle(pts)
    if ang is None:
        ang = np.deg2rad(rect[2])
    ctr = np.array(rect[0])
    c, s = np.cos(-ang), np.sin(-ang)
    rot = np.array([[c, -s], [s, c]])
    rp = (pts - ctr) @ rot.T

    edges = np.roll(rp, -1, axis=0) - rp
    lens = np.hypot(edges[:, 0], edges[:, 1])
    total = lens.sum()
    if total <= 0:
        return None
    # доля периметра вдоль осей
    ax = np.abs(np.rad2deg(np.arctan2(edges[:, 1], edges[:, 0]))) % 90.0
    dev = np.minimum(ax, 90.0 - ax)
    if lens[dev <= angle_tol].sum() / total < min_share:
        return None

    # группируем последовательные ребра одного направления
    groups = []  # (направление, координата, суммарная длина)
    n = len(rp)
    for i in range(n):
        p0, p1 = rp[i], rp[(i + 1) % n]
        horiz = abs(edges[i][0]) >= abs(edges[i][1])
        coord = (p0[1] + p1[1]) / 2 if horiz else (p0[0] + p1[0]) / 2
        w = lens[i]
        if w == 0:
            continue
        if groups and groups[-1][0] == horiz:
            d, cc, ww = groups[-1]
            groups[-1] = (d, (cc * ww + coord * w) / (ww + w), ww + w)
        else:
            groups.append((horiz, coord, w))
    if len(groups) >= 2 and groups[0][0] == groups[-1][0]:
        d, cc, ww = groups.pop()
        d0, c0, w0 = groups[0]
        groups[0] = (d0, (c0 * w0 + cc * ww) / (w0 + ww), w0 + ww)
    if len(groups) < 4 or len(groups) % 2 == 1:
        return None

    verts = []
    for i in range(len(groups)):
        h1, c1, _ = groups[i]
        h2, c2, _ = groups[(i + 1) % len(groups)]
        if h1 == h2:
            return None
        verts.append((c2, c1) if h1 else (c1, c2))
    verts = np.array(verts, dtype=np.float64)

    area_new = abs(cv2.contourArea(verts.astype(np.float32)))
    area_old = abs(cv2.contourArea(rp.astype(np.float32)))
    if area_old <= 0 or not 0.5 <= area_new / area_old <= 1.6:
        return None

    back = np.array([[np.cos(ang), -np.sin(ang)],
                     [np.sin(ang), np.cos(ang)]])
    return verts @ back.T + ctr


def fill_small_holes(mask, min_area):
    """
    Заполняет внутренние дыры меньше 1/3 площади контура.
    Вместо перебора с bitwise_not по всей картинке (как в прототипе)
    используется иерархия контуров — заметно быстрее на больших областях.
    """
    contours, hierarchy = cv2.findContours(mask, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(mask)
    if hierarchy is None:
        return filled
    hierarchy = hierarchy[0]
    for i, cnt in enumerate(contours):
        if hierarchy[i][3] != -1:      # это дыра, а не внешний контур
            continue
        area = cv2.contourArea(cnt)
        if area <= min_area:
            continue
        cv2.drawContours(filled, [cnt], -1, 255, -1)  # заливаем целиком
        child = hierarchy[i][2]
        while child != -1:             # возвращаем большие дыры
            if cv2.contourArea(contours[child]) >= area / 3.0:
                cv2.drawContours(filled, [contours[child]], -1, 0, -1)
            child = hierarchy[child][0]
    return filled


def _poly_iou(pts_a, pts_b):
    """IoU двух полигонов через растеризацию в общем окне."""
    a = np.asarray(pts_a, dtype=np.float64)
    b = np.asarray(pts_b, dtype=np.float64)
    allp = np.vstack([a, b])
    x0, y0 = np.floor(allp.min(axis=0)) - 1
    x1, y1 = np.ceil(allp.max(axis=0)) + 1
    w, h = int(x1 - x0), int(y1 - y0)
    if w <= 0 or h <= 0 or w * h > 4_000_000:
        return 1.0  # слишком крупно для проверки — не блокируем
    ra = np.zeros((h, w), np.uint8)
    rb = np.zeros((h, w), np.uint8)
    cv2.fillPoly(ra, [(a - [x0, y0]).astype(np.int32)], 1)
    cv2.fillPoly(rb, [(b - [x0, y0]).astype(np.int32)], 1)
    inter = int(np.logical_and(ra, rb).sum())
    union = int(np.logical_or(ra, rb).sum())
    return inter / union if union else 0.0


def contours_to_features(mask, tx_min, ty_min, zoom, min_area=100,
                         rect_threshold=0.82, simplify=0.015,
                         min_width=8, offset=(0.0, 0.0), eps_cap=8.0):
    """
    Финальные контуры -> список GeoJSON-фич в EPSG:3395.

    rect_threshold — если площадь контура покрывает такую долю его
    минимального повернутого прямоугольника, контур заменяется этим
    прямоугольником. Иначе пробуем ортогонализацию (спрямление до
    прямых углов для Г/Т/П-образных зданий). 0 отключает и то, и другое.
    simplify — доля периметра для упрощения контуров-исключений.
    min_width — минимальная ширина объекта в пикселях: тонкие вытянутые
    объекты (заборы, обводки дорог) отбрасываются.
    offset — сдвиг результата в пикселях (x вправо, y вниз): компенсация
    псевдо-3D Яндекса, который смещает крышу здания влево-вверх.
    eps_cap — потолок допуска упрощения в пикселях. Без него допуск
    растет пропорционально периметру, и у больших агломераций
    упрощение срезает целые выступы диагоналями.
    """
    contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    features = []
    fid = 0
    off_x, off_y = offset
    for cnt in contours:
        area = cv2.contourArea(cnt)
        if area <= min_area:
            continue

        rect = cv2.minAreaRect(cnt)
        rect_w, rect_h = rect[1]
        rect_area = rect_w * rect_h

        if min_width > 0:
            # Толщина как диаметр максимальной вписанной окружности:
            # у изогнутого забора минимальный повернутый прямоугольник
            # широкий (короткая сторона равна плечу изгиба), а вписанная
            # окружность честно меряет толщину ленты любой формы.
            bx, by, bw, bh = cv2.boundingRect(cnt)
            # рамка в 1 px, чтобы у distanceTransform всегда был ноль
            roi = np.zeros((bh + 2, bw + 2), dtype=np.uint8)
            cv2.drawContours(roi, [cnt - np.array([[bx - 1, by - 1]])],
                             -1, 255, -1)
            thickness = 2.0 * float(
                cv2.distanceTransform(roi, cv2.DIST_L2, 3).max())
            if thickness < min_width:
                continue  # забор, обводка, прочие тонкие объекты

        polygon_pts = None
        if rect_threshold > 0 and rect_area > 0:
            # Сначала всегда ортогонализация: она сохраняет ступеньки
            # и выемки с прямыми углами, а чистый прямоугольник сама
            # сводит к 4 вершинам. Дома с небольшими выступами больше
            # не выпрямляются в сплошной прямоугольник.
            arc = cv2.arcLength(cnt, True)
            eps_fine = min(0.006 * arc, eps_cap * 0.6)
            fine = cv2.approxPolyDP(cnt, eps_fine, True)[:, 0]
            polygon_pts = _orthogonalize(fine)
            # спрямление принимается, только если хорошо совпадает
            # с исходным контуром (агломерации корпусов под разными
            # углами нельзя вписывать в одну сетку)
            if (polygon_pts is not None
                    and _poly_iou(fine, polygon_pts) < 0.90):
                polygon_pts = None
            # запасной вариант: ортогонализация не вышла, но форма
            # по заполнению почти прямоугольная — ровный прямоугольник
            # по доминирующему направлению ребер
            if polygon_pts is None and area / rect_area >= rect_threshold:
                polygon_pts = _oriented_box(cnt)
        if polygon_pts is None:
            # Не прямоугольная по характеру форма — упрощенный контур
            epsilon = min(simplify * cv2.arcLength(cnt, True), eps_cap)
            approx = cv2.approxPolyDP(cnt, epsilon, True)
            if len(approx) == 4 and cv2.isContourConvex(approx):
                polygon_pts = _oriented_box(cnt)
            else:
                polygon_pts = approx[:, 0]

        if len(polygon_pts) < 3:
            continue

        ring = [pixel_to_merc(p[0] + off_x, p[1] + off_y,
                              tx_min, ty_min, zoom) for p in polygon_pts]
        ring.append(list(ring[0]))  # замыкаем кольцо

        fid += 1
        features.append({
            "type": "Feature",
            "geometry": {"type": "Polygon", "coordinates": [ring]},
            "properties": {"id": fid, "area_px": float(area)},
        })
    return features


def build_geojson(features):
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::3395"}},
        "features": features,
    }


def process_mask(mask, tx_min, ty_min, zoom, min_area=100,
                 label_radius=10, rect_threshold=0.82, simplify=0.015,
                 min_width=8, offset=(0.0, 0.0), allowed=None, eps_cap=8.0,
                 wall=None):
    """Полный конвейер: чистка -> лечение вырезов -> дыры -> GeoJSON dict.

    allowed — маска подписей (для заращивания и лечения);
    wall — маска стен, нейтральная при лечении через оболочку.
    """
    m = mask
    if allowed is not None:
        # ряды подписей, зажатые между кусками крыши, вливаются в здание
        m = absorb_labels(m, allowed)
    m = clean_mask(m, label_radius, allowed)
    if allowed is not None:
        m = heal_label_bites(m, allowed, wall)
    m = fill_small_holes(m, min_area)
    feats = contours_to_features(m, tx_min, ty_min, zoom, min_area,
                                 rect_threshold, simplify, min_width, offset,
                                 eps_cap)
    return build_geojson(feats)
