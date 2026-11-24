# Driver: sensor de pH analógico (placa amplificadora tipo PH-4502C) con temperatura opcional.
#
# Configuración que manda la PC:
#   pin       GPIO de la señal de pH (ADC1: GPIO 1 a 10 en el ESP32-S2)
#   muestras  cantidad de lecturas que se promedian
#   temp      None, "ds18b20" o "analogica"
#   pin_temp  GPIO de la temperatura
#
# Devuelve la señal en milivoltios; la conversión a pH (calibración con buffers)
# la hace la PC. La tensión en el pin no debe pasar de ~2,5 V: usar un divisor.

import time
from machine import Pin, ADC


class Driver:
    def __init__(self, cfg, sistema):
        self.adc = ADC(Pin(cfg["pin"]))
        self.adc.atten(ADC.ATTN_11DB)            # rango de medición más amplio (hasta ~2,5 V)
        self.muestras = int(cfg.get("muestras", 40))
        self.tipo_temp = cfg.get("temp")
        self.sonda = None
        self.direcciones = []
        self.adc_temp = None
        if self.tipo_temp == "ds18b20":
            import onewire
            import ds18x20
            self.sonda = ds18x20.DS18X20(onewire.OneWire(Pin(cfg["pin_temp"])))
            self.direcciones = self.sonda.scan()
        elif self.tipo_temp == "analogica":
            self.adc_temp = ADC(Pin(cfg["pin_temp"]))
            self.adc_temp.atten(ADC.ATTN_11DB)

    def _milivoltios(self, adc):
        # Promedia lecturas repartidas en ~80 ms (cuatro ciclos de la red de 50 Hz: cancela su ruido).
        total = 0
        for _ in range(self.muestras):
            total += adc.read_uv()
            time.sleep_ms(2)
        return total / self.muestras / 1000

    def accion(self, a, p):
        raise ValueError("este modulo solo mide")

    def medir(self, magnitud):
        if magnitud == "ph_mv":
            return self._milivoltios(self.adc)
        if magnitud == "temperatura":
            if self.tipo_temp == "ds18b20":
                if not self.direcciones:
                    self.direcciones = self.sonda.scan()
                if not self.direcciones:
                    raise ValueError("no se encontro la sonda de temperatura")
                self.sonda.convert_temp()
                time.sleep_ms(750)
                return self.sonda.read_temp(self.direcciones[0])
            if self.tipo_temp == "analogica":
                return self._milivoltios(self.adc_temp)      # mV: la PC los pasa a grados
            raise ValueError("este modulo no tiene temperatura configurada")
        raise ValueError("magnitud desconocida: " + str(magnitud))

    def tick(self, ahora):
        return None

    def seguro(self):
        pass
