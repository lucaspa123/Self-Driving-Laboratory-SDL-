# Driver: motor de corriente continua con puente H (bomba peristáltica, agitador).
#
# Configuración que manda la PC:
#   pin_a   GPIO del PWM "hacia adelante"
#   pin_b   GPIO del PWM "hacia atrás" (None si el motor gira en un solo sentido)
#   max_ms  marcha continua máxima (se apaga solo)

import time
from machine import Pin, PWM


class Driver:
    def __init__(self, cfg, sistema):
        self.a = PWM(Pin(cfg["pin_a"]), freq=1000)
        self.a.duty_u16(0)
        self.b = None
        if cfg.get("pin_b") is not None:
            self.b = PWM(Pin(cfg["pin_b"]), freq=1000)
            self.b.duty_u16(0)
        self.max_ms = int(cfg.get("max_ms", 180000))
        self.limite = None

    def _girar(self, potencia, sentido):
        ciclo = int(min(100.0, max(0.0, float(potencia))) * 65535 / 100)
        if sentido >= 0:
            if self.b is not None:
                self.b.duty_u16(0)
            self.a.duty_u16(ciclo)
        else:
            if self.b is None:
                raise ValueError("este motor gira en un solo sentido")
            self.a.duty_u16(0)
            self.b.duty_u16(ciclo)

    def accion(self, a, p):
        if a == "parar":
            self.seguro()
            return {}
        if a == "girar":
            potencia = p.get("potencia", 0)
            sentido = int(p.get("sentido", 1))
            if "ms" in p:
                ms = int(p["ms"])
                if ms <= 0 or ms > self.max_ms:
                    raise ValueError("tiempo de marcha fuera del limite")
                return self._girar_por(potencia, sentido, ms)
            self._girar(potencia, sentido)                 # queda girando...
            self.limite = time.ticks_add(time.ticks_ms(), self.max_ms)   # ...hasta este límite
            return {}
        raise ValueError("accion desconocida: " + str(a))

    def _girar_por(self, potencia, sentido, ms):
        fin = time.ticks_add(time.ticks_ms(), ms)
        self._girar(potencia, sentido)
        try:
            while time.ticks_diff(fin, time.ticks_ms()) > 0:
                yield
        finally:
            self.seguro()                # se apaga SIEMPRE, también ante una parada
        return {}

    def medir(self, magnitud):
        raise ValueError("este modulo no mide")

    def tick(self, ahora):
        if self.limite is not None and time.ticks_diff(ahora, self.limite) >= 0:
            self.seguro()
            return "motor apagado por marcha maxima"
        return None

    def seguro(self):
        self.a.duty_u16(0)
        if self.b is not None:
            self.b.duty_u16(0)
        self.limite = None
