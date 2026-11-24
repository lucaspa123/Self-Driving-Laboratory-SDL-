# Driver: servo de ROTACIÓN CONTINUA que abre y cierra el robinete de una bureta.
#
# Un servo continuo (por ejemplo, un MG996R al que se le quitó el tope) NO tiene posición: el ancho del
# pulso es la VELOCIDAD y el SENTIDO. Con 1,5 ms está quieto, con menos gira para un lado y con más
# para el otro. Por eso este driver:
#   - al arrancar NO manda ningún pulso (el servo queda quieto y en silencio);
#   - para ir a un ángulo gira durante un tiempo calculado (grados / velocidad) y se detiene;
#   - lleva la cuenta de en qué posición cree que está el robinete ("a ojo", sumando lo que giró).
#
# Como la posición es una estimación, TRAS UN REINICIO el driver no sabe dónde está el robinete
# hasta que la PC le diga "está cerrado" (acción "referencia"). Mientras tanto se niega a abrir.
#
# Los ángulos que recibe son grados DESDE CERRADO hacia abierto (0 = cerrado, "recorrido" = del todo).
#
# Configuración que manda la PC:
#   pin            GPIO de la señal del servo
#   recorrido      grados entre cerrado y abierto del todo
#   deg_por_s      grados por segundo que gira con "vel_us" (se mide una vez)
#   vel_us         cuánto se aparta el pulso de "neutro_us" al girar (más = más rápido)
#   neutro_us      pulso en que el servo está quieto (1500 por lo general)
#   sentido        1 si el pulso mayor que el neutro ABRE el robinete, -1 si lo cierra
#   factor_cierre  corrige si el servo es más lento (>1) o más rápido (<1) al cerrar que al abrir
#   max_ms         tiempo máximo que puede quedar abierto (se cierra solo)

import time
from machine import Pin, PWM


class Driver:
    def __init__(self, cfg, sistema):
        self.recorrido = float(cfg.get("recorrido", 90))
        self.deg_s = float(cfg.get("deg_por_s", 90))
        self.vel_us = int(cfg.get("vel_us", 150))
        self.neutro_us = int(cfg.get("neutro_us", 1500))
        self.sentido = 1 if int(cfg.get("sentido", 1)) >= 0 else -1
        self.factor = float(cfg.get("factor_cierre", 1.0))
        self.max_ms = int(cfg.get("max_ms", 60000))
        if self.recorrido <= 0 or self.recorrido > 360:
            raise ValueError("recorrido fuera de rango")
        if self.deg_s < 5 or self.deg_s > 1000:
            raise ValueError("deg_por_s fuera de rango")
        if self.vel_us < 30 or self.vel_us > 500:
            raise ValueError("vel_us fuera de rango (30 a 500)")
        if self.neutro_us < 1300 or self.neutro_us > 1700:
            raise ValueError("neutro_us fuera de rango (1300 a 1700)")
        if self.factor < 0.5 or self.factor > 2.0:
            raise ValueError("factor_cierre fuera de rango (0,5 a 2)")
        self.pin = cfg["pin"]
        self.pwm = None                  # se crea solo mientras el servo gira
        self.pos = 0.0                   # grados desde cerrado (estimados)
        self.ref = False                 # ¿se sabe dónde está el robinete?
        self.mov = None                  # (instante de inicio, signo) del giro en curso
        self.activo = False              # hay una secuencia (abrir, dosis, giro) en marcha
        self.limite = None               # instante en que debe cerrarse solo
        Pin(self.pin, Pin.OUT, value=0)  # línea en bajo: sin pulsos, el servo no se mueve

    # --- el servo -----------------------------------------------------------
    def _arrancar(self, signo):
        """Empieza a girar: signo +1 = hacia abierto, -1 = hacia cerrado."""
        if self.pwm is None:
            self.pwm = PWM(Pin(self.pin), freq=50)
        micros = self.neutro_us + self.sentido * signo * self.vel_us
        self.pwm.duty_u16(micros * 65535 // 20000)
        self.mov = (time.ticks_ms(), signo)

    def _frenar(self):
        """Deja de mandar pulsos y anota cuánto giró desde que arrancó."""
        if self.mov is not None:
            inicio, signo = self.mov
            self.mov = None
            segundos = time.ticks_diff(time.ticks_ms(), inicio) / 1000.0
            self.pos += signo * segundos * self.deg_s / (self.factor if signo < 0 else 1.0)
        if self.pwm is not None:
            self.pwm.deinit()
            self.pwm = None
        Pin(self.pin, Pin.OUT, value=0)

    def _ms(self, grados):
        """Milisegundos de giro para recorrer 'grados' (negativo = cerrando)."""
        if grados < 0:
            return int(-grados * 1000 / self.deg_s * self.factor)
        return int(grados * 1000 / self.deg_s)

    def _cerrar_ya(self):
        """Cierra de inmediato (bloquea el tiempo que tarde). Lo usan las paradas."""
        self._frenar()
        self.limite = None
        if not self.ref or self.pos <= 0.01:
            return
        fin = time.ticks_add(time.ticks_ms(), self._ms(-self.pos))
        self._arrancar(-1)
        try:
            while time.ticks_diff(fin, time.ticks_ms()) > 0:
                time.sleep_ms(2)
        finally:
            self._frenar()
        self.pos = 0.0

    # --- órdenes ------------------------------------------------------------
    def _angulo_pedido(self, p):
        # Sin dato: abierto del todo. Nunca se acepta un ángulo fuera del recorrido.
        if p.get("angulo") is None:
            return self.recorrido
        angulo = float(p["angulo"])
        if angulo < 0 or angulo > self.recorrido + 1e-9:
            raise ValueError("angulo fuera del recorrido del robinete")
        return angulo

    def _exigir_ref(self):
        if not self.ref:
            raise ValueError("no se sabe en que posicion esta el robinete: "
                             "cierrelo a mano y declarelo cerrado")

    def _estado(self):
        return {"ref": self.ref, "pos": round(self.pos, 1)}

    def accion(self, a, p):
        if a == "info":                  # la PC averigua qué sabe hacer este driver y en qué posición cree estar
            r = self._estado()
            r["parcial"] = True
            r["continuo"] = True
            return r
        if a == "referencia":            # "el robinete está ahora en esta posición" (por lo general, cerrado)
            pos = float(p.get("pos", 0.0))
            if self.activo or self.mov is not None:
                raise ValueError("el servo esta en movimiento")
            if pos < 0 or pos > self.recorrido + 1e-9:
                raise ValueError("posicion fuera del recorrido")
            self.pos = pos
            self.ref = True
            self.limite = None
            return self._estado()
        if a == "cerrar":
            self._cerrar_ya()
            return self._estado()
        if a == "abrir":                 # apertura manual: igual se cierra sola al llegar a max_ms
            self._exigir_ref()
            return self._secuencia(self._angulo_pedido(p), 0, False)
        if a == "abrir_por":
            self._exigir_ref()
            ms = int(p["ms"])
            if ms <= 0 or ms > self.max_ms:
                raise ValueError("tiempo de apertura fuera del limite")
            angulo = self._angulo_pedido(p)
            # El caudal sube mientras abre y baja mientras cierra: cuenta como medio recorrido cada uno.
            # Así "ms" es el tiempo EQUIVALENTE con el robinete en esa apertura, como con un servo posicional.
            viaje = self._ms(angulo - self.pos)
            cierre = self._ms(-angulo)
            espera = ms - (viaje + cierre) // 2
            if espera < 0:
                raise ValueError("tiempo de apertura menor que lo que tarda el servo en abrir (%d ms)" % viaje)
            return self._secuencia(angulo, espera, True)
        if a == "girar":                 # ajuste a mano: gira 's' segundos (+ abre, - cierra); pierde la referencia
            s = float(p["s"])
            if self.mov is not None or s == 0 or abs(s) > 3:
                raise ValueError("giro fuera del limite (hasta 3 s)")
            return self._girar(s)
        raise ValueError("accion desconocida: " + str(a))

    def _secuencia(self, destino, espera_ms, volver):
        """Va al ángulo 'destino'. Con volver=True espera y vuelve a cerrar; si no, queda abierto."""
        completo = False
        try:
            self.activo = True
            self.limite = None
            delta = destino - self.pos
            if abs(delta) > 0.01:
                fin = time.ticks_add(time.ticks_ms(), self._ms(delta))
                self._arrancar(1 if delta > 0 else -1)
                while time.ticks_diff(fin, time.ticks_ms()) > 0:
                    yield                # devuelve el control al bucle principal
                self._frenar()
            if volver:
                fin = time.ticks_add(time.ticks_ms(), espera_ms)
                while time.ticks_diff(fin, time.ticks_ms()) > 0:
                    yield
                if self.pos > 0.01:
                    fin = time.ticks_add(time.ticks_ms(), self._ms(-self.pos))
                    self._arrancar(-1)
                    while time.ticks_diff(fin, time.ticks_ms()) > 0:
                        yield
                    self._frenar()
                self.pos = 0.0
            else:
                self.limite = time.ticks_add(time.ticks_ms(), self.max_ms)
            completo = True
        finally:
            self.activo = False
            self._frenar()
            if not completo:             # interrumpido (parada, error): se cierra SIEMPRE
                self._cerrar_ya()
        return self._estado()

    def _girar(self, s):
        signo = 1 if s > 0 else -1
        fin = time.ticks_add(time.ticks_ms(), int(abs(s) * 1000))
        try:
            self.activo = True
            self.ref = False             # se movió "a mano": la posición ya no es confiable
            self.limite = None
            self._arrancar(signo)
            while time.ticks_diff(fin, time.ticks_ms()) > 0:
                yield
        finally:
            self.activo = False
            self._frenar()
        return self._estado()

    def medir(self, magnitud):
        raise ValueError("este modulo no mide")

    def tick(self, ahora):
        if self.limite is not None and time.ticks_diff(ahora, self.limite) >= 0:
            self._cerrar_ya()
            return "robinete cerrado por tiempo maximo"
        return None

    def seguro(self):
        # Nunca mueve un robinete cuya posición se ignora: sin referencia no hay nada que cerrar "a ciegas".
        self._cerrar_ya()
