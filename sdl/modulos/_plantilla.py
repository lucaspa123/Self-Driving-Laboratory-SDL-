"""PLANTILLA para agregar un módulo nuevo (sensor_ph.py es un ejemplo completo).

Pasos:
1. Copiar este archivo con otro nombre (ej. sensor_ph.py) en esta misma carpeta.
   Los archivos que empiezan con "_" se ignoran; el resto se carga solo.
2. Completar la clase: TIPO, CONFIG, acciones()/MEDICIONES, ejecutar()/medir().
3. Si usa el ESP32: crear firmware/drivers/<DRIVER>.py (ver firmware/drivers/_plantilla.py)
   y copiarlo al ESP32.
4. En la pantalla Módulos: "Agregar módulo", elegir el tipo nuevo y activarlo.

Desde ese momento sus acciones y mediciones aparecen en el asistente de
experimentos: se pueden usar como variable a optimizar, como paso del
protocolo o como objetivo medido. No hay que tocar el resto del programa.
"""
from __future__ import annotations

from .base import ErrorModulo, Modulo


class MiModulo(Modulo):
    TIPO = "mi_modulo"                 # nombre corto y único
    DRIVER = "mi_driver"               # archivo firmware/drivers/mi_driver.py
    NOMBRE = "Mi módulo"
    DESCRIPCION = "Qué hace, en una línea."
    USA_ESP32 = True
    CONFIG = {
        "pin": {"etiqueta": "Pin (GPIO)", "valor": 1, "avanzado": True},
        "pendiente": {"etiqueta": "Pendiente de calibración", "valor": 1.0},
    }
    MEDICIONES = {
        "magnitud": {"etiqueta": "Magnitud medida", "unidad": "u"},
    }

    def acciones(self) -> dict:
        # Un sensor puro puede no tener acciones: devolver {}.
        return {}

    def config_firmware(self) -> dict:
        # Lo que el driver del ESP32 recibe en su __init__.
        return {"pin": self.config["pin"]}

    def autotest(self) -> tuple[bool, str]:
        valor = self.medir("magnitud")
        return True, f"Responde. Lectura actual: {valor:g}."

    def medir(self, magnitud: str) -> float:
        if magnitud != "magnitud":
            raise ErrorModulo(f"{self.etiqueta} no mide '{magnitud}'.")
        crudo = float(self.enlace.medir(self.id, "magnitud"))
        return round(crudo * float(self.config["pendiente"]), 3)

    def estado_seguro(self) -> None:
        # Un sensor no tiene nada que apagar. Un actuador SIEMPRE debe implementarlo.
        pass
