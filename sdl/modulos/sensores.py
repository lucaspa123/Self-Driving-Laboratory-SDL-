"""Sensores disponibles al inicio: temperatura (DS18B20) y color por cámara."""
from __future__ import annotations

import random

from .base import ErrorModulo, Modulo


class SensorTemperatura(Modulo):
    TIPO = "temperatura"
    DRIVER = "ds18b20"
    NOMBRE = "Sensor de temperatura (DS18B20)"
    DESCRIPCION = "Sonda sumergible. Mide la temperatura del líquido."
    CONFIG = {
        "correccion": {"etiqueta": "Corrección de calibración", "valor": 0.0, "unidad": "°C"},
        "pin_datos": {"etiqueta": "Pin de datos (GPIO)", "valor": 37, "avanzado": True},
    }
    MEDICIONES = {"temperatura": {"etiqueta": "Temperatura", "unidad": "°C"}}

    def config_firmware(self) -> dict:
        return {"pin": self.config["pin_datos"]}

    def autotest(self) -> tuple[bool, str]:
        valor = self.medir("temperatura")
        return True, f"Responde. Lectura actual: {valor:.1f} °C."

    def medir(self, magnitud: str) -> float:
        if magnitud != "temperatura":
            raise ErrorModulo(f"{self.etiqueta} no mide '{magnitud}'.")
        valor = float(self.enlace.medir(self.id, "temperatura")) + float(self.config["correccion"])
        self.estado["ultima"] = round(valor, 2)
        return round(valor, 2)

    def resumen(self) -> str:
        ultima = self.estado.get("ultima")
        return f"Última lectura {ultima:.1f} °C" if ultima is not None else ""


class CamaraColor(Modulo):
    """Mide el color medio de una zona fija de la imagen.

    Es una versión básica y autónoma. El punto de conexión con el detector
    YOLO del proyecto (detector.py) es el método _capturar_hsv: basta con
    reemplazarlo por una llamada a ese detector.
    """
    TIPO = "camara"
    USA_ESP32 = False
    NOMBRE = "Cámara (color del líquido)"
    DESCRIPCION = "Mide tono, saturación y brillo del líquido con la cámara de la PC."
    CONFIG = {
        "indice_camara": {"etiqueta": "Número de cámara", "valor": 0},
        "zona": {"etiqueta": "Tamaño de la zona central analizada", "valor": 20, "unidad": "% de la imagen"},
        "fotogramas": {"etiqueta": "Fotogramas promediados", "valor": 5, "avanzado": True},
    }
    MEDICIONES = {
        "tono": {"etiqueta": "Tono del color", "unidad": "°"},
        "saturacion": {"etiqueta": "Saturación del color", "unidad": "%"},
        "brillo": {"etiqueta": "Brillo", "unidad": "%"},
    }

    def _capturar_hsv(self) -> tuple[float, float, float]:
        try:
            import cv2
            import numpy as np
        except ImportError:
            raise ErrorModulo("Falta instalar OpenCV (pip install opencv-python) para usar la cámara.")
        camara = cv2.VideoCapture(int(self.config["indice_camara"]))
        try:
            if not camara.isOpened():
                raise ErrorModulo("No se pudo abrir la cámara.")
            muestras = []
            for _ in range(int(self.config["fotogramas"]) + 3):
                ok, imagen = camara.read()
                if ok:
                    alto, ancho = imagen.shape[:2]
                    f = float(self.config["zona"]) / 200.0
                    zona = imagen[int(alto * (0.5 - f)):int(alto * (0.5 + f)),
                                  int(ancho * (0.5 - f)):int(ancho * (0.5 + f))]
                    muestras.append(cv2.cvtColor(zona, cv2.COLOR_BGR2HSV).reshape(-1, 3).mean(axis=0))
            if len(muestras) <= 3:
                raise ErrorModulo("La cámara no entregó imágenes.")
            h, s, v = np.mean(muestras[3:], axis=0)        # los primeros fotogramas se descartan
            return float(h) * 2.0, float(s) / 2.55, float(v) / 2.55
        finally:
            camara.release()

    def autotest(self) -> tuple[bool, str]:
        if self.enlace is not None and self.enlace.simulado:
            return True, "Simulada."
        self._capturar_hsv()
        return True, "La cámara entrega imágenes."

    def medir(self, magnitud: str) -> float:
        if magnitud not in self.MEDICIONES:
            raise ErrorModulo(f"{self.etiqueta} no mide '{magnitud}'.")
        if self.enlace is not None and self.enlace.simulado:
            return round(random.uniform(0, 100), 1)
        tono, saturacion, brillo = self._capturar_hsv()
        return round({"tono": tono, "saturacion": saturacion, "brillo": brillo}[magnitud], 1)
