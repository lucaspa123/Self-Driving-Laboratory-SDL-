"""Sensor de pH analógico con lectura de temperatura.

Pensado para las placas amplificadoras de sonda de pH con salida de tensión
(tipo PH-4502C): la placa entrega una tensión que cambia en línea recta con el
pH. El ESP32 mide esa tensión (en milivoltios) y este módulo la convierte a pH
con la calibración de dos buffers.

IMPORTANTE (cableado): la entrada del ESP32-S2 mide bien hasta unos 2,5 V. Si
la placa entrega más (las de 5 V llegan a ~4 V), hay que poner un divisor de
tensión entre la placa y el pin. La calibración con buffers absorbe el divisor.

La temperatura puede venir de la salida analógica de la placa o de una sonda
DS18B20; se elige en la configuración. No se corrige el pH por temperatura.
"""
from __future__ import annotations

from .base import ErrorModulo, Modulo

TEMPERATURAS = ["ninguna", "ds18b20", "analogica"]


class SensorPH(Modulo):
    TIPO = "ph"
    DRIVER = "sensor_ph"
    NOMBRE = "Sensor de pH (con temperatura)"
    DESCRIPCION = "Mide el pH del líquido con una sonda y su placa amplificadora; opcionalmente la temperatura."
    CONFIG = {
        "mv_ph7": {"etiqueta": "Señal a pH 7 (calibración)", "valor": 1667.0, "unidad": "mV"},
        "mv_por_ph": {"etiqueta": "Cambio de señal por unidad de pH (calibración)", "valor": -118.0, "unidad": "mV"},
        "calibrada": {"etiqueta": "Calibrada", "valor": False},
        "temperatura": {"etiqueta": "Lectura de temperatura", "valor": "ninguna", "opciones": TEMPERATURAS},
        "correccion_temperatura": {"etiqueta": "Corrección de temperatura", "valor": 0.0, "unidad": "°C"},
        "pin_ph": {"etiqueta": "Pin de la señal de pH (GPIO 1 a 10)", "valor": 1, "avanzado": True},
        "pin_temperatura": {"etiqueta": "Pin de la temperatura (GPIO)", "valor": 2, "avanzado": True},
        "temp_mv_0c": {"etiqueta": "Temperatura analógica: señal a 0 °C", "valor": 0.0, "unidad": "mV",
                       "avanzado": True},
        "temp_mv_por_grado": {"etiqueta": "Temperatura analógica: señal por grado", "valor": 10.0, "unidad": "mV/°C",
                              "avanzado": True},
        "muestras": {"etiqueta": "Lecturas promediadas", "valor": 40, "avanzado": True},
    }
    CALIBRACION = {
        "texto": ("Calibración con dos soluciones buffer. Enjuague la sonda, sumérjala en el PRIMER buffer, "
                  "espere a que la lectura se estabilice (1 minuto), escriba el pH del buffer y pulse Ejecutar."),
        "antes": [{"clave": "ph_a", "etiqueta": "pH del primer buffer", "unidad": "", "valor": 7.0,
                   "min": 0.0, "max": 14.0}],
        "texto_despues": ("Primer buffer leído. Ahora enjuague la sonda, sumérjala en el SEGUNDO buffer, espere "
                          "1 minuto, escriba su pH y guarde."),
        "despues": [{"clave": "ph_b", "etiqueta": "pH del segundo buffer", "unidad": "", "valor": 4.0,
                     "min": 0.0, "max": 14.0}],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._primer_buffer: tuple[float, float] | None = None       # (pH, mV)

    # --- qué ofrece -----------------------------------------------------
    def mediciones(self) -> dict:
        m = {"ph": {"etiqueta": "pH", "unidad": ""}}
        if self.config.get("temperatura") in ("ds18b20", "analogica"):
            m["temperatura"] = {"etiqueta": "Temperatura", "unidad": "°C"}
        return m

    def config_firmware(self) -> dict:
        c = self.config
        tipo = c.get("temperatura") if c.get("temperatura") in ("ds18b20", "analogica") else None
        return {"pin": c["pin_ph"], "muestras": int(c["muestras"]), "temp": tipo,
                "pin_temp": c["pin_temperatura"] if tipo else None}

    def avisos(self) -> list[str]:
        if not self.config.get("calibrada"):
            return [f"{self.etiqueta} no está calibrado con buffers: el pH medido no es confiable."]
        return []

    # --- qué hace -------------------------------------------------------
    def _mv(self) -> float:
        mv = float(self.enlace.medir(self.id, "ph_mv"))
        if getattr(self.enlace, "simulado", False):
            # En simulación no hay sonda: se inventa una señal coherente con la calibración actual.
            ph = float(getattr(self.enlace, "ph_simulado", 7.0))
            mv = self.config["mv_ph7"] + (ph - 7.0) * self.config["mv_por_ph"] + (mv - 0.5) * 2.0
        return mv

    def _ph(self, mv: float) -> float:
        return 7.0 + (mv - float(self.config["mv_ph7"])) / float(self.config["mv_por_ph"])

    def autotest(self) -> tuple[bool, str]:
        mv = self._mv()
        if mv < 50 or mv > 2600:
            return False, (f"La señal de pH es {mv:.0f} mV, fuera de lo que el ESP32 puede medir (50 a 2500 mV). "
                           f"Revise el cableado y el divisor de tensión.")
        aviso = "" if self.config.get("calibrada") else " Falta calibrar con buffers."
        return True, f"Responde. pH actual: {self._ph(mv):.2f} (señal {mv:.0f} mV).{aviso}"

    def medir(self, magnitud: str) -> float:
        if magnitud == "ph":
            valor = round(self._ph(self._mv()), 2)
            self.estado["ultimo_ph"] = valor
            return valor
        if magnitud == "temperatura" and magnitud in self.mediciones():
            c = self.config
            crudo = float(self.enlace.medir(self.id, "temperatura"))
            if c["temperatura"] == "analogica" and not getattr(self.enlace, "simulado", False):
                crudo = (crudo - float(c["temp_mv_0c"])) / float(c["temp_mv_por_grado"])
            valor = round(crudo + float(c["correccion_temperatura"]), 1)
            self.estado["ultima_temperatura"] = valor
            return valor
        raise ErrorModulo(f"{self.etiqueta} no mide '{magnitud}'.")

    def resumen(self) -> str:
        partes = []
        if self.estado.get("ultimo_ph") is not None:
            partes.append(f"Último pH {self.estado['ultimo_ph']:.2f}")
        if self.estado.get("ultima_temperatura") is not None and "temperatura" in self.mediciones():
            partes.append(f"{self.estado['ultima_temperatura']:.1f} °C")
        if self.config.get("calibrada"):
            partes.append(f"{abs(self.config['mv_por_ph']):.0f} mV por unidad de pH")
        return " · ".join(partes)

    # --- calibración con dos buffers ----------------------------------------
    def calibrar_ejecutar(self, datos: dict) -> None:
        ph_a = float(datos["ph_a"])
        if getattr(self.enlace, "simulado", False):
            self.enlace.ph_simulado = ph_a
        self._primer_buffer = (ph_a, self._mv())

    def calibrar_aplicar(self, datos: dict) -> str:
        if self._primer_buffer is None:
            raise ErrorModulo("Primero hay que leer el primer buffer.")
        ph_a, mv_a = self._primer_buffer
        ph_b = float(datos["ph_b"])
        if abs(ph_b - ph_a) < 1.0:
            raise ErrorModulo("Los dos buffers deben diferir en al menos 1 unidad de pH (por ejemplo 7 y 4).")
        if getattr(self.enlace, "simulado", False):
            self.enlace.ph_simulado = ph_b
        mv_b = self._mv()
        pendiente = (mv_b - mv_a) / (ph_b - ph_a)
        if abs(pendiente) < 10.0:
            raise ErrorModulo(f"La señal casi no cambió entre los dos buffers ({mv_a:.0f} y {mv_b:.0f} mV). "
                              f"Revise que la sonda esté conectada y sumergida, y repita.")
        c = self.config
        c["mv_por_ph"] = round(pendiente, 3)
        c["mv_ph7"] = round(mv_a + (7.0 - ph_a) * pendiente, 2)
        c["calibrada"] = True
        self._primer_buffer = None
        return (f"Calibración guardada: {abs(pendiente):.1f} mV por unidad de pH; señal a pH 7: {c['mv_ph7']:.0f} mV "
                f"(buffer {ph_a:g}: {mv_a:.0f} mV, buffer {ph_b:g}: {mv_b:.0f} mV).")

    def estado_seguro(self) -> None:
        pass                                   # un sensor no tiene nada que apagar
