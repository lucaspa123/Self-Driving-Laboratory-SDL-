"""Comunicación entre la PC y el ESP32 por USB.

Protocolo: una línea de texto JSON por mensaje.
    PC  -> ESP32   {"id": 7, "c": "accion", "m": "bureta_1", "a": "abrir_por", "p": {"ms": 1200}}
                   órdenes ("c"): hola, sistema, modulo, estado, seguro, rearmar, medir, accion,
                   latido (sin respuesta) y parar (sin respuesta)
    ESP32 -> PC    {"id": 7, "ok": true, "r": {...}}      o    {"id": 7, "ok": false, "e": "motivo"}
    ESP32 -> PC    {"ev": "parada", "motivo": "boton"}    (eventos espontáneos)

Además la PC envía un "latido" cada segundo. Si el ESP32 deja de recibirlo,
pasa solo a estado seguro (ver firmware/main.py).

EnlaceSimulado responde como lo haría el ESP32, pero sin hardware: sirve para
probar todo el programa en la PC.
"""
from __future__ import annotations

import json
import queue
import random
import threading
import time


class ErrorEnlace(Exception):
    """El ESP32 no respondió o rechazó la orden."""


class ParadaEmergencia(Exception):
    """Se activó la parada de emergencia mientras se ejecutaba una orden."""


class Enlace:
    """Interfaz común de los enlaces (serie y simulado)."""

    simulado = False
    descripcion = "Sin conexión"

    def __init__(self):
        self.al_evento = None          # función(dict) llamada con eventos del ESP32
        self.registro = None           # función(str) para el registro de auditoría

    def conectado(self) -> bool:
        return False

    def enviar(self, comando: str, espera: float = 3.0, **datos) -> dict:
        raise NotImplementedError

    def accion(self, modulo: str, accion: str, espera: float = 5.0, **p) -> dict:
        return self.enviar("accion", espera=espera, m=modulo, a=accion, p=p)

    def medir(self, modulo: str, magnitud: str) -> float:
        return self.enviar("medir", m=modulo, q=magnitud)["valor"]

    def parar(self) -> None:
        """Parada de emergencia: corta la orden en curso y deja todo seguro."""

    def cerrar(self) -> None:
        pass

    def _log(self, texto: str) -> None:
        if self.registro:
            self.registro(texto)


# ---------------------------------------------------------------------------
class EnlaceSerie(Enlace):
    """Enlace real por puerto serie (USB) usando pyserial."""

    def __init__(self, puerto: str, baudios: int = 115200):
        super().__init__()
        import serial  # se importa acá para que la simulación no lo necesite
        self.descripcion = f"ESP32 en {puerto}"
        self._serie = serial.Serial(puerto, baudios, timeout=0.2, write_timeout=2)
        self._escritura = threading.Lock()
        self._orden = threading.Lock()         # una orden a la vez
        self._respuestas: "queue.Queue[dict]" = queue.Queue()
        self._id = 0
        self._vivo = True
        self._ultimo_ok = time.time()
        threading.Thread(target=self._leer, daemon=True).start()
        threading.Thread(target=self._latir, daemon=True).start()

    def conectado(self) -> bool:
        return self._vivo and self._serie.is_open

    def _escribir(self, mensaje: dict) -> None:
        linea = (json.dumps(mensaje, separators=(",", ":")) + "\n").encode()
        with self._escritura:
            # En tandas cortas: la memoria de recepción del ESP32 es chica (~250 bytes).
            for i in range(0, len(linea), 96):
                self._serie.write(linea[i:i + 96])
                self._serie.flush()
                if i + 96 < len(linea):
                    time.sleep(0.02)

    def _leer(self) -> None:
        pendiente = bytearray()                     # lo recibido que todavía no forma una línea completa
        while self._vivo:
            try:
                datos = self._serie.read(self._serie.in_waiting or 1)
            except Exception as error:
                self._vivo = False
                self._log(f"Se perdió la conexión con el ESP32: {error}")
                if self.al_evento:
                    self.al_evento({"ev": "desconexion", "motivo": str(error)})
                return
            if not datos:
                continue
            pendiente.extend(datos)
            while b"\n" in pendiente:
                cruda, _, resto = bytes(pendiente).partition(b"\n")
                pendiente = bytearray(resto)
                self._linea(cruda.decode("utf-8", "replace").strip())
            if len(pendiente) > 20000:
                pendiente.clear()

    def _linea(self, texto: str) -> None:
        if not texto.startswith("{"):
            if texto:
                self._log(f"ESP32> {texto}")           # mensajes sueltos (print del firmware)
            return
        try:
            mensaje = json.loads(texto)
        except ValueError:
            return
        if "ev" in mensaje:
            if mensaje.get("ev") != "listo":
                self._log(f"Evento del ESP32: {mensaje}")
            if self.al_evento:
                self.al_evento(mensaje)
        else:
            self._respuestas.put(mensaje)

    def _latir(self) -> None:
        while self._vivo:
            try:
                self._escribir({"c": "latido"})
            except Exception:
                pass
            time.sleep(1.0)

    def enviar(self, comando: str, espera: float = 3.0, **datos) -> dict:
        if not self.conectado():
            raise ErrorEnlace("No hay conexión con el ESP32.")
        with self._orden:
            self._id += 1
            ident = self._id
            while not self._respuestas.empty():          # descarta respuestas viejas
                self._respuestas.get_nowait()
            self._escribir({"id": ident, "c": comando, **datos})
            limite = time.time() + espera
            while True:
                restante = limite - time.time()
                if restante <= 0:
                    raise ErrorEnlace(f"El ESP32 no respondió a '{comando}' en {espera:.0f} s.")
                try:
                    r = self._respuestas.get(timeout=min(restante, 0.5))
                except queue.Empty:
                    if not self.conectado():
                        raise ErrorEnlace("Se perdió la conexión con el ESP32.")
                    continue
                if r.get("id") != ident:
                    continue
                if r.get("ok"):
                    return r.get("r") or {}
                error = str(r.get("e", "error desconocido"))
                if error.startswith("parada"):
                    raise ParadaEmergencia(error)
                raise ErrorEnlace(error)

    def parar(self) -> None:
        try:
            self._escribir({"c": "parar"})               # sin esperar turno: es urgente
        except Exception:
            pass

    def cerrar(self) -> None:
        self._vivo = False
        try:
            self._serie.close()
        except Exception:
            pass


def puertos_disponibles() -> list[str]:
    try:
        from serial.tools import list_ports
        return [p.device for p in list_ports.comports()]
    except Exception:
        return []


# ---------------------------------------------------------------------------
class EnlaceSimulado(Enlace):
    """Imita al ESP32. Las órdenes largas duran lo mismo, dividido por 'aceleracion'."""

    simulado = True

    def __init__(self, aceleracion: float = 20.0):
        super().__init__()
        self.aceleracion = max(1.0, float(aceleracion))
        self.descripcion = "Simulación (sin hardware)"
        self._parada = threading.Event()
        self._enclavada = False
        self._modulos: dict[str, dict] = {}
        self._pasos: dict[str, list[int]] = {}
        self._ref: dict[str, bool] = {}

    def conectado(self) -> bool:
        return True

    def enviar(self, comando: str, espera: float = 3.0, **d) -> dict:
        if comando == "hola":
            return {"fw": "simulado", "drivers": ["servo_valvula", "servo_continuo", "motor_dc", "motor_paso", "brazo", "ds18b20", "sensor_ph"],
                    "parada": self._enclavada}
        if comando == "sistema":
            return {}
        if comando == "modulo":
            self._modulos[d["m"]] = {"id": d["m"], "tipo": d.get("tipo"), "cfg": d.get("cfg") or {}}
            return {}
        if comando == "estado":
            return {"parada": self._enclavada, "boton": False, "motivo": ""}
        if comando == "seguro":
            return {}
        if comando == "rearmar":
            self._enclavada = False
            self._parada.clear()
            return {}
        if self._enclavada:
            raise ErrorEnlace("parada de emergencia activa: hay que rearmar")
        if comando == "medir":
            return {"valor": self._medir(d.get("m"), d.get("q"))}
        if comando == "accion":
            return self._accion(d.get("m"), d.get("a"), d.get("p") or {})
        raise ErrorEnlace(f"orden desconocida: {comando}")

    def _dormir(self, segundos: float) -> None:
        fin = time.time() + segundos / self.aceleracion
        while time.time() < fin:
            if self._parada.is_set():
                self._enclavada = True
                raise ParadaEmergencia("parada: orden interrumpida")
            time.sleep(0.02)

    def _accion(self, modulo: str, accion: str, p: dict) -> dict:
        if modulo not in self._modulos:
            raise ErrorEnlace(f"módulo no configurado: {modulo}")
        tipo = self._modulos[modulo].get("tipo")
        if "ms" in p:
            self._dormir(float(p["ms"]) / 1000.0)
        if tipo == "brazo":
            pasos = self._pasos.setdefault(modulo, [0, 0, 0, 0])
            if accion == "mover":
                if not self._ref.get(modulo):
                    raise ErrorEnlace("el brazo no tiene origen fijado")
                n = int(p["pasos"])
                self._dormir(abs(n) / max(1.0, float(p.get("vel", 1000))))
                pasos[int(p["eje"])] += n
                return {"pasos": pasos[int(p["eje"])]}
            if accion == "fijar_origen":
                self._pasos[modulo] = [int(x) for x in p["pasos"]]
                self._ref[modulo] = True
                return {}
            if accion == "estado":
                return {"ref": bool(self._ref.get(modulo)), "pasos": list(pasos)}
            if accion == "pinza":
                self._dormir(0.5)
        return {}

    def _medir(self, modulo: str, magnitud: str) -> float:
        if magnitud == "temperatura":
            return round(25.0 + random.gauss(0, 0.15), 2)
        return round(random.random(), 3)

    def parar(self) -> None:
        self._enclavada = True
        self._parada.set()
