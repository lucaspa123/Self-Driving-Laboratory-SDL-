"""Imitación mínima del módulo 'machine' de MicroPython, para probar el firmware en la PC."""
REGISTRO = []          # (pin, tipo, valor) de todo lo que el firmware escribe en los pines
ENTRADAS = {}          # pin -> valor que "lee" una entrada (para simular el botón de parada)


class Pin:
    IN, OUT, PULL_UP = 0, 1, 2

    def __init__(self, numero, modo=None, pull=None, value=None):
        self.numero, self.modo = numero, modo
        self._valor = 0
        if value is not None:
            self.value(value)

    def value(self, v=None):
        if v is None:
            return ENTRADAS.get(self.numero, 0) if self.modo == Pin.IN else self._valor
        self._valor = v
        REGISTRO.append((self.numero, "pin", v))


class PWM:
    def __init__(self, pin, freq=1000):
        self.pin, self.frecuencia, self.ciclo = pin.numero, freq, 0

    def duty_u16(self, v=None):
        if v is None:
            return self.ciclo
        self.ciclo = v
        REGISTRO.append((self.pin, "pwm", v))

    def freq(self, f=None):
        if f is None:
            return self.frecuencia
        self.frecuencia = f
        REGISTRO.append((self.pin, "freq", f))

    def deinit(self):
        self.ciclo = 0
        REGISTRO.append((self.pin, "pwm", 0))
        REGISTRO.append((self.pin, "deinit", 1))


class ADC:
    ATTN_11DB = 3

    def __init__(self, pin):
        self.pin = pin

    def atten(self, a):
        pass

    def read_uv(self):
        return 1500000


class WDT:
    def __init__(self, timeout=8000):
        pass

    def feed(self):
        pass
