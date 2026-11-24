# Driver: servo que abre (del todo o en parte) y cierra el robinete de una bureta.
#
# Las órdenes "abrir" y "abrir_por" aceptan un "angulo" intermedio para regular el caudal.
#
# Configuración que manda la PC:
#   pin      GPIO de la señal del servo
#   cerrado  ángulo con el robinete cerrado
#   abierto  ángulo con el robinete abierto del todo
#   max_ms   tiempo máximo que puede quedar abierto (se cierra solo)

import time
from machine import Pin, PWM


class Driver:
    def __init__(self, cfg, sistema):
        self.cerrado = cfg.get("cerrado", 0)
        self.abierto = cfg.get("abierto", 90)
        self.max_ms = int(cfg.get("max_ms", 60000))
        self.pwm = PWM(Pin(cfg["pin"]), freq=50)
        self.limite = None               # instante en que debe cerrarse solo
        self._angulo(self.cerrado)       # al arrancar: cerrado

    def _angulo(self, grados):
        # Servo estándar: pulso de 0,5 ms (0°) a 2,5 ms (180°), cada 20 ms.
        micros = 500 + int(2000 * grados / 180)
        self.pwm.duty_u16(micros * 65535 // 20000)

    def _angulo_pedido(self, p):
        # La PC puede pedir una apertura parcial ("angulo"). Sin ese dato: abierto del todo.
        # Nunca se acepta un ángulo fuera del tramo cerrado-abierto.
        if p.get("angulo") is None:
            return self.abierto
        angulo = float(p["angulo"])
        if angulo < min(self.cerrado, self.abierto) or angulo > max(self.cerrado, self.abierto):
            raise ValueError("angulo fuera del recorrido del robinete")
        return angulo

    def accion(self, a, p):
        if a == "info":                  # le dice a la PC que este driver sabe abrir en parte
            return {"parcial": True}
        if a == "cerrar":
            self.seguro()
            return {}
        if a == "abrir":                 # apertura manual: igual se cierra sola al llegar a max_ms
            self._angulo(self._angulo_pedido(p))
            self.limite = time.ticks_add(time.ticks_ms(), self.max_ms)
            return {}
        if a == "abrir_por":
            ms = int(p["ms"])
            if ms <= 0 or ms > self.max_ms:
                raise ValueError("tiempo de apertura fuera del limite")
            return self._abrir_por(ms, self._angulo_pedido(p))
        raise ValueError("accion desconocida: " + str(a))

    def _abrir_por(self, ms, angulo):
        fin = time.ticks_add(time.ticks_ms(), ms)
        self._angulo(angulo)
        try:
            while time.ticks_diff(fin, time.ticks_ms()) > 0:
                yield                    # devuelve el control al bucle principal
        finally:
            self._angulo(self.cerrado)   # se cierra SIEMPRE, también ante una parada
        fin = time.ticks_add(time.ticks_ms(), 400)      # tiempo para que el servo llegue
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            yield
        return {}

    def medir(self, magnitud):
        raise ValueError("este modulo no mide")

    def tick(self, ahora):
        if self.limite is not None and time.ticks_diff(ahora, self.limite) >= 0:
            self.seguro()
            return "robinete cerrado por tiempo maximo"
        return None

    def seguro(self):
        self._angulo(self.cerrado)
        self.limite = None
