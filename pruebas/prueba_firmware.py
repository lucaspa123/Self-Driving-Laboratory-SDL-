"""Prueba el firmware del ESP32 en la PC, con pines de mentira.

Conecta los módulos reales de la PC (bureta, bomba, agitador, brazo, termómetro)
con el código real del firmware, sin cable: así se comprueba que los dos lados
hablan el mismo idioma. No reemplaza la prueba con el hardware real.
"""
import json
import os
import sys
import shutil
import tempfile
import time as tiempo_real
import types
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

# --- entorno falso de MicroPython ---------------------------------------------------
falso = types.ModuleType("time")
falso.__dict__.update(tiempo_real.__dict__)
falso.ticks_ms = lambda: int(tiempo_real.monotonic() * 1000)
falso.ticks_us = lambda: int(tiempo_real.monotonic() * 1000000)
falso.ticks_add = lambda a, b: a + b
falso.ticks_diff = lambda a, b: a - b
falso.sleep_ms = lambda ms: tiempo_real.sleep(ms / 1000)
falso.sleep_us = lambda us: None if us < 50 else tiempo_real.sleep(us / 1000000)
seleccion = types.ModuleType("select")
seleccion.POLLIN = 1
seleccion.poll = lambda: types.SimpleNamespace(register=lambda *a: None, poll=lambda t: [])

sys.path.insert(0, str(RAIZ / "pruebas" / "micropython_falso"))
sys.path.insert(0, str(RAIZ / "firmware"))
reales = {n: sys.modules.get(n) for n in ("time", "select")}
sys.modules["time"], sys.modules["select"] = falso, seleccion
os.chdir(RAIZ / "firmware")                      # el firmware busca la carpeta drivers/
import main as fw                                # noqa: E402  (firmware/main.py)
import machine                                   # noqa: E402  (el falso)
sys.modules["select"] = reales["select"]       # 'time' queda con el falso: los drivers se cargan más tarde
# (se queda en la carpeta firmware: ahí busca drivers/)

salida = []
fw.enviar = salida.append

from sdl.comunicacion import Enlace, ErrorEnlace, ParadaEmergencia   # noqa: E402
from sdl.modulos import GestorModulos                                 # noqa: E402
from sdl.modulos.base import ErrorModulo, NecesitaUsuario                          # noqa: E402
import sdl.modulos as paquete_modulos                                 # noqa: E402


class EnlaceDirecto(Enlace):
    """Entrega cada orden al firmware y hace girar su bucle hasta que contesta."""
    descripcion = "Firmware en la PC (prueba)"

    def __init__(self):
        super().__init__()
        self.n = 0

    def conectado(self):
        return True

    def enviar(self, comando, espera=3.0, **datos):
        self.n += 1
        fw.procesar(json.dumps({"id": self.n, "c": comando, **datos}))
        limite = tiempo_real.time() + espera
        while tiempo_real.time() < limite:
            fw.vuelta()
            for mensaje in list(salida):
                if "ev" in mensaje:
                    salida.remove(mensaje)
                    eventos.append(mensaje)
                elif mensaje.get("id") == self.n:
                    salida.remove(mensaje)
                    if mensaje["ok"]:
                        return mensaje["r"]
                    if str(mensaje["e"]).startswith("parada"):
                        raise ParadaEmergencia(mensaje["e"])
                    raise ErrorEnlace(mensaje["e"])
        raise ErrorEnlace(f"sin respuesta a {comando}")

    def parar(self):
        fw.procesar(json.dumps({"c": "parar"}))


eventos = []
base = Path(tempfile.gettempdir()) / "sdl_prueba_firmware"
shutil.rmtree(base, ignore_errors=True)
gestor = GestorModulos(base / "config")
gestor.agregar("agitador_nema17", "agitador_paso", "Agitador NEMA17")
assert not gestor.conflictos_de_pines(), gestor.conflictos_de_pines()
gestor.datos["conexion"]["modo"] = "esp32"
gestor.datos["conexion"]["puerto"] = "PRUEBA"
gestor.datos["sistema"]["pin_parada"] = 21
gestor.datos["sistema"]["tiempo_latido_s"] = 1
paquete_modulos.EnlaceSerie = lambda puerto: EnlaceDirecto()
machine.ENTRADAS[21] = 0                          # botón de parada en reposo

ok, mensaje = gestor.conectar()
print("conexión:", ok, mensaje)
for ident, (bien, texto) in gestor.pruebas.items():
    print(f"  {ident:11} {'OK ' if bien else 'FALLA'} {texto}")
assert ok and all(b for b, _ in gestor.pruebas.values()), "algún módulo no respondió"


def ultimo_pwm(pin):
    return [v for p, t, v in machine.REGISTRO if p == pin and t == "pwm"][-1]


CERRADO = (500 + 0) * 65535 // 20000
ABIERTO = (500 + 1000) * 65535 // 20000

# 1. Bureta: dosifica y SIEMPRE termina cerrada
bureta = gestor.modulos["bureta_1"]
bureta.config["caudal_k"] = 0.5                   # caudal alto para que la prueba sea rápida
try:
    bureta.ejecutar("dosificar", {"volumen": 2.0})
    raise AssertionError("debía preguntar cuánto reactivo hay")
except NecesitaUsuario as pedido:
    bureta.resolver(pedido.clave, {"disponible": 25.0})
machine.REGISTRO.clear()
r = bureta.ejecutar("dosificar", {"volumen": 2.0})
pwm = [v for p, t, v in machine.REGISTRO if p == 13 and t == "pwm"]
assert pwm == [ABIERTO, CERRADO], pwm
assert abs(bureta.estado["disponible_ml"] - 23.0) < 1e-6
print(f"bureta: abrió {r['segundos']} s y cerró. Quedan {bureta.estado['disponible_ml']} mL")

# 1b. Apertura parcial: el servo va al ángulo intermedio pedido y después cierra
bureta.calibrar_manual({"apertura": 40, "inicial": 25, "salio": 5, "segundos": 2})
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
machine.REGISTRO.clear()
r = bureta.ejecutar("dosificar", {"volumen": 1.0, "caudal": bureta.caudal_nominal(bureta.tabla()[40.0])})
PARCIAL = (500 + int(2000 * 36.0 / 180)) * 65535 // 20000            # 40 % de 90° = 36°
pwm = [v for p, t, v in machine.REGISTRO if p == 13 and t == "pwm"]
assert r["apertura_pct"] == 40.0 and pwm == [PARCIAL, CERRADO], (r, pwm)
try:
    gestor.enlace.accion("bureta_1", "abrir_por", ms=500, angulo=140)
    raise AssertionError("debía rechazar un ángulo fuera del recorrido")
except ErrorEnlace as error:
    print("apertura parcial: servo a 36° y cierre; fuera de recorrido ->", error)
bureta.ejecutar("abrir", {"apertura": 50})
assert ultimo_pwm(13) == (500 + int(2000 * 45.0 / 180)) * 65535 // 20000
bureta.ejecutar("cerrar", {})
bureta.config["aperturas"] = []
bureta.ejecutar("fijar_volumen", {"volumen": 23.0})

# 2. Firmware: rechaza una apertura más larga que su límite (capa 1 de seguridad)
try:
    gestor.enlace.accion("bureta_1", "abrir_por", ms=10 ** 7)
    raise AssertionError("debía rechazarlo")
except ErrorEnlace as error:
    print("límite del firmware:", error)

# 3. Bomba en los dos sentidos y agitador
bomba = gestor.modulos["bomba"]
bomba.config["caudal_ml_s"] = 20.0
bomba.ejecutar("bombear", {"volumen": 4.0})
assert ultimo_pwm(33) == 0
bomba.ejecutar("retroceder", {"volumen": 4.0})
assert ultimo_pwm(34) == 0
agitador = gestor.modulos["agitador"]
agitador.ejecutar("encender", {"velocidad": 50})
assert ultimo_pwm(16) == int(50 * 65535 / 100)
agitador.ejecutar("apagar", {})
assert ultimo_pwm(16) == 0
print("bomba y agitador: correctos")

# 3b. Agitador NEMA17: rampa de arranque, un solo sentido (sin pin DIR), se apaga y suelta el motor
nema = gestor.modulos["agitador_paso"]
HZ = int(120 * 200 * 16 / 60)                     # 120 rpm con 16 micropasos = 6400 pasos/s
assert abs(nema.hz(120) - HZ) < 1e-6
machine.REGISTRO.clear()
nema.ejecutar("agitar", {"velocidad": 120, "segundos": 1})
frecuencias = [v for p, t, v in machine.REGISTRO if p == 17 and t == "freq"]
assert frecuencias and frecuencias[0] <= 200, frecuencias[:3]
assert frecuencias == sorted(frecuencias) and max(frecuencias) <= HZ, frecuencias
assert len(frecuencias) >= 5, "el motor no aceleró en rampa"
en = [v for p, t, v in machine.REGISTRO if p == 18 and t == "pin"]
assert en[0] == 0 and en[-1] == 1, en               # con corriente mientras gira; libre al terminar
assert ultimo_pwm(17) == 0 and [1 for p, t, v in machine.REGISTRO if p == 17 and t == "deinit"]
assert not any(p in (19, 20) for p, t, v in machine.REGISTRO)      # no toca los pines del USB
print(f"agitador NEMA17: rampa de {frecuencias[0]:g} a {max(frecuencias):g} pasos/s, "
      f"y al terminar queda apagado y sin corriente")
for mal in ({"velocidad": 400, "segundos": 1}, {"velocidad": 10, "segundos": 1}):
    try:
        nema.ejecutar("agitar", mal)
        raise AssertionError("debía rechazar la velocidad")
    except ErrorModulo as error:
        pass
try:
    gestor.enlace.accion("agitador_paso", "girar", hz=nema.hz(300) * 3, accel=1000)
    raise AssertionError("el firmware debía rechazar esa velocidad")
except ErrorEnlace as error:
    print("límite del firmware (NEMA17):", error)
try:
    gestor.enlace.accion("agitador_paso", "girar", hz=1000, accel=1000, ms=10 ** 8)
    raise AssertionError("el firmware debía rechazar ese tiempo")
except ErrorEnlace:
    pass
nema.config["micropasos"] = 3
try:
    nema.config_firmware()
    raise AssertionError("debía rechazar micropasos inválidos")
except ErrorModulo:
    pass
nema.config["micropasos"] = 16
nema.config["rpm_max"] = 900
assert nema.avisos(), "debía avisar que 900 rpm superan lo que el motor sigue"
nema.config["rpm_max"] = 300
print("agitador NEMA17: límites de la PC y del firmware correctos")

# 4. Termómetro
print("temperatura:", gestor.modulos["termometro"].medir("temperatura"), "°C")

# 4b. Sensor de pH: se agrega como módulo nuevo y mide por el driver real
gestor.agregar("ph", "sensor_ph", "Sensor de pH")
gestor.ficha("sensor_ph")["config"] = {"temperatura": "ds18b20", "pin_temperatura": 2}
ok, mensaje = gestor.conectar()
assert ok and gestor.pruebas["sensor_ph"][0], gestor.pruebas["sensor_ph"]
bureta, bomba, agitador = (gestor.modulos[x] for x in ("bureta_1", "bomba", "agitador"))
bureta.config["caudal_k"] = 0.5
sensor = gestor.modulos["sensor_ph"]
ph = sensor.medir("ph")                           # el ADC falso entrega 1500 mV
assert abs(ph - (7 + (1500 - 1667) / -118)) < 0.01, ph
assert sensor.medir("temperatura") == 24.5
print(f"sensor de pH: {gestor.pruebas['sensor_ph'][1]} Temperatura {sensor.medir('temperatura')} °C")

# 5. Brazo: sin origen no se mueve; con origen cuenta los pasos y respeta el recorrido
brazo = gestor.modulos["brazo"]
try:
    brazo.ejecutar("mover_eje", {"eje": "Cintura", "grados": 5})
    raise AssertionError("debía exigir el origen")
except Exception as error:
    print("brazo sin origen:", error)
brazo.ejecutar("fijar_origen", {})
machine.REGISTRO.clear()
brazo.ejecutar("mover_eje", {"eje": "Cintura", "grados": 5})
pulsos = sum(1 for p, t, v in machine.REGISTRO if p == 4 and t == "pin" and v == 1)
esperados = round(5 * 200 * 8 * 8.8 / 360)
assert pulsos == esperados, (pulsos, esperados)
assert abs(brazo.angulos()[0] - 5.0) < 0.05
brazo.ejecutar("guardar_estacion", {"nombre": "vaso"})
brazo.ejecutar("mover_eje", {"eje": "Cintura", "grados": -5})
brazo.ejecutar("ir_a", {"estacion": "vaso"})
assert abs(brazo.angulos()[0] - 5.0) < 0.05
try:
    gestor.enlace.accion("brazo", "mover", eje=0, pasos=10 ** 6, vel=500)
    raise AssertionError("debía rechazarlo")
except ErrorEnlace as error:
    print("brazo fuera de recorrido:", error)
brazo.ejecutar("cerrar_pinza", {})
print(f"brazo: {pulsos} pulsos para 5° de cintura, estación guardada y alcanzada")

# 6. Vigilancia de la PC: sin latido, lo que estaba encendido se apaga solo
agitador.ejecutar("encender", {"velocidad": 60})
nema.ejecutar("encender", {"velocidad": 60})
limite = tiempo_real.time() + 3
while tiempo_real.time() < limite and (ultimo_pwm(16) != 0 or ultimo_pwm(17) != 0):
    fw.vuelta()
    tiempo_real.sleep(0.01)
assert ultimo_pwm(16) == 0, "el agitador siguió girando sin latido de la PC"
assert ultimo_pwm(17) == 0, "el agitador NEMA17 siguió girando sin latido de la PC"
print("sin latido de la PC: los dos agitadores se apagaron solos")

# 7. Botón físico de parada en medio de una dosificación: cierra y queda enclavado
nema.ejecutar("encender", {"velocidad": 60})
bureta.resolver("disponible", {"disponible": 25.0})
bureta.config["caudal_k"] = 0.002                 # dosis lenta, para cortarla a la mitad
machine.ENTRADAS[21] = 0
import threading                                   # noqa: E402
threading.Timer(0.4, lambda: machine.ENTRADAS.__setitem__(21, 1)).start()
try:
    bureta.ejecutar("dosificar", {"volumen": 1.0})
    raise AssertionError("la parada no cortó la dosificación")
except ParadaEmergencia as error:
    print("parada física:", error)
assert ultimo_pwm(13) == CERRADO and bureta.estado["disponible_ml"] is None
assert ultimo_pwm(17) == 0, "la parada no apagó el agitador NEMA17"
assert [v for p, t, v in machine.REGISTRO if p == 18 and t == "pin"][-1] == 1
assert any(e.get("ev") == "parada" for e in eventos + salida)
try:
    gestor.enlace.accion("agitador", "girar", potencia=50, sentido=1)
    raise AssertionError("con la parada enclavada no debe aceptar órdenes")
except (ErrorEnlace, ParadaEmergencia):
    pass
try:
    gestor.enlace.enviar("rearmar")
    raise AssertionError("no debe rearmar con el botón apretado")
except ErrorEnlace:
    pass
machine.ENTRADAS[21] = 0
gestor.enlace.enviar("rearmar")
agitador.ejecutar("encender", {"velocidad": 30})
agitador.ejecutar("apagar", {})
nema.ejecutar("encender", {"velocidad": 60})
nema.ejecutar("apagar", {})
print("rearme: solo con el botón liberado; después acepta órdenes")
print("OK")
