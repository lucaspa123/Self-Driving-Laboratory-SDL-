"""Módulos con motor de corriente continua: bomba peristáltica y agitador.

Los dos usan el mismo driver del firmware (motor_dc): un puente H con PWM.
"""
from __future__ import annotations

from .base import ErrorModulo, Modulo


class BombaPeristaltica(Modulo):
    TIPO = "bomba"
    DRIVER = "motor_dc"
    NOMBRE = "Bomba peristáltica"
    DESCRIPCION = "Bombea un volumen de líquido. El volumen sale de caudal × tiempo."
    CONFIG = {
        "caudal_ml_s": {"etiqueta": "Caudal (calibración)", "valor": 1.0, "unidad": "mL/s"},
        "potencia": {"etiqueta": "Potencia de trabajo", "valor": 60, "unidad": "%"},
        "volumen_min_ml": {"etiqueta": "Volumen mínimo", "valor": 0.5, "unidad": "mL"},
        "volumen_max_ml": {"etiqueta": "Volumen máximo por orden", "valor": 100.0, "unidad": "mL"},
        "resolucion_ml": {"etiqueta": "Resolución", "valor": 0.5, "unidad": "mL"},
        "calibrada": {"etiqueta": "Calibrada", "valor": False},
        "pin_adelante": {"etiqueta": "Pin PWM hacia adelante (GPIO)", "valor": 33, "avanzado": True},
        "pin_atras": {"etiqueta": "Pin PWM hacia atrás (GPIO)", "valor": 34, "avanzado": True},
        "tiempo_max_s": {"etiqueta": "Marcha continua máxima", "valor": 180, "unidad": "s", "avanzado": True},
    }
    CALIBRACION = {
        "texto": ("Ponga la manguera de entrada en agua y la de salida en una probeta. El programa "
                  "bombeará el tiempo indicado; después escriba el volumen recogido."),
        "antes": [{"clave": "segundos", "etiqueta": "Tiempo de bombeo", "unidad": "s", "valor": 10.0}],
        "despues": [{"clave": "volumen", "etiqueta": "Volumen recogido", "unidad": "mL", "valor": 0.0}],
    }

    def acciones(self) -> dict:
        c = self.config
        vol = {"etiqueta": "Volumen", "unidad": "mL", "min": c["volumen_min_ml"],
               "max": c["volumen_max_ml"], "paso": c["resolucion_ml"]}
        return {
            "bombear": {"etiqueta": "Bombear un volumen", "en_protocolo": True,
                        "agrega_volumen": "volumen", "usa_reactivo": True,
                        "parametros": {"volumen": {**vol, "optimizable": True}}},
            "retroceder": {"etiqueta": "Bombear en reversa (vaciar la manguera)", "en_protocolo": True,
                           "parametros": {"volumen": dict(vol)}},
            "detener": {"etiqueta": "Detener", "parametros": {}},
        }

    def config_firmware(self) -> dict:
        c = self.config
        return {"pin_a": c["pin_adelante"], "pin_b": c["pin_atras"],
                "max_ms": int(float(c["tiempo_max_s"]) * 1000)}

    def avisos(self) -> list[str]:
        return [] if self.config.get("calibrada") else [
            f"{self.etiqueta} no está calibrada: los volúmenes pueden no ser exactos."]

    def resumen(self) -> str:
        return f"Caudal {self.config['caudal_ml_s']:g} mL/s al {self.config['potencia']:g} %"

    def _segundos(self, volumen: float) -> float:
        return float(volumen) / float(self.config["caudal_ml_s"])

    def duracion(self, accion: str, p: dict) -> float:
        return self._segundos(p.get("volumen", 0)) + 1.0 if "volumen" in p else 1.0

    def autotest(self) -> tuple[bool, str]:
        self.enlace.accion(self.id, "parar")
        return True, "Responde. Motor detenido."

    def ejecutar(self, accion: str, p: dict) -> dict:
        self.comprobar(accion, p)
        if accion == "detener":
            self.enlace.accion(self.id, "parar")
            return {}
        segundos = self._segundos(p["volumen"])
        if segundos > float(self.config["tiempo_max_s"]):
            raise ErrorModulo(f"{self.etiqueta}: ese volumen pide {segundos:.0f} s de marcha y el máximo "
                              f"es {self.config['tiempo_max_s']} s.")
        self.enlace.accion(self.id, "girar", potencia=float(self.config["potencia"]),
                           sentido=1 if accion == "bombear" else -1,
                           ms=int(segundos * 1000), espera=segundos + 10)
        return {"volumen": float(p["volumen"]), "segundos": round(segundos, 2)}

    def estado_seguro(self) -> None:
        self.enlace.accion(self.id, "parar")

    def calibrar_ejecutar(self, datos: dict) -> None:
        segundos = float(datos["segundos"])
        if not 1 <= segundos <= float(self.config["tiempo_max_s"]):
            raise ErrorModulo("El tiempo debe estar entre 1 s y la marcha máxima.")
        self.enlace.accion(self.id, "girar", potencia=float(self.config["potencia"]), sentido=1,
                           ms=int(segundos * 1000), espera=segundos + 10)

    def calibrar_aplicar(self, datos: dict) -> str:
        volumen, segundos = float(datos["volumen"]), float(datos["segundos"])
        if volumen <= 0:
            raise ErrorModulo("El volumen recogido debe ser mayor que cero.")
        self.config["caudal_ml_s"] = round(volumen / segundos, 4)
        self.config["calibrada"] = True
        return f"Calibración guardada: {self.config['caudal_ml_s']:g} mL/s."


class Agitador(Modulo):
    TIPO = "agitador"
    DRIVER = "motor_dc"
    NOMBRE = "Agitador"
    DESCRIPCION = "Motor de mezclado de un solo sentido con velocidad regulable."
    CONFIG = {
        "velocidad_min": {"etiqueta": "Velocidad mínima útil", "valor": 20, "unidad": "%"},
        "velocidad_max": {"etiqueta": "Velocidad máxima permitida", "valor": 80, "unidad": "%"},
        "pin_pwm": {"etiqueta": "Pin PWM (GPIO)", "valor": 16, "avanzado": True},
        "tiempo_max_s": {"etiqueta": "Marcha continua máxima", "valor": 180, "unidad": "s", "avanzado": True},
    }

    def acciones(self) -> dict:
        c = self.config
        vel = {"etiqueta": "Velocidad", "unidad": "%", "min": c["velocidad_min"],
               "max": c["velocidad_max"], "paso": 1, "optimizable": True}
        return {
            "agitar": {"etiqueta": "Agitar durante un tiempo", "en_protocolo": True,
                       "parametros": {"velocidad": dict(vel),
                                      "segundos": {"etiqueta": "Duración", "unidad": "s", "min": 1,
                                                   "max": c["tiempo_max_s"], "paso": 1,
                                                   "optimizable": True}}},
            "encender": {"etiqueta": "Encender (queda girando)", "en_protocolo": True,
                         "parametros": {"velocidad": dict(vel)}},
            "apagar": {"etiqueta": "Apagar", "en_protocolo": True, "parametros": {}},
        }

    def config_firmware(self) -> dict:
        return {"pin_a": self.config["pin_pwm"], "pin_b": None,
                "max_ms": int(float(self.config["tiempo_max_s"]) * 1000)}

    def resumen(self) -> str:
        v = self.estado.get("velocidad", 0)
        return f"Girando al {v:g} %" if v else "Apagado"

    def duracion(self, accion: str, p: dict) -> float:
        return float(p.get("segundos", 0)) + 1.0

    def autotest(self) -> tuple[bool, str]:
        self.enlace.accion(self.id, "parar")
        return True, "Responde. Motor detenido."

    def ejecutar(self, accion: str, p: dict) -> dict:
        self.comprobar(accion, p)
        if accion == "apagar":
            self.enlace.accion(self.id, "parar")
            self.estado["velocidad"] = 0
        elif accion == "encender":
            # Sin 'ms': queda girando. El firmware lo corta solo al llegar a la marcha máxima.
            self.enlace.accion(self.id, "girar", potencia=float(p["velocidad"]), sentido=1)
            self.estado["velocidad"] = float(p["velocidad"])
        elif accion == "agitar":
            segundos = float(p["segundos"])
            self.estado["velocidad"] = float(p["velocidad"])
            try:
                self.enlace.accion(self.id, "girar", potencia=float(p["velocidad"]), sentido=1,
                                   ms=int(segundos * 1000), espera=segundos + 10)
            finally:
                self.estado["velocidad"] = 0
        return {}

    def estado_seguro(self) -> None:
        self.estado["velocidad"] = 0
        self.enlace.accion(self.id, "parar")
