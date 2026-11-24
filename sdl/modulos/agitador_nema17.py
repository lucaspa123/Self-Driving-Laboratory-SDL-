"""Agitador con motor paso a paso NEMA17 (driver DRV8825). Gira en un solo sentido.

Hace lo mismo que el agitador de motor de corriente continua (acciones "agitar",
"encender" y "apagar", parámetros "velocidad" y "segundos"), pero la velocidad se
da en vueltas por minuto (rpm) y no en porcentaje.

Conexión: STEP y ENABLE van al ESP32. El pin DIR del DRV8825 NO se conecta al
ESP32: se une a GND (o a 3,3 V) y fija el sentido de giro para siempre. Si la
hélice gira al revés de lo que se quiere, se pasa ese cable de GND a 3,3 V.
"""
from __future__ import annotations

from .base import ErrorModulo, Modulo

MICROPASOS = (1, 2, 4, 8, 16, 32)
HZ_MAXIMO = 20000          # por encima de esto el NEMA17 pierde casi todo su par


class AgitadorNema17(Modulo):
    TIPO = "agitador_nema17"
    DRIVER = "motor_paso"
    NOMBRE = "Agitador (NEMA17)"
    DESCRIPCION = ("Motor paso a paso NEMA17 con DRV8825 que gira en un solo sentido. "
                   "La velocidad se da en rpm.")
    CONFIG = {
        "rpm_min": {"etiqueta": "Velocidad mínima útil", "valor": 30, "unidad": "rpm"},
        "rpm_max": {"etiqueta": "Velocidad máxima permitida", "valor": 300, "unidad": "rpm"},
        "tiempo_max_s": {"etiqueta": "Marcha continua máxima", "valor": 300, "unidad": "s", "avanzado": True},
        "pasos_vuelta": {"etiqueta": "Pasos por vuelta del motor", "valor": 200, "avanzado": True},
        "micropasos": {"etiqueta": "Micropasos del DRV8825 (1, 2, 4, 8, 16 o 32)", "valor": 16,
                       "avanzado": True},
        "aceleracion_rpm_s": {"etiqueta": "Aceleración al arrancar", "valor": 150, "unidad": "rpm/s",
                              "avanzado": True},
        "pin_step": {"etiqueta": "Pin STEP (GPIO)", "valor": 17, "avanzado": True},
        "pin_habilitar": {"etiqueta": "Pin ENABLE (GPIO)", "valor": 18, "avanzado": True},
    }

    # --- conversiones ----------------------------------------------------
    def _micropasos(self) -> int:
        m = self.config["micropasos"]
        if m not in MICROPASOS:
            raise ErrorModulo(f"{self.etiqueta}: los micropasos deben ser 1, 2, 4, 8, 16 o 32.")
        return int(m)

    def _pasos_por_rpm(self) -> float:
        """Pasos por segundo que corresponden a 1 rpm."""
        return float(self.config["pasos_vuelta"]) * self._micropasos() / 60.0

    def hz(self, rpm: float) -> float:
        return float(rpm) * self._pasos_por_rpm()

    # --- qué ofrece ------------------------------------------------------
    def acciones(self) -> dict:
        c = self.config
        vel = {"etiqueta": "Velocidad", "unidad": "rpm", "min": c["rpm_min"],
               "max": c["rpm_max"], "paso": 5, "optimizable": True}
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
        c = self.config
        self._micropasos()
        hz_max = int(self.hz(c["rpm_max"])) + 1
        return {"pin_step": c["pin_step"], "pin_en": c["pin_habilitar"], "hz_max": hz_max,
                "max_ms": int(float(c["tiempo_max_s"]) * 1000)}

    def avisos(self) -> list[str]:
        c = self.config
        avisos = []
        if self.hz(c["rpm_max"]) > HZ_MAXIMO:
            rpm = HZ_MAXIMO / self._pasos_por_rpm()
            avisos.append(f"{self.etiqueta}: {c['rpm_max']:g} rpm piden más de {HZ_MAXIMO} pasos por "
                          f"segundo, más de lo que el motor puede seguir. Baje la velocidad máxima a "
                          f"unas {rpm:.0f} rpm o use menos micropasos.")
        if float(c["rpm_min"]) >= float(c["rpm_max"]):
            avisos.append(f"{self.etiqueta}: la velocidad mínima debe ser menor que la máxima.")
        return avisos

    def resumen(self) -> str:
        v = self.estado.get("velocidad", 0)
        return f"Girando a {v:g} rpm" if v else "Apagado"

    def duracion(self, accion: str, p: dict) -> float:
        return float(p.get("segundos", 0)) + 1.0

    def autotest(self) -> tuple[bool, str]:
        self.enlace.accion(self.id, "parar")
        return True, "Responde. Motor detenido y sin corriente."

    # --- acciones --------------------------------------------------------
    def _girar(self, velocidad: float, **extra) -> None:
        c = self.config
        hz = self.hz(velocidad)
        if hz > HZ_MAXIMO:
            raise ErrorModulo(f"{self.etiqueta}: {velocidad:g} rpm piden {hz:.0f} pasos por segundo; "
                              f"el máximo es {HZ_MAXIMO}.")
        acel = max(50.0, float(c["aceleracion_rpm_s"]) * self._pasos_por_rpm())
        self.enlace.accion(self.id, "girar", hz=round(hz, 1), accel=round(acel, 1), **extra)

    def ejecutar(self, accion: str, p: dict) -> dict:
        self.comprobar(accion, p)
        if accion == "apagar":
            self.enlace.accion(self.id, "parar")
            self.estado["velocidad"] = 0
        elif accion == "encender":
            # Sin 'ms': queda girando. El firmware lo corta solo al llegar a la marcha máxima.
            self._girar(float(p["velocidad"]))
            self.estado["velocidad"] = float(p["velocidad"])
        elif accion == "agitar":
            segundos = float(p["segundos"])
            self.estado["velocidad"] = float(p["velocidad"])
            try:
                self._girar(float(p["velocidad"]), ms=int(segundos * 1000), espera=segundos + 10)
            finally:
                self.estado["velocidad"] = 0
        return {}

    def estado_seguro(self) -> None:
        self.estado["velocidad"] = 0
        self.enlace.accion(self.id, "parar")
