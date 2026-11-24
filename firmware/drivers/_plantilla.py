# PLANTILLA de driver para un módulo nuevo (por ejemplo, el sensor de pH).
#
# 1. Copiar este archivo con otro nombre (ej. sensor_ph.py). Los archivos que
#    empiezan con "_" se ignoran.
# 2. Completar la clase Driver.
# 3. Copiarlo al ESP32:   mpremote cp drivers/sensor_ph.py :drivers/sensor_ph.py
# 4. En la PC, crear el módulo que lo usa (sdl/modulos/_plantilla.py) con
#    DRIVER = "sensor_ph".
#
# Ejemplo: sensor analógico conectado a una entrada del conversor (ADC1: GPIO 1 a 10).

from machine import Pin, ADC


class Driver:
    def __init__(self, cfg, sistema):
        # 'cfg' es lo que devuelve config_firmware() del módulo de la PC.
        self.adc = ADC(Pin(cfg["pin"]))
        self.adc.atten(ADC.ATTN_11DB)        # rango de 0 a ~3,1 V

    def accion(self, a, p):
        # Un sensor puro no tiene acciones. Un actuador devuelve {} al terminar,
        # o un generador (función con 'yield') si la acción lleva tiempo.
        raise ValueError("este modulo solo mide")

    def medir(self, magnitud):
        # Promedia varias lecturas y devuelve milivoltios; la PC aplica la calibración.
        total = 0
        for _ in range(32):
            total += self.adc.read_uv()
        return total / 32 / 1000

    def tick(self, ahora):
        # Se llama en cada vuelta del bucle. Sirve para límites de tiempo propios.
        # Devolver un texto si hay algo que avisar a la PC, o None.
        return None

    def seguro(self):
        # Un actuador SIEMPRE debe dejar acá su salida apagada o cerrada.
        pass
