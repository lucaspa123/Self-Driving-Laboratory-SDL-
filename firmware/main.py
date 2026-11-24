# Firmware del SDL para ESP32-S2 (MicroPython).
#
# Qué hace este archivo:
#   - Lee órdenes de la PC por el cable USB (una línea de texto JSON por orden).
#   - Las pasa al "driver" del módulo que corresponda (carpeta drivers/).
#   - Contesta con otra línea JSON.
#   - Cuida la seguridad: botón de parada, vigilancia de la PC ("latido"),
#     cierre automático de válvulas y apagado automático de motores.
#
# Para agregar un sensor o actuador nuevo NO hay que tocar este archivo:
# se agrega un archivo en drivers/ (ver drivers/_plantilla.py).
#
# Formato de los mensajes:
#   PC -> ESP32   {"id": 7, "c": "accion", "m": "bureta_1", "a": "abrir_por", "p": {"ms": 1200}}
#   ESP32 -> PC   {"id": 7, "ok": true, "r": {...}}     o    {"id": 7, "ok": false, "e": "motivo"}
#   ESP32 -> PC   {"ev": "parada", "motivo": "boton"}   (avisos espontáneos)

import sys
import os
import time
import select

try:
    import ujson as json
except ImportError:
    import json

from machine import Pin

VERSION = "1.3"

# Vigilante de hardware: si este programa se cuelga, reinicia el ESP32 (y al
# reiniciar no queda ningún actuador encendido). Dejarlo en False mientras se
# hacen pruebas con mpremote/REPL y pasarlo a True antes de usar reactivos.
USAR_VIGILANTE = False


class Sistema:
    """Estado general del equipo. Los drivers reciben este objeto."""

    def __init__(self):
        self.modulos = {}            # id -> [tipo, configuracion_en_texto, driver]
        self.parada = False          # parada de emergencia enclavada
        self.motivo = ""
        self.pin_parada = None       # botón normal cerrado a GND (con pull-up interno)
        self.pin_dc = None           # habilitación común de los puentes H
        self.latido_ms = 5000        # sin mensajes de la PC en este tiempo -> todo seguro
        self.ultimo_mensaje = time.ticks_ms()
        self.pc_presente = False
        self.tarea = None            # [id_de_la_orden, generador] de la orden larga en curso
        self.cuenta_boton = 0

    def boton_apretado(self):
        # Botón normal cerrado: en reposo une el pin con GND (lee 0).
        # Apretado, o con el cable cortado, el pin lee 1 -> parada.
        return self.pin_parada is not None and self.pin_parada.value() == 1


S = Sistema()

# --- comunicación -----------------------------------------------------------
_sondeo = select.poll()
_sondeo.register(sys.stdin, select.POLLIN)
_letras = []


def leer_lineas():
    """Devuelve las líneas completas que llegaron por USB (sin bloquear)."""
    lineas = []
    while _sondeo.poll(0):
        c = sys.stdin.read(1)
        if c == "\n":
            lineas.append("".join(_letras))
            _letras.clear()
        elif c != "\r":
            _letras.append(c)
            if len(_letras) > 1500:      # línea absurda: se descarta
                _letras.clear()
    return lineas


def enviar(mensaje):
    print(json.dumps(mensaje))


def responder(ident, ok, dato):
    if ident is None:
        return
    if ok:
        enviar({"id": ident, "ok": True, "r": dato if dato is not None else {}})
    else:
        enviar({"id": ident, "ok": False, "e": str(dato)})


# --- seguridad ----------------------------------------------------------------
def todo_seguro():
    """Cierra válvulas y apaga motores de todos los módulos."""
    for ficha in S.modulos.values():
        try:
            ficha[2].seguro()
        except Exception as error:
            enviar({"ev": "aviso", "texto": "no se pudo dejar seguro un modulo: " + str(error)})


def cancelar_tarea(motivo):
    """Corta la orden larga en curso (por ejemplo, una dosificación)."""
    if S.tarea is not None:
        ident, generador = S.tarea
        S.tarea = None
        try:
            generador.close()        # ejecuta los 'finally' del driver (cierra la válvula)
        except Exception:
            pass
        responder(ident, False, motivo)


def parada(motivo, avisar=True):
    """PARADA DE EMERGENCIA: corta todo y queda enclavada hasta que la PC rearme."""
    if S.parada:
        return
    S.parada = True
    S.motivo = motivo
    cancelar_tarea("parada: " + motivo)
    todo_seguro()
    if S.pin_dc is not None:
        S.pin_dc.value(0)
    if avisar:
        enviar({"ev": "parada", "motivo": motivo})


def vigilar(ahora):
    # 1. Botón físico (se pide que esté apretado 3 lecturas seguidas: evita falsos disparos)
    if S.boton_apretado():
        S.cuenta_boton += 1
        if S.cuenta_boton >= 3:
            parada("boton")
    else:
        S.cuenta_boton = 0
    # 2. Latido de la PC: si la PC se cuelga o se desconecta el cable, todo a seguro
    if S.pc_presente and time.ticks_diff(ahora, S.ultimo_mensaje) > S.latido_ms:
        S.pc_presente = False
        cancelar_tarea("sin latido de la PC")
        todo_seguro()
    # 3. Límites de tiempo propios de cada driver (válvula abierta, motor girando)
    for ident, ficha in S.modulos.items():
        aviso = ficha[2].tick(ahora)
        if aviso:
            enviar({"ev": "aviso", "texto": ident + ": " + aviso})


# --- drivers ------------------------------------------------------------------
def drivers_disponibles():
    nombres = []
    try:
        for archivo in os.listdir("drivers"):
            nombre = archivo.split(".")[0]
            if nombre and not nombre.startswith("_") and nombre not in nombres:
                nombres.append(nombre)
    except OSError:
        pass
    return nombres


def configurar_modulo(ident, tipo, cfg):
    """Crea (o reutiliza) el driver de un módulo con la configuración que manda la PC."""
    texto = json.dumps(cfg)
    actual = S.modulos.get(ident)
    if actual is not None:
        if actual[0] == tipo and actual[1] == texto:
            return                    # misma configuración: se conserva (el brazo no pierde su posición)
        try:
            actual[2].seguro()
        except Exception:
            pass
    paquete = __import__("drivers." + tipo)
    modulo = getattr(paquete, tipo)
    S.modulos[ident] = [tipo, texto, modulo.Driver(cfg, S)]


def ejecutar(orden, m):
    """Atiende una orden. Devuelve un dict, o un generador si la orden lleva tiempo."""
    if orden == "hola":
        return {"fw": VERSION, "drivers": drivers_disponibles(), "parada": S.parada}
    if orden == "sistema":
        pin = m.get("pin_parada")
        S.pin_parada = Pin(pin, Pin.IN, Pin.PULL_UP) if pin is not None else None
        pin = m.get("pin_habilitar_dc")
        S.pin_dc = Pin(pin, Pin.OUT, value=0 if S.parada else 1) if pin is not None else None
        S.latido_ms = int(float(m.get("tiempo_latido_s", 5)) * 1000)
        return {}
    if orden == "modulo":
        configurar_modulo(m["m"], m["tipo"], m.get("cfg") or {})
        return {}
    if orden == "estado":
        return {"parada": S.parada, "motivo": S.motivo, "boton": S.boton_apretado()}
    if orden == "seguro":
        todo_seguro()
        return {}
    if orden == "rearmar":
        if S.boton_apretado():
            raise ValueError("el boton de parada sigue apretado")
        S.parada = False
        S.motivo = ""
        if S.pin_dc is not None:
            S.pin_dc.value(1)
        return {}
    if orden == "medir":
        return {"valor": S.modulos[m["m"]][2].medir(m.get("q"))}
    if orden == "accion":
        if S.parada:
            raise ValueError("parada de emergencia activa: hay que rearmar")
        if m["m"] not in S.modulos:
            raise ValueError("modulo no configurado: " + str(m["m"]))
        return S.modulos[m["m"]][2].accion(m.get("a"), m.get("p") or {})
    raise ValueError("orden desconocida: " + str(orden))


def procesar(linea):
    try:
        m = json.loads(linea)
    except ValueError:
        return
    if not isinstance(m, dict):
        return
    S.ultimo_mensaje = time.ticks_ms()
    S.pc_presente = True
    orden = m.get("c")
    ident = m.get("id")
    if orden == "latido":
        return
    if orden == "parar":
        parada("pc", avisar=False)
        return
    try:
        resultado = ejecutar(orden, m)
    except KeyError as error:
        responder(ident, False, "falta o no existe: " + str(error))
        return
    except Exception as error:
        responder(ident, False, error)
        return
    if hasattr(resultado, "send"):            # es un generador: orden que lleva tiempo
        if S.tarea is not None:
            resultado.close()
            responder(ident, False, "ocupado: hay otra orden en curso")
        else:
            S.tarea = [ident, resultado]
    else:
        responder(ident, True, resultado)


def avanzar_tarea():
    """Hace avanzar un poquito la orden larga en curso y vuelve (así se sigue leyendo el USB)."""
    if S.tarea is None:
        return
    ident, generador = S.tarea
    try:
        next(generador)
    except StopIteration as fin:
        S.tarea = None
        responder(ident, True, fin.args[0] if fin.args else {})
    except Exception as error:
        S.tarea = None
        todo_seguro()
        responder(ident, False, error)


def vuelta():
    """Una vuelta del bucle principal."""
    for linea in leer_lineas():
        procesar(linea)
    vigilar(time.ticks_ms())
    avanzar_tarea()


def principal():
    vigilante = None
    if USAR_VIGILANTE:
        from machine import WDT
        vigilante = WDT(timeout=8000)
    enviar({"ev": "listo", "fw": VERSION})
    while True:
        vuelta()
        if S.tarea is None:
            time.sleep_ms(2)
        if vigilante is not None:
            vigilante.feed()


if __name__ == "__main__":
    principal()
