"""Prueba el programa completo en simulación: validación, campaña, seguridad y recuperación."""
import shutil
import tempfile
import sys
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from sdl import seguridad                                             # noqa: E402
from sdl.ejemplo import crear_ejemplo, experimento_ejemplo             # noqa: E402
from sdl.historial import ABORTADO, COMPLETADO, EN_CURSO, FALLIDO, Historial   # noqa: E402
from sdl.motor import PARADA, TERMINADO, Motor                         # noqa: E402
from sdl.restricciones import ErrorRestriccion, compilar               # noqa: E402

BASE = Path(tempfile.gettempdir()) / "sdl_prueba_motor"


def motor_nuevo() -> Motor:
    shutil.rmtree(BASE, ignore_errors=True)
    m = Motor(BASE)
    crear_ejemplo(m)
    m.gestor.datos["conexion"]["aceleracion_simulacion"] = 200
    ok, mensaje = m.gestor.conectar()
    assert ok, mensaje
    return m


def esperar(condicion, segundos=60, que=""):
    limite = time.time() + segundos
    while time.time() < limite:
        if condicion():
            return
        time.sleep(0.05)
    raise AssertionError(f"no ocurrió a tiempo: {que}")


def errores(m, exp) -> list[str]:
    return [c.texto for c in m.verificar(exp) if c.nivel == seguridad.ERROR]


# 1. Validación contra los módulos disponibles -----------------------------------------
m = motor_nuevo()
exp = m.experimentos()[0]
assert not errores(m, exp), errores(m, exp)

m.gestor.activar("bureta_1", False)                       # se "desenchufa" la bureta
faltas = errores(m, exp)
assert any("Volumen de NaOH" in t and "bureta_1" in t for t in faltas), faltas
try:
    m.iniciar(exp, demo=True)
    esperar(lambda: not m.ocupado(), que="rechazo de la campaña")
    assert m.estado == TERMINADO and m.error_fin and m.hechos == 0, (m.estado, m.motivo_fin)
finally:
    m.cerrar_campana()
m.gestor.activar("bureta_1", True)
m.gestor.conectar()
print("1a. módulo desactivado: avisa y no arranca ->", faltas[0])

exp.variable("vol_naoh").maximo = 40.0                    # la bureta es de 25 mL
faltas = errores(m, exp)
assert any("excede" in t for t in faltas), faltas
exp.variable("vol_naoh").maximo = 20.0
print("1b. límite fuera de lo que admite el módulo ->", faltas[0])

vacio = experimento_ejemplo()
vacio.id, vacio.reaccion = "sin_historial", "sin_historial"
assert any("historial" in t.lower() for t in errores(m, vacio))
print("1c. sin experimentos previos: no arranca")

for mala in ("__import__('os').system('echo hola')", "vol_fe.real < 3", "vol_fe + 2", "otra_cosa < 3"):
    try:
        compilar(mala, ["vol_fe", "vol_naoh"])
        raise AssertionError(f"debía rechazar: {mala}")
    except ErrorRestriccion:
        pass
assert compilar("vol_fe + vol_naoh <= 45", ["vol_fe", "vol_naoh"])({"vol_fe": 20, "vol_naoh": 20})
print("1d. las condiciones entre variables no ejecutan código")

# 2. Campaña completa en demostración -------------------------------------------------------
exp.max_experimentos = 7
m.iniciar(exp, demo=True)
esperar(lambda: not m.ocupado(), 180, "fin de la campaña")
assert m.estado == TERMINADO and not m.error_fin, m.motivo_fin
filas = m.historial.filas()
nuevas = [f for f in filas if f["campana"] == m.campana]
assert len(nuevas) == 7 and all(f["estado"] in (COMPLETADO, FALLIDO) for f in nuevas)
for f in nuevas:                                          # toda propuesta respetó límites y condiciones
    assert not seguridad.comprobar_propuesta(exp, m.gestor, f["variables"], m.seguridad), f
    assert f["variables"]["vol_fe"] + f["variables"]["vol_naoh"] <= 45 + 1e-9
assert m.ruta_informe is not None and m.ruta_informe.stat().st_size > 20000
assert m.gestor.modulos["agitador"].estado.get("velocidad", 0) == 0
print(f"2.  campaña de 7 experimentos: {m.motivo_fin} Informe: {m.ruta_informe.name}")
m.cerrar_campana()

# 2b. Un agitador NEMA17 se agrega como cualquier módulo y aparece en el catálogo del asistente
m.gestor.agregar("agitador_nema17", "agitador_paso", "Agitador NEMA17")
ok, texto = m.gestor.conectar()                    # como en la pantalla: «Volver a conectar»
assert ok and m.gestor.pruebas["agitador_paso"][0], (ok, texto, m.gestor.pruebas)
nema = m.gestor.modulos["agitador_paso"]
nema.ejecutar("agitar", {"velocidad": 100, "segundos": 2})
assert nema.estado.get("velocidad", 0) == 0
catalogo = m.gestor.catalogo()
assert any(o["modulo"] == "agitador_paso" and o["parametro"] == "velocidad" for o in catalogo["optimizables"])
assert not m.gestor.conflictos_de_pines()
m.gestor.quitar("agitador_paso")
assert "agitador_paso" not in m.gestor.modulos
print("2b. agitador NEMA17: se agrega, agita y aparece como variable optimizable")

# 3. Respuestas del usuario: aprobación, mediciones y «la reacción no ocurrió» ----------------
exp.max_experimentos = 2
m.iniciar(exp, demo=False)
respuestas = {"Preparación": ("ok", {"disponible": 25.0}), "propuesta": ("aprobar", {}), "Acción manual": ("ok", {}),
              "Ajuste manual": ("ok", {}), "Hace falta": ("ok", {"disponible": 25.0})}
medidos = 0
while m.ocupado():
    s = m.solicitud
    if s is None:
        time.sleep(0.02)
        continue
    if s.titulo.startswith("Medición"):
        medidos += 1
        if medidos <= 2:                                   # primer experimento: se mide todo
            m.responder("ok", {s.campos[0]["clave"]: 70.0 if "Rendimiento" in s.titulo else 9.9})
        else:                                              # segundo: no ocurrió
            m.responder("no")
    elif "cumplieron" in s.titulo:
        m.responder("seguir")
    else:
        opcion, valores = next(v for k, v in respuestas.items() if k in s.titulo)
        m.responder(opcion, valores)
    esperar(lambda: m.solicitud is not s, 30, "que avance tras responder")
ultimas = m.historial.filas()[-2:]
assert ultimas[0]["estado"] == COMPLETADO and ultimas[0]["resultados"] == {"rendimiento": 70.0, "ph_final": 9.9}
assert ultimas[1]["estado"] == FALLIDO and not ultimas[1]["resultados"]
print("3.  respuestas manuales: un experimento completado y uno marcado «sin reacción»")
m.cerrar_campana()

# 4. Parada de emergencia a mitad de un experimento ----------------------------------------
m.gestor.enlace.aceleracion = 2                           # lento, para cortarlo a mitad de camino
exp.max_experimentos = 5
m.iniciar(exp, demo=True)
esperar(lambda: m.fila_actual is not None and m.paso_actual >= 4, 60, "que empiece a dosificar")
n = m.fila_actual
m.parada("prueba")
esperar(lambda: not m.ocupado(), 10, "que se detenga")
assert m.estado == PARADA
assert m.historial.fila(n)["estado"] == ABORTADO
try:
    m.iniciar(exp, demo=True)
    raise AssertionError("no debe iniciar con la parada activa")
except RuntimeError:
    pass
ok, mensaje = m.rearmar()
assert ok, mensaje
usables, _ = m.historial.usables(exp)
assert n not in [f["n"] for f in usables]
print("4.  parada de emergencia: corta, anota el experimento como abortado y exige rearmar")

# 5. Corte del programa a mitad de un experimento --------------------------------------------
ruta = m.historial.ruta
m.historial.agregar({v.nombre: v.minimo for v in exp.variables}, estado=EN_CURSO, origen="optimizacion")
recuperado = Historial(ruta)
assert recuperado.cerrar_interrumpidos() == 1 and recuperado.filas()[-1]["estado"] == ABORTADO
print("5.  corte de energía: lo que quedó a medias no se cuenta como válido")
print("OK")
