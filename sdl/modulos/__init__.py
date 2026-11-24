"""Registro de módulos y gestor de la instalación.

- tipos_disponibles() busca solo todas las clases de módulo de esta carpeta.
- GestorModulos lee config/modulos.yaml (qué hay instalado), abre la conexión
  con el ESP32 (o la simulación), le envía la configuración y prueba cada módulo.
"""
from __future__ import annotations

import importlib
import json
import pkgutil
import threading
from pathlib import Path

from ..comunicacion import Enlace, EnlaceSerie, EnlaceSimulado, ErrorEnlace, ParadaEmergencia
from ..modelos import escribir_yaml, leer_yaml
from .base import ErrorModulo, Modulo, NecesitaUsuario

__all__ = ["Modulo", "ErrorModulo", "NecesitaUsuario", "GestorModulos", "tipos_disponibles"]


def tipos_disponibles() -> dict[str, type[Modulo]]:
    """Devuelve {tipo: clase} con todos los módulos que hay en la carpeta."""
    tipos: dict[str, type[Modulo]] = {}
    for info in pkgutil.iter_modules(__path__):
        if info.name.startswith("_") or info.name == "base":
            continue
        paquete = importlib.import_module(f"{__name__}.{info.name}")
        for objeto in vars(paquete).values():
            if isinstance(objeto, type) and issubclass(objeto, Modulo) and objeto is not Modulo \
                    and objeto.TIPO:
                tipos[objeto.TIPO] = objeto
    return tipos


CONFIG_INICIAL = {
    "conexion": {"modo": "simulacion", "puerto": "", "aceleracion_simulacion": 20},
    "sistema": {"pin_parada": None, "pin_habilitar_dc": None, "tiempo_latido_s": 5},
    "modulos": [
        {"id": "bureta_1", "tipo": "bureta", "etiqueta": "Bureta 1", "activo": True,
         "config": {"pin_servo": 13}},
        {"id": "bureta_2", "tipo": "bureta", "etiqueta": "Bureta 2", "activo": True,
         "config": {"pin_servo": 14}},
        {"id": "bomba", "tipo": "bomba", "etiqueta": "Bomba peristáltica", "activo": True, "config": {}},
        {"id": "agitador", "tipo": "agitador", "etiqueta": "Agitador", "activo": True, "config": {}},
        {"id": "brazo", "tipo": "brazo", "etiqueta": "Brazo robótico", "activo": True, "config": {}},
        {"id": "termometro", "tipo": "temperatura", "etiqueta": "Sensor de temperatura",
         "activo": True, "config": {}},
        {"id": "camara", "tipo": "camara", "etiqueta": "Cámara", "activo": False, "config": {}},
    ],
}


class GestorModulos:
    def __init__(self, carpeta_config: Path, registrar=None):
        self.ruta = Path(carpeta_config) / "modulos.yaml"
        self.ruta_estado = Path(carpeta_config) / "estado_modulos.json"
        self.registrar = registrar or (lambda texto: None)
        self.al_evento = None                       # lo conecta el motor
        self.tipos = tipos_disponibles()
        self.datos = leer_yaml(self.ruta)
        if not self.datos:
            self.datos = json.loads(json.dumps(CONFIG_INICIAL))
            escribir_yaml(self.ruta, self.datos)
        self.estados: dict = {}
        if self.ruta_estado.exists():
            try:
                self.estados = json.loads(self.ruta_estado.read_text(encoding="utf-8"))
            except ValueError:
                self.estados = {}
        self._candado = threading.Lock()
        self.enlace: Enlace | None = None
        self.modulos: dict[str, Modulo] = {}
        self.pruebas: dict[str, tuple[bool, str]] = {}
        self.firmware: dict = {}
        self.instanciar()

    # --- archivos ---------------------------------------------------------
    def guardar(self) -> None:
        for ficha in self.datos["modulos"]:
            modulo = self.modulos.get(ficha["id"])
            if modulo is not None:                   # guarda solo lo que difiere del valor de fábrica
                ficha["config"] = {k: v for k, v in modulo.config.items()
                                   if k not in modulo.CONFIG or modulo.CONFIG[k].get("valor") != v}
        escribir_yaml(self.ruta, self.datos)

    def guardar_estados(self) -> None:
        with self._candado:
            tmp = self.ruta_estado.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.estados, ensure_ascii=False, indent=1), encoding="utf-8")
            tmp.replace(self.ruta_estado)

    # --- instancias -------------------------------------------------------
    def ficha(self, ident: str) -> dict | None:
        return next((m for m in self.datos["modulos"] if m["id"] == ident), None)

    def instanciar(self) -> None:
        """Crea los objetos de los módulos activos."""
        self.modulos = {}
        for ficha in self.datos["modulos"]:
            clase = self.tipos.get(ficha.get("tipo"))
            if clase is None or not ficha.get("activo", True):
                continue
            estado = self.estados.setdefault(ficha["id"], {})
            self.modulos[ficha["id"]] = clase(ficha["id"], ficha.get("etiqueta", ""),
                                             ficha.get("config") or {}, self.enlace, estado,
                                             self.guardar_estados)

    def agregar(self, tipo: str, ident: str, etiqueta: str) -> None:
        if self.ficha(ident):
            raise ValueError(f"Ya existe un módulo con el identificador '{ident}'.")
        if tipo not in self.tipos:
            raise ValueError(f"No existe el tipo de módulo '{tipo}'.")
        self.datos["modulos"].append({"id": ident, "tipo": tipo, "etiqueta": etiqueta,
                                      "activo": True, "config": {}})
        escribir_yaml(self.ruta, self.datos)
        self.instanciar()

    def quitar(self, ident: str) -> None:
        self.datos["modulos"] = [m for m in self.datos["modulos"] if m["id"] != ident]
        escribir_yaml(self.ruta, self.datos)
        self.instanciar()

    def activar(self, ident: str, activo: bool) -> None:
        self.guardar()
        self.ficha(ident)["activo"] = bool(activo)
        escribir_yaml(self.ruta, self.datos)
        self.instanciar()
        self.pruebas.pop(ident, None)

    # --- conexión -----------------------------------------------------------
    def conectado(self) -> bool:
        return self.enlace is not None and self.enlace.conectado()

    def desconectar(self) -> None:
        if self.enlace is not None:
            try:
                self.todos_seguros()
            except Exception:
                pass
            self.enlace.cerrar()
        self.enlace = None
        self.pruebas = {}
        for modulo in self.modulos.values():
            modulo.enlace = None

    def conectar(self) -> tuple[bool, str]:
        """Abre el enlace, configura el ESP32 y prueba cada módulo."""
        self.desconectar()
        conexion = self.datos.get("conexion", {})
        try:
            if conexion.get("modo") == "esp32":
                if not conexion.get("puerto"):
                    return False, "Elija el puerto USB del ESP32."
                enlace: Enlace = EnlaceSerie(conexion["puerto"])
            else:
                enlace = EnlaceSimulado(conexion.get("aceleracion_simulacion", 20))
        except Exception as error:
            return False, f"No se pudo abrir el puerto: {error}"
        enlace.registro = self.registrar
        enlace.al_evento = lambda evento: self.al_evento and self.al_evento(evento)
        # Al abrir el puerto el ESP32 suele reiniciarse: se insiste unos segundos.
        ultimo_error = None
        for _ in range(5):
            try:
                self.firmware = enlace.enviar("hola", espera=2)
                ultimo_error = None
                break
            except Exception as error:
                ultimo_error = error
        if ultimo_error is not None:
            enlace.cerrar()
            return False, f"El ESP32 no respondió. ¿Está cargado el firmware? ({ultimo_error})"
        self.enlace = enlace
        self.instanciar()
        self.pruebas = {}
        drivers = set(self.firmware.get("drivers") or [])
        try:
            enlace.enviar("sistema", espera=5, **(self.datos.get("sistema") or {}))
        except Exception as error:
            return False, f"El ESP32 rechazó la configuración general: {error}"
        # Un mensaje por módulo: son cortos y el ESP32 los recibe sin perder datos.
        for ident, modulo in self.modulos.items():
            if not modulo.USA_ESP32:
                continue
            driver = getattr(modulo, "DRIVER", "") or modulo.TIPO
            if driver not in drivers:
                self.pruebas[ident] = (False, f"El ESP32 no tiene el driver «{driver}» "
                                              f"(falta copiar firmware/drivers/{driver}.py).")
                continue
            try:
                enlace.enviar("modulo", espera=5, m=ident, tipo=driver, cfg=modulo.config_firmware() or {})
            except Exception as error:
                self.pruebas[ident] = (False, f"El ESP32 no pudo iniciar el módulo: {error}")
        self.probar_todos()
        fallas = [i for i, (ok, _) in self.pruebas.items() if not ok]
        if fallas:
            return True, f"Conectado. {len(fallas)} módulo(s) no respondieron: {', '.join(fallas)}."
        return True, f"Conectado: {enlace.descripcion}. Todos los módulos responden."

    def probar_todos(self) -> None:
        for ident, modulo in self.modulos.items():
            if ident in self.pruebas and not self.pruebas[ident][0]:
                continue                       # ya falló en la configuración
            self.probar(ident)

    def probar(self, ident: str) -> tuple[bool, str]:
        modulo = self.modulos[ident]
        try:
            resultado = modulo.autotest()
        except (ErrorEnlace, ErrorModulo, ParadaEmergencia) as error:
            resultado = (False, str(error))
        except Exception as error:               # un módulo defectuoso no debe tumbar el programa
            resultado = (False, f"Error inesperado: {error}")
        self.pruebas[ident] = resultado
        return resultado

    def disponible(self, ident: str) -> bool:
        """Activo, conectado y con el autotest aprobado."""
        return ident in self.modulos and self.pruebas.get(ident, (False, ""))[0]

    def todos_seguros(self) -> list[str]:
        """Pone cada módulo en estado seguro. Devuelve los errores encontrados."""
        errores = []
        if self.enlace is None:
            return errores
        for ident, modulo in self.modulos.items():
            if modulo.USA_ESP32 and not self.pruebas.get(ident, (False, ""))[0]:
                continue
            try:
                modulo.estado_seguro()
            except Exception as error:
                errores.append(f"{modulo.etiqueta}: {error}")
        try:
            self.enlace.enviar("seguro", espera=3)
        except Exception as error:
            errores.append(str(error))
        return errores

    def conflictos_de_pines(self) -> list[str]:
        """Pines (GPIO) asignados a más de una cosa entre los módulos activos."""
        usos: dict[int, list[str]] = {}

        def anotar(valor, quien: str) -> None:
            if isinstance(valor, bool):
                return
            if isinstance(valor, int):
                usos.setdefault(valor, []).append(quien)
            elif isinstance(valor, (list, tuple)):
                for x in valor:
                    anotar(x, quien)
        for modulo in self.modulos.values():
            if not modulo.USA_ESP32:
                continue
            for clave, valor in modulo.config.items():
                if clave.startswith("pin"):
                    anotar(valor, modulo.etiqueta)
        for clave, valor in (self.datos.get("sistema") or {}).items():
            if clave.startswith("pin"):
                anotar(valor, "Seguridad")
        return [f"El pin GPIO {pin} está asignado a más de una cosa: {', '.join(quienes)}."
                for pin, quienes in sorted(usos.items()) if len(quienes) > 1]

    # --- catálogo para el asistente de experimentos ------------------------
    def catalogo(self) -> dict:
        """Todo lo que la instalación actual puede ajustar, hacer y medir."""
        optimizables, acciones, mediciones, dosificadores = [], [], [], []
        for ident, modulo in self.modulos.items():
            for accion, d in modulo.acciones().items():
                if not d.get("en_protocolo"):
                    continue
                acciones.append({"modulo": ident, "accion": accion,
                                 "etiqueta": f"{modulo.etiqueta}: {d['etiqueta']}",
                                 "parametros": d.get("parametros") or {}})
                if d.get("usa_reactivo") and ident not in dosificadores:
                    dosificadores.append(ident)
                for parametro, dp in (d.get("parametros") or {}).items():
                    if dp.get("optimizable"):
                        optimizables.append({
                            "modulo": ident, "accion": accion, "parametro": parametro,
                            "etiqueta": f"{modulo.etiqueta}: {dp['etiqueta'].lower()} "
                                        f"({d['etiqueta'].lower()})",
                            "unidad": dp.get("unidad", ""), "min": dp.get("min"),
                            "max": dp.get("max"), "paso": dp.get("paso", 0)})
            for magnitud, d in modulo.mediciones().items():
                mediciones.append({"modulo": ident, "magnitud": magnitud,
                                   "etiqueta": f"{modulo.etiqueta}: {d['etiqueta'].lower()}",
                                   "unidad": d.get("unidad", "")})
        return {"optimizables": optimizables, "acciones": acciones, "mediciones": mediciones,
                "dosificadores": dosificadores}
