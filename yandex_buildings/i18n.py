# -*- coding: utf-8 -*-
"""
Простая локализация расширения (русский / английский).

Язык хранится в настройках QGIS. По умолчанию — язык интерфейса QGIS
(русский, если локаль начинается с "ru", иначе английский).
Строки задаются парами (ru, en); tr(key, **kw) подставляет параметры
через str.format.
"""

from qgis.core import QgsSettings

LANG_KEY = "yandex_buildings/lang"
LANGS = ("ru", "en")

_lang = None


def get_lang():
    global _lang
    if _lang is None:
        s = QgsSettings()
        val = s.value(LANG_KEY, "")
        if val not in LANGS:
            locale = str(s.value("locale/userLocale", "") or "")
            val = "ru" if locale.lower().startswith("ru") else "en"
        _lang = val
    return _lang


def set_lang(lang):
    global _lang
    if lang in LANGS:
        _lang = lang
        QgsSettings().setValue(LANG_KEY, lang)


def tr(key, **kw):
    pair = STRINGS.get(key)
    if pair is None:
        return key
    text = pair[0] if get_lang() == "ru" else pair[1]
    return text.format(**kw) if kw else text


# Стандартные категории: стабильный ключ -> название
BUILTIN_KEYS = ("residential", "nonresidential", "public",
                "educational", "medical", "cultural")

# Русские названия из прежних версий -> ключ (миграция сохраненных настроек)
LEGACY_NAMES = {
    "Жилые": "residential",
    "Нежилые": "nonresidential",
    "Общественные": "public",
    "Учебные": "educational",
    "Медицинские": "medical",
    "Культурные": "cultural",
}


def builtin_name(key):
    return tr("cat_" + key)


STRINGS = {
    # --- меню и заголовки ---
    "menu_action": ("Извлечение зданий (Яндекс)",
                    "Extract buildings (Yandex)"),
    "window_title": ("Извлечение зданий с карты Яндекса",
                     "Extract buildings from Yandex Maps"),
    "task_title": ("Извлечение зданий с карты Яндекса",
                   "Extracting buildings from Yandex Maps"),
    "msgbar_title": ("Извлечение зданий", "Building extraction"),
    "language": ("Язык:", "Language:"),

    # --- категории ---
    "cat_residential": ("Жилые", "Residential"),
    "cat_nonresidential": ("Нежилые", "Non-residential"),
    "cat_public": ("Общественные", "Public"),
    "cat_educational": ("Учебные", "Educational"),
    "cat_medical": ("Медицинские", "Medical"),
    "cat_cultural": ("Культурные", "Cultural"),

    # --- блок «Область» ---
    "grp_area": ("Область", "Area"),
    "area_not_set": ("Область не задана", "Area not set"),
    "area_coords": ("Широта: {lat0:.6f} … {lat1:.6f}\n"
                    "Долгота: {lon0:.6f} … {lon1:.6f}",
                    "Latitude: {lat0:.6f} … {lat1:.6f}\n"
                    "Longitude: {lon0:.6f} … {lon1:.6f}"),
    "btn_draw": ("Нарисовать область на карте", "Draw area on map"),
    "btn_hide_rect": ("Скрыть рамку", "Hide frame"),

    # --- блок категорий ---
    "grp_classes": ("Типы зданий (каждый — отдельным слоем)",
                    "Building types (each as a separate layer)"),
    "classes_hint": (
        "Цвет заливки на карте Яндекса, RGB «от» и «до»; несколько\n"
        "диапазонов — через точку с запятой. Пипетка (кнопка «⊕»)\n"
        "добавляет диапазон по клику на здание на карте.",
        "Fill color on Yandex Maps, RGB \"from\" and \"to\"; separate\n"
        "multiple ranges with semicolons. The eyedropper (\"⊕\" button)\n"
        "adds a range by clicking a building on the map."),
    "btn_add_cat": ("Добавить категорию", "Add category"),
    "btn_reset_cat": ("Сбросить к стандартным", "Reset to defaults"),
    "tip_pick": ("Пипетка: кликните по зданию на карте —\n"
                 "его цвет добавится диапазоном в категорию",
                 "Eyedropper: click a building on the map —\n"
                 "its color will be added to the category as a range"),
    "tip_delete": ("Удалить категорию", "Delete category"),
    "dlg_new_cat_title": ("Новая категория", "New category"),
    "dlg_new_cat_label": ("Название категории:", "Category name:"),
    "dlg_cat_exists_title": ("Категория существует", "Category exists"),
    "dlg_cat_exists": ("Категория «{name}» уже есть.",
                       "Category \"{name}\" already exists."),
    "dlg_del_title": ("Удалить категорию", "Delete category"),
    "dlg_del": ("Удалить категорию «{name}»?",
                "Delete category \"{name}\"?"),
    "dlg_reset_title": ("Сбросить категории", "Reset categories"),
    "dlg_reset": ("Вернуть стандартный набор категорий? Ваши категории и\n"
                  "изменения диапазонов будут удалены.",
                  "Restore the default category set? Your categories and\n"
                  "range changes will be removed."),
    "picked_status": ("Пипетка: цвет RGB({r}, {g}, {b}) добавлен в «{name}».",
                      "Eyedropper: color RGB({r}, {g}, {b}) added to "
                      "\"{name}\"."),

    # --- блок параметров ---
    "grp_params": ("Параметры", "Parameters"),
    "lbl_zoom": ("Зум тайлов:", "Tile zoom:"),
    "tip_zoom": ("Каждый шаг зума увеличивает число тайлов в 4 раза.\n"
                 "На зуме 21 в лимит 4000 тайлов помещается область около\n"
                 "600х600 м, на зуме 19 — около 2.5х2.5 км.",
                 "Each zoom step multiplies the tile count by 4.\n"
                 "At zoom 21 a 4000-tile limit covers about 600x600 m,\n"
                 "at zoom 19 about 2.5x2.5 km."),
    "lbl_tiles_limit": ("Лимит тайлов:", "Tile limit:"),
    "tip_tiles_limit": (
        "При превышении лимита расширение предупредит, но позволит\n"
        "продолжить. Ориентир: 4000 тайлов — это ~1 ГБ памяти в пике\n"
        "и несколько минут работы; память и время растут линейно.",
        "If the limit is exceeded, the plugin warns but lets you\n"
        "continue. Rough guide: 4000 tiles is ~1 GB peak memory and\n"
        "a few minutes of work; memory and time grow linearly."),
    "lbl_min_area": ("Мин. площадь, м²:", "Min. area, m²:"),
    "tip_min_area": ("Объекты меньшей площади отбрасываются. Отсекает ложные\n"
                     "срабатывания на плашках номеров домов. Задается в\n"
                     "метрах, в пиксели пересчитывается по зуму.",
                     "Smaller objects are discarded. Removes false hits on\n"
                     "house-number plates. Set in meters, converted to\n"
                     "pixels by zoom automatically."),
    "lbl_min_width": ("Мин. ширина, м:", "Min. width, m:"),
    "tip_min_width": ("Объекты уже этой ширины отбрасываются: заборы,\n"
                      "обводки дорог и прочие тонкие линии.",
                      "Objects thinner than this are discarded: fences,\n"
                      "road outlines and other thin lines."),
    "lbl_offset": ("Сдвиг результата, пикс:", "Result offset, px:"),
    "lbl_right": ("вправо:", "right:"),
    "lbl_down": ("вниз:", "down:"),
    "tip_offset": ("Яндекс рисует здания с псевдо-3D: видимая крыша\n"
                   "сдвинута влево-вверх относительно подошвы. Положительные\n"
                   "значения сдвигают результат обратно (обычно 3–6 px для\n"
                   "1–2 этажей на зуме 19).",
                   "Yandex draws buildings in pseudo-3D: the visible roof is\n"
                   "shifted up-left from the footprint. Positive values shift\n"
                   "the result back (usually 3–6 px for 1–2 floors at\n"
                   "zoom 19)."),
    "lbl_label_radius": ("Заращивание подписей, px:", "Label healing, px:"),
    "tip_label_radius": ("Номера домов рисуются поверх зданий и выгрызают\n"
                         "контур. Этот радиус затягивает такие вырезы. Если\n"
                         "соседние здания склеиваются — уменьшите значение.",
                         "House numbers are drawn over buildings and bite\n"
                         "into the outline. This radius closes such gaps.\n"
                         "If neighboring buildings merge, reduce it."),
    "chk_rect": ("Спрямлять прямые углы зданий",
                 "Square up building corners"),
    "tip_rect": ("Контур спрямляется до прямых углов с сохранением\n"
                 "выступов; почти прямоугольные здания — до прямоугольника.",
                 "Outlines are squared to right angles keeping\n"
                 "protrusions; near-rectangular buildings become rectangles."),

    # --- блок результата и кнопки ---
    "grp_output": ("Результат", "Output"),
    "out_placeholder": ("Базовое имя файла; добавится суффикс типа",
                        "Base file name; a type suffix will be added"),
    "dlg_save_geojson": ("Сохранить GeoJSON", "Save GeoJSON"),
    "btn_run": ("Запустить", "Run"),
    "btn_cancel": ("Отменить", "Cancel"),
    "tip_cancel": ("Остановить загрузку тайлов и обработку",
                   "Stop tile download and processing"),
    "btn_close": ("Закрыть", "Close"),

    # --- проверки ввода ---
    "err_empty_cat_title": ("Пустая категория", "Empty category"),
    "err_empty_cat": ("У категории «{name}» нет цветовых диапазонов.\n"
                      "Добавьте цвет пипеткой или текстом, либо снимите\n"
                      "с нее галочку.",
                      "Category \"{name}\" has no color ranges.\n"
                      "Add a color with the eyedropper or as text, or\n"
                      "uncheck it."),
    "err_title": ("Ошибка", "Error"),
    "err_rgb": ("Категория «{name}»: цвет задается тремя числами 0–255\n"
                "через запятую, например: 230, 225, 220. Несколько\n"
                "диапазонов — через точку с запятой, их число в полях\n"
                "«от» и «до» должно совпадать.",
                "Category \"{name}\": a color is three numbers 0–255\n"
                "separated by commas, e.g. 230, 225, 220. Separate\n"
                "multiple ranges with semicolons; the number of ranges in\n"
                "\"from\" and \"to\" must match."),
    "err_no_classes_title": ("Нет категорий", "No categories"),
    "err_no_classes": ("Включите хотя бы один тип зданий.",
                       "Enable at least one building type."),
    "err_no_area_title": ("Нет области", "No area"),
    "err_no_area": ("Сначала нарисуйте область на карте.",
                    "Draw an area on the map first."),

    # --- лимиты тайлов ---
    "limit_title": ("Превышен лимит тайлов", "Tile limit exceeded"),
    "limit_text": ("На зуме {zoom} потребуется {tiles} тайлов — больше\n"
                   "вашего лимита ({limit}).\n"
                   "Оценка: ~{mb:.0f} МБ под маску (в пике обработки в 4-5\n"
                   "раз больше), загрузка и обработка могут занять заметное\n"
                   "время. Шаг зума вниз сокращает число тайлов в 4 раза.\n\n"
                   "Продолжить все равно?",
                   "Zoom {zoom} requires {tiles} tiles — more than your\n"
                   "limit ({limit}).\n"
                   "Estimate: ~{mb:.0f} MB for the mask (4-5x more at peak),\n"
                   "download and processing may take a while. One zoom\n"
                   "step down reduces the tile count by 4.\n\n"
                   "Continue anyway?"),
    "big_title": ("Большая область", "Large area"),
    "big_text": ("Потребуется скачать {tiles} тайлов (маска займет\n"
                 "~{mb:.0f} МБ памяти). Продолжить?",
                 "{tiles} tiles will be downloaded (the mask will take\n"
                 "~{mb:.0f} MB of memory). Continue?"),

    # --- выполнение ---
    "status_loading": ("Загрузка {tiles} тайлов…",
                       "Downloading {tiles} tiles…"),
    "status_cancelling": ("Отменяю…", "Cancelling…"),
    "layer_name": ("Здания: {name} (Яндекс)", "Buildings: {name} (Yandex)"),
    "result_found": ("Найдено зданий — {parts}.",
                     "Buildings found — {parts}."),
    "result_failed_tiles": (" Не загрузилось тайлов: {n}.",
                            " Tiles failed to load: {n}."),
    "result_bad_layers": (" Часть слоев не удалось загрузить.",
                          " Some layers could not be loaded."),
    "task_failed": ("Задача отменена или завершилась с ошибкой.",
                    "The task was cancelled or failed."),
    "err_no_tiles": ("Ни один тайл не загрузился. Возможно, зум {zoom}\n"
                     "недоступен у Яндекса для этой территории — попробуйте\n"
                     "зум ниже. Либо проверьте доступ в интернет.",
                     "No tiles were downloaded. Zoom {zoom} may be\n"
                     "unavailable on Yandex for this territory — try a lower\n"
                     "zoom. Or check your internet connection."),
    "err_too_many": ("Область слишком большая: {n} тайлов (лимит {limit}).",
                     "Area too large: {n} tiles (limit {limit})."),

    # --- пипетка ---
    "pick_title": ("Пипетка", "Eyedropper"),
    "pick_hint": ("Кликните по зданию на карте — его цвет добавится "
                  "в категорию.",
                  "Click a building on the map — its color will be added "
                  "to the category."),
    "pick_no_tile": ("Не удалось получить тайл в этой точке — проверьте "
                     "доступ в интернет.",
                     "Could not get the tile at this point — check your "
                     "internet connection."),
    "pick_bg": ("Снятый цвет RGB{rgb} совпадает с фоном карты — диапазон "
                "захватил бы пустые области. Кликните точнее по зданию.",
                "The picked color RGB{rgb} matches the map background — "
                "the range would capture empty areas. Click more precisely "
                "on a building."),

    # --- зависимости ---
    "dep_title": ("Нужна библиотека OpenCV", "OpenCV library required"),
    "dep_text": ("Для распознавания зданий требуется библиотека OpenCV\n"
                 "(opencv-python-headless). Установить ее сейчас через pip?\n\n"
                 "Установка займет около минуты.",
                 "Building recognition requires the OpenCV library\n"
                 "(opencv-python-headless). Install it now via pip?\n\n"
                 "Installation takes about a minute."),
    "dep_manual_title": ("Установка вручную", "Manual installation"),
    "dep_manual": ("Откройте OSGeo4W Shell (Windows) или терминал и "
                   "выполните:\n\npip install opencv-python-headless\n\n"
                   "Затем перезапустите QGIS.",
                   "Open the OSGeo4W Shell (Windows) or a terminal and run:"
                   "\n\npip install opencv-python-headless\n\n"
                   "Then restart QGIS."),
    "dep_fail_title": ("Не удалось установить", "Installation failed"),
    "dep_fail": ("Автоматическая установка не сработала:\n{err}\n\n"
                 "Установите вручную: откройте OSGeo4W Shell и выполните\n"
                 "pip install opencv-python-headless, затем перезапустите "
                 "QGIS.",
                 "Automatic installation failed:\n{err}\n\n"
                 "Install manually: open the OSGeo4W Shell and run\n"
                 "pip install opencv-python-headless, then restart QGIS."),
}
