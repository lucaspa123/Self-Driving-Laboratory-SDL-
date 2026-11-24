# Driver: brazo robótico. 4 motores paso a paso con DRV8825 + servo de la pinza.
#
# Configuración que manda la PC:
#   step     lista de GPIO de STEP (uno por articulación)
#   dir      lista de GPIO de DIR
#   en       GPIO de ENABLE común (en el DRV8825, 0 = motores con fuerza, 1 = libres)
#   pinza    GPIO del servo de la pinza
#   limites  recorrido permitido de cada articulación, en pasos: [[min, max], ...]
#   vmax     pasos por segundo máximos
#
# Mueve UNA articulación por vez. El ESP32 lleva la cuenta de pasos; como no
# hay finales de carrera, hay que "fijar el origen" a mano después de cada
# encendido (lo hace el usuario desde la pantalla Módulos).

import time
from machine import Pin, PWM

VEL_ARRANQUE = 200       # pasos/s al arrancar y al frenar
RAMPA = 300              # pasos que dura la aceleración (y la frenada)


class Driver:
    def __init__(self, cfg, sistema):
        self.step = [Pin(n, Pin.OUT, value=0) for n in cfg["step"]]
        self.dir = [Pin(n, Pin.OUT, value=0) for n in cfg["dir"]]
        self.en = Pin(cfg["en"], Pin.OUT, value=1) if cfg.get("en") is not None else None
        self.limites = cfg.get("limites")
        self.vmax = int(cfg.get("vmax", 2000))
        self.pasos = [0] * len(self.step)
        self.ref = False                 # ¿se fijó el origen?
        self.pinza = None                # el servo no recibe señal hasta la primera orden (no se mueve solo)
        self.pin_pinza = cfg.get("pinza")

    def _fuerza(self, activar):
        if self.en is not None:
            self.en.value(0 if activar else 1)

    def accion(self, a, p):
        if a == "estado":
            return {"ref": self.ref, "pasos": self.pasos}
        if a == "fijar_origen":
            self.pasos = [int(x) for x in p["pasos"]]
            self.ref = True
            self._fuerza(True)           # desde acá los motores sostienen el brazo
            return {}
        if a == "liberar":
            self._fuerza(False)
            self.ref = False
            return {}
        if a == "detener":
            return {}                    # el brazo queda quieto sosteniendo la carga
        if a == "pinza":
            return self._pinza(float(p["angulo"]))
        if a == "mover":
            eje, n, vel = int(p["eje"]), int(p["pasos"]), int(p.get("vel", 400))
            if not self.ref:
                raise ValueError("el brazo no tiene origen fijado")
            if eje < 0 or eje >= len(self.step):
                raise ValueError("articulacion inexistente")
            if vel < 1 or vel > self.vmax:
                raise ValueError("velocidad fuera del limite")
            if self.limites:
                destino = self.pasos[eje] + n
                if destino < self.limites[eje][0] or destino > self.limites[eje][1]:
                    raise ValueError("movimiento fuera del recorrido permitido")
            return self._mover(eje, n, vel)
        raise ValueError("accion desconocida: " + str(a))

    def _pinza(self, grados):
        if self.pin_pinza is None:
            raise ValueError("la pinza no tiene pin configurado")
        if self.pinza is None:
            self.pinza = PWM(Pin(self.pin_pinza), freq=50)
        micros = 500 + int(2000 * grados / 180)
        self.pinza.duty_u16(micros * 65535 // 20000)
        fin = time.ticks_add(time.ticks_ms(), 600)       # tiempo para que el servo llegue
        while time.ticks_diff(fin, time.ticks_ms()) > 0:
            yield
        return {}

    def _mover(self, eje, n, vel):
        self._fuerza(True)
        sentido = 1 if n > 0 else -1
        self.dir[eje].value(1 if n > 0 else 0)
        time.sleep_us(50)
        total = abs(n)
        hechos = 0
        periodo = 1000000 // vel                         # microsegundos entre pasos a velocidad plena
        lento = max(periodo, 1000000 // VEL_ARRANQUE)
        rampa = min(RAMPA, total // 2)
        pin = self.step[eje]
        completo = False
        try:
            while hechos < total:
                # Ráfaga de ~20 ms de pasos y después se devuelve el control (yield)
                # para que el bucle principal lea el USB y vigile la parada.
                fin_rafaga = time.ticks_add(time.ticks_ms(), 20)
                siguiente = time.ticks_us()
                while hechos < total and time.ticks_diff(fin_rafaga, time.ticks_ms()) > 0:
                    if hechos < rampa:                   # acelera
                        espera = lento - (lento - periodo) * hechos // rampa
                    elif total - hechos <= rampa:        # frena
                        espera = lento - (lento - periodo) * (total - hechos) // rampa
                    else:
                        espera = periodo
                    pin.value(1)
                    time.sleep_us(4)                     # el DRV8825 necesita al menos 1,9 µs
                    pin.value(0)
                    hechos += 1
                    self.pasos[eje] += sentido
                    siguiente = time.ticks_add(siguiente, espera)
                    falta = time.ticks_diff(siguiente, time.ticks_us())
                    if falta > 0:
                        time.sleep_us(falta)
                yield
            completo = True
        finally:
            if not completo:
                self.ref = False         # movimiento cortado: la posición ya no es confiable
        return {"pasos": self.pasos[eje]}

    def medir(self, magnitud):
        raise ValueError("este modulo no mide")

    def tick(self, ahora):
        return None

    def seguro(self):
        pass                             # quieto y con fuerza: soltar el brazo sería peor
