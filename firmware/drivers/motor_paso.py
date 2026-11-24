# Driver: motor paso a paso (NEMA17 + DRV8825) que gira en UN solo sentido (agitador).
#
# Configuración que manda la PC:
#   pin_step  GPIO de STEP. Los pulsos los genera el PWM por hardware: no ocupan al procesador,
#             así que se puede llegar a miles de pasos por segundo sin trabar el USB.
#   pin_en    GPIO de ENABLE del DRV8825 (0 = motor con corriente, 1 = libre). El motor solo
#             tiene corriente mientras gira.
#   hz_max    pasos por segundo máximos que acepta
#   max_ms    marcha continua máxima (se apaga solo)
#
# No hay pin DIR: en la plaqueta ese pin queda unido a GND (o a 3,3 V) y fija el sentido.
#
# Acciones:
#   girar  {hz, accel, ms?}   gira a 'hz' pasos/s acelerando 'accel' pasos/s por segundo.
#                             Con 'ms' se apaga solo; sin 'ms' queda girando hasta 'parar'.
#   parar                     se apaga ya (sin rampa de frenado: es lo más seguro).

import time
from machine import Pin, PWM

ARRANQUE_HZ = 200        # a esta velocidad un NEMA17 arranca sin perder pasos
PASO_MS = 20             # cada cuánto se actualiza la rampa


class Driver:
    def __init__(self, cfg, sistema):
        self.pin_step = int(cfg["pin_step"])
        Pin(self.pin_step, Pin.OUT, value=0)
        self.en = Pin(cfg["pin_en"], Pin.OUT, value=1) if cfg.get("pin_en") is not None else None
        self.hz_max = int(cfg.get("hz_max", 8000))
        self.max_ms = int(cfg.get("max_ms", 300000))
        self.pwm = None
        self.hz = 0.0            # velocidad actual
        self.obj = 0.0           # velocidad pedida
        self.accel = 1000.0
        self.t = 0
        self.limite = None

    def _fuerza(self, activar):
        if self.en is not None:
            self.en.value(0 if activar else 1)

    def _aplicar(self):
        self.pwm.freq(max(1, int(self.hz)))
        self.pwm.duty_u16(32768)                       # 50 %: pulsos de ancho parejo

    def _arrancar(self, hz, accel):
        self.obj = hz
        self.accel = accel
        self.t = time.ticks_ms()
        if self.pwm is None:
            self._fuerza(True)
            self.hz = min(float(ARRANQUE_HZ), hz)
            self.pwm = PWM(Pin(self.pin_step), freq=max(1, int(self.hz)))
            self._aplicar()

    def accion(self, a, p):
        if a == "parar":
            self.seguro()
            return {}
        if a == "girar":
            hz = float(p.get("hz", 0))
            accel = float(p.get("accel", 1000))
            if hz < 1 or hz > self.hz_max:
                raise ValueError("velocidad fuera del limite")
            if accel < 1:
                raise ValueError("aceleracion invalida")
            if "ms" in p:
                ms = int(p["ms"])
                if ms <= 0 or ms > self.max_ms:
                    raise ValueError("tiempo de marcha fuera del limite")
                return self._girar_por(hz, accel, ms)
            self._arrancar(hz, accel)                  # queda girando...
            self.limite = time.ticks_add(time.ticks_ms(), self.max_ms)   # ...hasta este límite
            return {}
        raise ValueError("accion desconocida: " + str(a))

    def _girar_por(self, hz, accel, ms):
        fin = time.ticks_add(time.ticks_ms(), ms)
        self._arrancar(hz, accel)
        try:
            while time.ticks_diff(fin, time.ticks_ms()) > 0:
                yield
        finally:
            self.seguro()                # se apaga SIEMPRE, también ante una parada
        return {}

    def medir(self, magnitud):
        raise ValueError("este modulo no mide")

    def tick(self, ahora):
        if self.pwm is None:
            return None
        if self.limite is not None and time.ticks_diff(ahora, self.limite) >= 0:
            self.seguro()
            return "motor apagado por marcha maxima"
        dt = time.ticks_diff(ahora, self.t)
        if dt >= PASO_MS and self.hz != self.obj:
            self.t = ahora
            cambio = self.accel * dt / 1000.0
            if self.hz < self.obj:
                self.hz = min(self.obj, self.hz + cambio)
            else:
                self.hz = max(self.obj, self.hz - cambio)
            self._aplicar()
        return None

    def seguro(self):
        if self.pwm is not None:
            try:
                self.pwm.deinit()
            except Exception:
                pass
            self.pwm = None
        Pin(self.pin_step, Pin.OUT, value=0)
        self._fuerza(False)
        self.hz = 0.0
        self.obj = 0.0
        self.limite = None
