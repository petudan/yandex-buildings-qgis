# -*- coding: utf-8 -*-


def classFactory(iface):
    from .plugin import YandexBuildingsPlugin
    return YandexBuildingsPlugin(iface)
