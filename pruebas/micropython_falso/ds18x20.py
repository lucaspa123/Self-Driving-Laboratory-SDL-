class DS18X20:
    def __init__(self, bus):
        self.bus = bus

    def scan(self):
        return [b"sensor-falso"]

    def convert_temp(self):
        pass

    def read_temp(self, direccion):
        return 24.5
