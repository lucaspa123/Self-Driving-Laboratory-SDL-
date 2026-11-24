"""Prueba la bureta con servo de ROTACIÓN CONTINUA contra el firmware real, con pines de mentira.

Comprueba, sobre todo, lo que importa con ese servo: que al conectar NO reciba ningún pulso
(no gira ni vibra), que no se mueva sin saber dónde está el robinete, que cada dosis lo
abra y lo cierre por tiempo y que cualquier parada lo deje cerrado. No reemplaza la prueba
con el servo real.
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
base = Path(tempfile.gettempdir()) / "sdl_prueba_servo_continuo"
shutil.rmtree(base, ignore_errors=True)
gestor = GestorModulos(base / "config")
gestor.datos["conexion"]["modo"] = "esp32"
gestor.datos["conexion"]["puerto"] = "PRUEBA"
gestor.datos["sistema"]["pin_parada"] = 21
gestor.datos["sistema"]["tiempo_latido_s"] = 30
paquete_modulos.EnlaceSerie = lambda puerto: EnlaceDirecto()
machine.ENTRADAS[21] = 0

PIN = 13
VEL = 150
ABRIR = (1500 + VEL) * 65535 // 20000
CERRAR = (1500 - VEL) * 65535 // 20000
bureta = gestor.modulos["bureta_1"]


def configurar(**valores):
    """Cambia la configuración de la bureta de modo que sobreviva a cada reconexión."""
    gestor.ficha("bureta_1")["config"].update(valores)
    bureta.config.update(valores)


def conectar():
    global bureta
    resultado = gestor.conectar()               # al conectar se crean módulos nuevos desde la configuración
    bureta = gestor.modulos["bureta_1"]
    return resultado


configurar(servo_continuo=True, servo_deg_por_s=360.0, servo_vel_us=VEL, caudal_k=0.5)   # servo rápido, caudal alto
assert bureta.DRIVER == "servo_continuo" and bureta.continuo


def pulsos(pin=PIN):
    """Lo que el firmware mandó al pin: ancho de cada pulso (0 = sin pulsos)."""
    return [v for p, t, v in machine.REGISTRO if p == pin and t == "pwm"]


def correr_firmware(segundos):
    limite = tiempo_real.time() + segundos
    while tiempo_real.time() < limite:
        fw.vuelta()
        tiempo_real.sleep(0.005)


def driver():
    return fw.S.modulos["bureta_1"][2]


# 1. Al conectar el servo NO recibe ningún pulso (era lo que lo hacía vibrar solo)
machine.REGISTRO.clear()
ok, mensaje = conectar()
print("conexión:", ok, mensaje)
assert ok, mensaje
bien, texto = gestor.pruebas["bureta_1"]
assert bien and "falta indicar" in texto, texto
assert not any(v for v in pulsos()), f"el servo recibió pulsos al conectar: {pulsos()}"
assert not [1 for p, t, v in machine.REGISTRO if p == PIN and t in ("freq", "deinit")]
assert driver().ref is False and bureta.avisos()
print("1. conectar: el servo no recibió ni un pulso;", texto)

# 2. Sin saber dónde está el robinete no se mueve (ni dosifica, ni abre, ni cierra)
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
for orden in (lambda: bureta.ejecutar("dosificar", {"volumen": 2.0}), lambda: bureta.ejecutar("abrir", {}),
              lambda: bureta.ejecutar("cerrar", {})):
    try:
        orden()
        raise AssertionError("no debía moverse sin referencia")
    except ErrorModulo as error:
        assert "posición" in str(error)
try:
    gestor.enlace.accion("bureta_1", "abrir_por", ms=2000)       # el firmware tampoco lo permite
    raise AssertionError("el firmware debía negarse")
except ErrorEnlace as error:
    assert "posicion" in str(error)
assert not any(v for v in pulsos())
print("2. sin referencia: la PC y el firmware se niegan a mover el servo")

# 3. Se declara cerrado y la dosis abre y cierra por tiempo
bureta.ejecutar("declarar_cerrado", {})
assert driver().ref and driver().pos == 0 and not bureta.avisos()[1:]
assert bureta.estado["servo_cerrado"] is True
machine.REGISTRO.clear()
inicio = tiempo_real.time()
r = bureta.ejecutar("dosificar", {"volumen": 2.0})
duracion = tiempo_real.time() - inicio
assert [v for v in pulsos() if v] == [ABRIR, CERRAR], pulsos()
assert pulsos()[-1] == 0, "al terminar el servo no debe seguir recibiendo pulsos"
assert abs(driver().pos) < 1e-9 and driver().ref and driver().limite is None
assert abs(bureta.estado["disponible_ml"] - 23.0) < 1e-6
viaje = 90 / 360.0
assert abs(duracion - (r["segundos"] + viaje)) < 0.25, (duracion, r["segundos"], viaje)
print(f"3. dosis de 2 mL: {r['segundos']} s equivalentes, {duracion:.2f} s en total; "
      f"pulsos abrir/cerrar y silencio al final")

# 4. Una dosis más corta que el recorrido del servo se rechaza ANTES de mover nada
machine.REGISTRO.clear()
configurar(caudal_k=5.0)
try:
    bureta.ejecutar("dosificar", {"volumen": 0.2})
    raise AssertionError("debía rechazar una dosis más corta que el recorrido")
except ErrorModulo as error:
    print("4. dosis demasiado corta:", error)
assert not any(v for v in pulsos())
configurar(caudal_k=0.5)

# 5. Apertura parcial: recorre solo ese tramo y vuelve a cero
bureta.calibrar_manual({"apertura": 40, "inicial": 25, "salio": 5, "segundos": 2})
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
machine.REGISTRO.clear()
caudal = bureta.caudal_nominal(bureta.tabla()[40.0])
r = bureta.ejecutar("dosificar", {"volumen": 1.0, "caudal": caudal})
assert r["apertura_pct"] == 40.0 and [v for v in pulsos() if v] == [ABRIR, CERRAR], (r, pulsos())
assert abs(driver().pos) < 1e-9
assert abs(bureta._angulo(40.0) - 36.0) < 1e-9          # 40 % de 90°: grados desde cerrado
print("5. apertura parcial al 40 %: 36° desde cerrado, y vuelve a cerrado")
bureta.config["aperturas"] = []

# 6. Abrir a mano y cerrar; el firmware lo cierra solo al llegar a su tiempo máximo
configurar(apertura_max_s=1)
conectar()                                         # reconfigura el firmware con el máximo nuevo
assert driver().max_ms == 1000 and driver().ref and driver().pos == 0     # sin moverse: la PC recordó que estaba cerrado
machine.REGISTRO.clear()
bureta.ejecutar("abrir", {"apertura": 50})
assert abs(driver().pos - 45.0) < 1.0 and bureta.estado["servo_cerrado"] is False
assert [v for v in pulsos() if v] == [ABRIR]
correr_firmware(1.6)
assert [v for v in pulsos() if v] == [ABRIR, CERRAR] and abs(driver().pos) < 1e-9, (pulsos(), driver().pos)
assert pulsos()[-1] == 0
print("6. abrir a mano al 50 %: el firmware lo cerró solo al pasar el máximo (1 s)")
bureta.ejecutar("abrir", {"apertura": 100})
bureta.ejecutar("cerrar", {})
assert abs(driver().pos) < 1e-9 and bureta.estado["servo_cerrado"] is True
configurar(apertura_max_s=60)

# 7. Parada física en medio de una dosis: se detiene, se cierra y queda enclavado
conectar()
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
configurar(caudal_k=0.002)                 # dosis lenta, para cortarla a la mitad
machine.REGISTRO.clear()
import threading                                   # noqa: E402
threading.Timer(0.8, lambda: machine.ENTRADAS.__setitem__(21, 1)).start()
try:
    bureta.ejecutar("dosificar", {"volumen": 1.0})
    raise AssertionError("la parada no cortó la dosificación")
except ParadaEmergencia as error:
    print("7. parada física:", error)
assert [v for v in pulsos() if v] == [ABRIR, CERRAR], pulsos()      # abrió, y al parar cerró
assert pulsos()[-1] == 0 and abs(driver().pos) < 1e-9 and bureta.estado["disponible_ml"] is None
machine.ENTRADAS[21] = 0
gestor.enlace.enviar("rearmar")
configurar(caudal_k=0.5)

# 8. Reinicio del ESP32: la PC recuerda que el robinete quedó cerrado y lo informa sin mover el servo
fw.S.modulos.clear()                               # el ESP32 "se reinicia": pierde sus drivers y la posición
machine.REGISTRO.clear()
conectar()
assert gestor.pruebas["bureta_1"][0] and driver().ref and not any(v for v in pulsos())
print("8. reinicio del ESP32:", gestor.pruebas["bureta_1"][1])

# 9. Giro a mano: se pierde la referencia hasta declarar de nuevo
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
machine.REGISTRO.clear()
bureta.ejecutar("girar", {"segundos": 0.2})
assert [v for v in pulsos() if v] == [ABRIR] and pulsos()[-1] == 0 and driver().ref is False
assert bureta.estado["servo_cerrado"] is False
try:
    bureta.ejecutar("dosificar", {"volumen": 2.0})
    raise AssertionError("tras girar a mano no debe dosificar sin declarar cerrado")
except ErrorModulo:
    pass
bureta.ejecutar("girar", {"segundos": -0.2})
assert pulsos()[-2:] == [CERRAR, 0]
bureta.ejecutar("declarar_cerrado", {})
bureta.ejecutar("dosificar", {"volumen": 2.0})
for mal in (4.0, -4.0):
    try:
        bureta.ejecutar("girar", {"segundos": mal})
        raise AssertionError("debía rechazar un giro largo")
    except ErrorModulo:
        pass
print("9. girar a mano: pierde la referencia; se recupera con «declarar cerrado»")

# 10. Sentido invertido y velocidad: cambia el pulso
configurar(servo_sentido=-1)
conectar()
machine.REGISTRO.clear()
bureta.ejecutar("dosificar", {"volumen": 2.0})
assert [v for v in pulsos() if v] == [CERRAR, ABRIR], pulsos()      # el pulso que "abre" ahora es el menor
configurar(servo_sentido=1)
print("10. sentido invertido: abre con el pulso menor")

# 11. Configuración inválida: el firmware la rechaza y el módulo queda como no disponible
configurar(servo_vel_us=900)
ok, mensaje = conectar()
assert ok and not gestor.pruebas["bureta_1"][0], gestor.pruebas["bureta_1"]
print("11. velocidad fuera de rango:", gestor.pruebas["bureta_1"][1])
configurar(servo_vel_us=VEL)
conectar()

# 12. Aviso cuando hace muchas aperturas que no se verifica el cierre
bureta.estado["servo_ciclos"] = 30
assert any("verifica" in a for a in bureta.avisos())
bureta.ejecutar("declarar_cerrado", {})
assert not any("verifica" in a for a in bureta.avisos())
print("12. aviso de verificación de cierre tras 30 aperturas")

# 12b. Dosis larga: se reparte en aperturas de igual duración (ninguna diminuta) y todas terminan cerradas
configurar(apertura_max_s=2, caudal_k=0.05)
conectar()
bureta.ejecutar("fijar_volumen", {"volumen": 25.0})
ordenes = []
original = gestor.enlace.accion
gestor.enlace.accion = lambda modulo, accion, espera=None, **p: (ordenes.append((accion, p)),
                                                                  original(modulo, accion, espera=espera, **p))[1]
machine.REGISTRO.clear()
r = bureta.ejecutar("dosificar", {"volumen": 3.0})
gestor.enlace.accion = original
tiempos = [o[1]["ms"] for o in ordenes if o[0] == "abrir_por"]
assert r["aperturas"] == len(tiempos) >= 2 and all(t <= 2000 for t in tiempos), (r, tiempos)
assert max(tiempos) - min(tiempos) <= 0.25 * max(tiempos), f"aperturas desparejas: {tiempos}"
assert [v for v in pulsos() if v] == [ABRIR, CERRAR] * len(tiempos) and abs(driver().pos) < 1e-9
assert abs(bureta.estado["disponible_ml"] - 22.0) < 1e-3
print(f"12b. dosis de 3 mL en {len(tiempos)} aperturas parejas: {tiempos} ms")
configurar(apertura_max_s=60, caudal_k=0.5)
conectar()

# 13. Si el firmware del ESP32 es el viejo (sin el driver nuevo) la PC lo dice y no mueve nada
nuevo = fw.drivers_disponibles
fw.drivers_disponibles = lambda: [d for d in nuevo() if d != "servo_continuo"]
ok, mensaje = conectar()
texto = gestor.pruebas["bureta_1"][1]
assert not gestor.pruebas["bureta_1"][0] and "servo_continuo" in texto
fw.drivers_disponibles = nuevo
print("13. sin el driver nuevo en el ESP32:", texto)

# 14. En simulación (sin ESP32) también funciona
from sdl.modulos import GestorModulos as Gestor2                      # noqa: E402
sim = Gestor2(base / "config_sim")
sim.datos["conexion"]["aceleracion_simulacion"] = 200
sim.ficha("bureta_1")["config"].update({"servo_continuo": True, "servo_deg_por_s": 360.0, "caudal_k": 0.5})
ok, mensaje = sim.conectar()
assert ok and sim.pruebas["bureta_1"][0], (mensaje, sim.pruebas)
assert sim.modulos["bureta_1"].continuo and sim.modulos["bureta_1"].DRIVER == "servo_continuo"
sim.modulos["bureta_1"].ejecutar("fijar_volumen", {"volumen": 25.0})
r = sim.modulos["bureta_1"].ejecutar("dosificar", {"volumen": 2.0})
sim.modulos["bureta_1"].ejecutar("declarar_cerrado", {})
assert r["volumen"] == 2.0
sim.desconectar()
print("14. simulación: conecta y dosifica")
print("OK")
