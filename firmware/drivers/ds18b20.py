# Driver: sensor de temperatura DS18B20 (un cable de datos con resistencia de 4,7 kΩ a 3,3 V).
#
# Configuración que manda la PC:
#   pin   GPIO del cable de datos

import time
import onewire
import ds18x20
from machine import Pin


class Driver:
    def __init__(self, cfg, sistema):
        self.sensor = ds18x20.DS18X20(onewire.OneWire(Pin(cfg["pin"])))
        self.direcciones = self.sensor.scan()

    def accion(self, a, p):
        raise ValueError("este modulo solo mide")

    def medir(self, magnitud):
        if not self.direcciones:
            self.direcciones = self.sensor.scan()
        if not self.direcciones:
            raise ValueError("no se encontro el sensor DS18B20")
        self.sensor.convert_temp()
        time.sleep_ms(750)               # tiempo que tarda el sensor en medir
        return self.sensor.read_temp(self.direcciones[0])

    def tick(self, ahora):
        return None

    def seguro(self):
        pass
