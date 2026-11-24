"""Pruebas de la bureta (reactivo disponible, calibración a mano) y del sensor de pH, en simulación."""
import shutil
import sys
import tempfile
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from sdl.ejemplo import crear_ejemplo                          # noqa: E402
from sdl.historial import COMPLETADO                            # noqa: E402
from sdl.modelos import Objetivo, Paso                          # noqa: E402
from sdl.modulos import GestorModulos                           # noqa: E402
from sdl.modulos.base import ErrorModulo, NecesitaUsuario       # noqa: E402
from sdl.motor import TERMINADO, Motor                          # noqa: E402
from sdl import seguridad                                       # noqa: E402

BASE = Path(tempfile.gettempdir()) / "sdl_prueba_bureta_ph"
shutil.rmtree(BASE, ignore_errors=True)

# 1. El problema informado: bureta llena, el usuario escribe 25 y debe poder dosificar ------------
g = GestorModulos(BASE / "a" / "config")
assert g.conectar()[0]
b = g.modulos["bureta_1"]
pedido = b.al_iniciar_campana("NaOH 1 M")
assert pedido.clave == "disponible" and pedido.campos[0]["valor"] == 25.0
b.resolver(pedido.clave, {"disponible": 25})
r = b.ejecutar("dosificar", {"volumen": 8.0})
assert r["volumen"] == 8.0 and abs(b.estado["disponible_ml"] - 17.0) < 1e-6
print("1a. bureta llena = 25 mL: dosifica 8 mL y quedan 17")

b.ejecutar("fijar_volumen", {"volumen": 3.0})                   # queda poco
try:
    b.ejecutar("dosificar", {"volumen": 8.0})
    raise AssertionError("debía pedir la recarga")
except NecesitaUsuario as pedido:
    assert "hay 3.0 mL" in pedido.mensaje and "8.0 mL" in pedido.mensaje
    assert pedido.campos[0]["min"] == 8.0 and pedido.campos[0]["valor"] == 25.0   # no acepta menos de lo necesario
    b.resolver(pedido.clave, {"disponible": 25})                # el usuario recarga y escribe 25
assert b.ejecutar("dosificar", {"volumen": 8.0})["volumen"] == 8.0
print("1b. sin reactivo suficiente: pide la recarga una sola vez; con 25 sigue")

# 1c. Lo guardado por la versión anterior (lectura de la escala) se convierte al abrir
g.estados["bureta_2"] = {"lectura_ml": 5.0}
g.instanciar()
assert abs(g.modulos["bureta_2"].estado["disponible_ml"] - 20.0) < 1e-9
print("1c. dato guardado por la versión anterior (lectura 5) -> 20 mL disponibles")

# 2. Calibración a mano: volumen que salió y tiempo que tardó ----------------------------------
b = g.modulos["bureta_1"]
previa = b.calibrar_previa({"inicial": 25, "salio": 10, "segundos": 20})
assert "0.500 mL/s" in previa[0] and not b.config["calibrada"]   # la vista previa no guarda nada
mensaje = b.calibrar_manual({"inicial": 25, "salio": 10, "segundos": 20})
assert b.config["calibrada"] and abs(b.estado["disponible_ml"] - 15.0) < 1e-9
assert abs(b.tiempo_para(10, 25) - 20.0) < 1e-3                 # reproduce la medición
assert b.tiempo_para(10, 15) > b.tiempo_para(10, 25)            # con menos nivel sale más lento
assert abs(b.volumen_en(b.tiempo_para(4.2, 18), 18) - 4.2) < 1e-6
for malo in ({"inicial": 25, "salio": 30, "segundos": 20}, {"inicial": 25, "salio": 10, "segundos": 0}):
    try:
        b.calibrar_manual(malo)
        raise AssertionError("debía rechazarlo")
    except ErrorModulo:
        pass
print("2.  calibración a mano:", mensaje)

# 2b. Apertura parcial: cada apertura tiene su caudal; al dosificar se elige la más cercana al pedido ------
import math                                                       # noqa: E402
from sdl.comunicacion import ErrorEnlace                          # noqa: E402
assert not b.acciones()["dosificar"]["parametros"]["caudal"]["optimizable"]      # con una sola apertura no hay qué elegir
b.calibrar_manual({"apertura": 40, "inicial": 25, "salio": 5, "segundos": 50})   # 0,1 mL/s medio
b.calibrar_manual({"apertura": 60, "inicial": 25, "salio": 5, "segundos": 20})   # 0,25 mL/s medio
tabla = b.tabla()
assert sorted(tabla) == [40.0, 60.0, 100.0] and tabla[40.0] < tabla[60.0] < tabla[100.0]
caudal = b.acciones()["dosificar"]["parametros"]["caudal"]
assert caudal["optimizable"] and caudal["opcional"] and caudal["min"] < 0.11 < 0.5 < caudal["max"]
assert b.elegir_apertura(None)[0] == 100.0                        # sin pedido: abierto del todo
b.config["caudal_continuo"] = False                               # solo aperturas calibradas: la más cercana
assert b.elegir_apertura(0.10)[0] == 40.0 and b.elegir_apertura(0.27)[0] == 60.0 and b.elegir_apertura(0.5)[0] == 100.0
b.config["caudal_continuo"] = True                                # curva caudal-apertura
nominal = lambda pct: b.caudal_nominal(b.tabla()[pct])
for pct in (40.0, 60.0, 100.0):                                   # la curva pasa por los puntos medidos
    apertura, k = b.elegir_apertura(nominal(pct))
    assert apertura == pct and abs(k / b.tabla()[pct] - 1) < 1e-9
anterior = 0.0
for i in range(41):                                               # creciente y continua en todo el tramo
    pedido = nominal(40.0) + (nominal(100.0) - nominal(40.0)) * i / 40
    apertura, k = b.elegir_apertura(pedido)
    assert 40.0 <= apertura <= 100.0 and apertura >= anterior
    assert abs(b.caudal_nominal(k) / pedido - 1) < 0.03, (pedido, apertura)   # da el caudal pedido (redondeo de 0,5 %)
    anterior = apertura
apertura, k = b.elegir_apertura(0.17)                             # entre 40 % y 60 %
assert 40.0 < apertura < 60.0 and b.tabla()[40.0] < k < b.tabla()[60.0]
assert b.k_en(30.0) is None and b.elegir_apertura(0.05)[0] == 40.0     # nunca se extiende fuera de lo calibrado
r = b.calibrar_previa({"apertura": 50, "inicial": 25, "salio": 5, "segundos": 30})
assert any("La curva actual preveía" in linea for linea in r)
b.config["aperturas"] = b.config["aperturas"] + [[50.0, b.tabla()[60.0] * 1.2]]   # medición incoherente
assert b.curva() is None and b.elegir_apertura(0.27)[0] in (50.0, 60.0)         # se desactiva sola la curva
b.borrar_apertura(50.0)
assert b.curva() is not None

ordenes = []
original = g.enlace.accion
g.enlace.accion = lambda modulo, accion, espera=None, **p: (ordenes.append((accion, p)), original(modulo, accion, espera=espera, **p))[1]
b.ejecutar("fijar_volumen", {"volumen": 25.0})
r = b.ejecutar("dosificar", {"volumen": 5.0, "caudal": nominal(40.0)})
assert r["apertura_pct"] == 40.0 and ordenes[-1][0] == "abrir_por" and ordenes[-1][1]["angulo"] == 36.0   # 40 % de 90°
assert abs(r["segundos"] - (50.0 + b.config["tiempo_muerto_s"])) < 0.05       # reproduce la medición de esa apertura
b.ejecutar("fijar_volumen", {"volumen": 25.0})
r = b.ejecutar("dosificar", {"volumen": 5.0, "caudal": 0.17})     # caudal intermedio: apertura intermedia
assert 40.0 < r["apertura_pct"] < 60.0 and 36.0 < ordenes[-1][1]["angulo"] < 54.0
assert 20.0 < r["segundos"] < 50.0                                # tarda entre lo de 60 % y lo de 40 %
b.ejecutar("fijar_volumen", {"volumen": 20.0})
assert abs(b.estado["disponible_ml"] - 20.0) < 1e-6
r = b.ejecutar("dosificar", {"volumen": 5.0})                     # sin caudal: del todo
assert r["apertura_pct"] == 100.0 and ordenes[-1][1]["angulo"] == 90.0
b.config["caudal_habitual"] = nominal(60.0)                       # caudal habitual del módulo
assert b.ejecutar("dosificar", {"volumen": 2.0})["apertura_pct"] == 60.0
b.config["caudal_habitual"] = None
try:
    b.ejecutar("dosificar", {"volumen": 2.0, "caudal": 0.001})    # más lento que cualquier apertura calibrada
    raise AssertionError("debía rechazarlo")
except ErrorModulo:
    pass
# una dosis lenta y grande se reparte en varias aperturas sin pasar el máximo del firmware
b.ejecutar("fijar_volumen", {"volumen": 25.0})
r = b.ejecutar("dosificar", {"volumen": 12.0, "caudal": nominal(40.0)})
assert r["aperturas"] > 1 and all(o[1]["ms"] <= 60000 for o in ordenes if o[0] == "abrir_por")
assert abs(b.estado["disponible_ml"] - 13.0) < 1e-6
g.enlace.accion = original


class EnlaceViejo:                                                # un ESP32 con el driver anterior
    simulado = False

    def accion(self, modulo, accion, espera=None, **p):
        if accion == "info":
            raise ErrorEnlace("accion desconocida: info")
        ordenes.append((accion, p))
        return {}
real, b.enlace, b._parcial_ok = b.enlace, EnlaceViejo(), None
antes = len(ordenes)
b.ejecutar("fijar_volumen", {"volumen": 25.0})
try:
    b.ejecutar("dosificar", {"volumen": 5.0, "caudal": 0.17})
    raise AssertionError("con el driver viejo no debe abrir en parte")
except ErrorModulo as error:
    assert "versión vieja" in str(error) and len(ordenes) == antes     # no llegó a abrir
assert b.ejecutar("dosificar", {"volumen": 1.0})["apertura_pct"] == 100.0   # del todo sí funciona
b.enlace = real
print("2b. apertura parcial:", b.descripcion_aperturas())

# 3. Sensor de pH: módulo nuevo, calibración con dos buffers y uso como objetivo automático ----
m = Motor(BASE / "b")
crear_ejemplo(m)
m.gestor.datos["conexion"]["aceleracion_simulacion"] = 200
exp = m.experimentos()[0]
exp.objetivo("ph_final").medicion, exp.objetivo("ph_final").modulo, exp.objetivo("ph_final").magnitud = "modulo", "sensor_ph", "ph"
m.gestor.conectar()
faltas = [c.texto for c in m.verificar(exp) if c.nivel == seguridad.ERROR]
assert any("pH final" in t for t in faltas), faltas            # sin el módulo: avisa y no arranca
print("3a. objetivo que pide un sensor que no está:", faltas[0])

m.gestor.agregar("ph", "sensor_ph", "Sensor de pH")
m.gestor.conectar()
sensor = m.gestor.modulos["sensor_ph"]
assert set(sensor.mediciones()) == {"ph"}
sensor.config["temperatura"] = "ds18b20"
assert set(sensor.mediciones()) == {"ph", "temperatura"}
sensor.config.update(mv_ph7=1500.0, mv_por_ph=-100.0)           # la "placa" simulada
sensor.calibrar_ejecutar({"ph_a": 7.0})
texto = sensor.calibrar_aplicar({"ph_b": 4.0})
assert sensor.config["calibrada"] and abs(sensor.config["mv_por_ph"] + 100.0) < 2 and abs(sensor.config["mv_ph7"] - 1500) < 3
m.gestor.enlace.ph_simulado = 9.3
assert abs(sensor.medir("ph") - 9.3) < 0.05
print("3b. calibración con buffers:", texto)

assert not [c.texto for c in m.verificar(exp) if c.nivel == seguridad.ERROR]
exp.registros = [{"modulo": "sensor_ph", "magnitud": "temperatura"}]
exp.max_experimentos = 1
m.iniciar(exp, demo=False)
limite = time.time() + 60
while m.ocupado() and time.time() < limite:
    s = m.solicitud
    if s is None:
        time.sleep(0.02)
        continue
    if s.titulo.startswith("Medición"):
        m.responder("ok", {s.campos[0]["clave"]: 55.0})
    elif s.titulo.startswith("¿Ocurrió"):
        m.responder("si")
    elif s.campos:
        m.responder("ok", {c["clave"]: c["valor"] for c in s.campos})
    else:
        m.responder(next(o["clave"] for o in s.opciones if o.get("principal")))
    while m.solicitud is s and m.ocupado():
        time.sleep(0.01)
assert m.estado == TERMINADO and not m.error_fin, m.motivo_fin
fila = m.historial.filas()[-1]
assert fila["estado"] == COMPLETADO and abs(fila["resultados"]["ph_final"] - 9.3) < 0.05
assert "sensor_ph.temperatura" in fila["registros"]
print(f"3c. campaña con pH automático: pH final = {fila['resultados']['ph_final']}, "
      f"temperatura anotada = {fila['registros']['sensor_ph.temperatura']} °C")
print("OK")
