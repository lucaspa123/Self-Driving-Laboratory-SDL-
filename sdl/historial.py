"""Historial de experimentos de una reacción.

Un archivo CSV por reacción (datos/reacciones/<reaccion>/historial.csv), que
también se puede abrir con Excel o LibreOffice. Cada fila es un experimento:

    n ; fecha ; campana ; origen ; estado ; var:<variable>... ; obj:<objetivo>... ; reg:<registro>... ; notas

estado:  completado  la reacción ocurrió y se midió
         fallido     el químico marcó que la reacción NO ocurrió (se penaliza)
         en_curso    se está ejecutando (si el programa se corta, queda así)
         abortado    se interrumpió (parada de emergencia, corte); no se usa
         descartado  el químico lo anuló; no se usa

Cada cambio reescribe el archivo completo de forma atómica (temporal + reemplazo),
así un corte de luz no lo deja a medio escribir.
"""
from __future__ import annotations

import csv
import io
import threading
import time
from datetime import datetime
from pathlib import Path

COMPLETADO, FALLIDO, EN_CURSO, ABORTADO, DESCARTADO = (
    "completado", "fallido", "en_curso", "abortado", "descartado")
USABLES = (COMPLETADO, FALLIDO)
FIJAS = ["n", "fecha", "campana", "origen", "estado"]


def a_numero(texto):
    """Convierte texto a número aceptando coma decimal. Vacío -> None."""
    if texto is None:
        return None
    if isinstance(texto, (int, float)):
        return float(texto)
    texto = str(texto).strip().replace(",", ".")
    if not texto:
        return None
    try:
        return float(texto)
    except ValueError:
        return None


class Historial:
    def __init__(self, ruta: Path):
        self.ruta = Path(ruta)
        self._candado = threading.RLock()
        self._filas: list[dict] = []
        self._leer()

    # --- lectura / escritura ---------------------------------------------
    @staticmethod
    def _interpretar(texto: str) -> list[dict]:
        texto = texto.lstrip("﻿")
        if not texto.strip():
            return []
        separador = ";" if texto.splitlines()[0].count(";") >= texto.splitlines()[0].count(",") else ","
        filas = []
        for cruda in csv.DictReader(io.StringIO(texto), delimiter=separador):
            fila = {"n": 0, "fecha": "", "campana": "", "origen": "previo", "estado": COMPLETADO,
                    "variables": {}, "resultados": {}, "registros": {}, "notas": ""}
            for clave, valor in cruda.items():
                if clave is None:
                    continue
                clave = clave.strip()
                if clave.startswith("var:"):
                    numero = a_numero(valor)
                    if numero is not None:
                        fila["variables"][clave[4:]] = numero
                elif clave.startswith("obj:"):
                    numero = a_numero(valor)
                    if numero is not None:
                        fila["resultados"][clave[4:]] = numero
                elif clave.startswith("reg:"):
                    numero = a_numero(valor)
                    if numero is not None:
                        fila["registros"][clave[4:]] = numero
                elif clave == "n":
                    fila["n"] = int(a_numero(valor) or 0)
                elif clave in fila and valor not in (None, ""):
                    fila[clave] = valor.strip()
            filas.append(fila)
        return filas

    def _leer(self) -> None:
        if self.ruta.exists():
            self._filas = self._interpretar(self.ruta.read_text(encoding="utf-8-sig"))
        else:
            self._filas = []
        for i, fila in enumerate(self._filas, 1):
            if not fila["n"]:
                fila["n"] = i

    def texto_csv(self, filas: list[dict] | None = None, decimal: str = ".") -> str:
        """CSV del historial. Con decimal="," queda listo para abrir con Excel en español."""
        filas = self._filas if filas is None else filas
        _fmt = lambda valor: _formato(valor).replace(".", decimal)
        variables = sorted({k for f in filas for k in f["variables"]})
        objetivos = sorted({k for f in filas for k in f["resultados"]})
        registros = sorted({k for f in filas for k in f.get("registros", {})})
        salida = io.StringIO()
        escritor = csv.writer(salida, delimiter=";", lineterminator="\n")
        escritor.writerow(FIJAS + [f"var:{v}" for v in variables] + [f"obj:{o}" for o in objetivos]
                          + [f"reg:{r}" for r in registros] + ["notas"])
        for f in filas:
            escritor.writerow([f[c] for c in FIJAS]
                              + [_fmt(f["variables"].get(v)) for v in variables]
                              + [_fmt(f["resultados"].get(o)) for o in objetivos]
                              + [_fmt(f.get("registros", {}).get(r)) for r in registros]
                              + [f.get("notas", "")])
        return salida.getvalue()

    def _guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        tmp.write_text(self.texto_csv(), encoding="utf-8-sig")
        for intento in range(10):
            try:
                tmp.replace(self.ruta)
                return
            except PermissionError:                 # en Windows: el archivo está abierto en Excel
                time.sleep(0.5)
        raise OSError(f"No se pudo guardar el historial: cierre el archivo {self.ruta.name} "
                      f"si lo tiene abierto en otro programa (por ejemplo Excel).")

    # --- operaciones --------------------------------------------------------
    def filas(self) -> list[dict]:
        with self._candado:
            return [dict(f, variables=dict(f["variables"]), resultados=dict(f["resultados"]),
                         registros=dict(f.get("registros", {}))) for f in self._filas]

    def fila(self, n: int) -> dict | None:
        return next((f for f in self.filas() if f["n"] == n), None)

    def agregar(self, variables: dict, resultados: dict | None = None, estado: str = COMPLETADO,
                origen: str = "previo", campana: str = "", notas: str = "") -> int:
        with self._candado:
            n = max((f["n"] for f in self._filas), default=0) + 1
            self._filas.append({
                "n": n, "fecha": datetime.now().strftime("%Y-%m-%d %H:%M"), "campana": campana,
                "origen": origen, "estado": estado,
                "variables": {k: float(v) for k, v in variables.items()},
                "resultados": {k: float(v) for k, v in (resultados or {}).items() if v is not None},
                "registros": {}, "notas": notas})
            self._guardar()
            return n

    def actualizar(self, n: int, **cambios) -> None:
        with self._candado:
            for f in self._filas:
                if f["n"] == n:
                    for clave, valor in cambios.items():
                        if clave in ("variables", "resultados", "registros"):
                            f.setdefault(clave, {}).update({k: float(v) for k, v in valor.items() if v is not None})
                        else:
                            f[clave] = valor
            self._guardar()

    def cerrar_interrumpidos(self) -> int:
        """Al arrancar: lo que quedó 'en_curso' por un corte pasa a 'abortado'."""
        with self._candado:
            pendientes = [f for f in self._filas if f["estado"] == EN_CURSO]
            for f in pendientes:
                f["estado"] = ABORTADO
                f["notas"] = (f.get("notas", "") + " Interrumpido por cierre del programa.").strip()
            if pendientes:
                self._guardar()
            return len(pendientes)

    def importar(self, texto: str, campana: str = "") -> int:
        """Agrega filas desde otro CSV (mismas columnas var:/obj:)."""
        nuevas = self._interpretar(texto)
        with self._candado:
            for fila in nuevas:
                if not fila["variables"]:
                    continue
                fila["n"] = max((f["n"] for f in self._filas), default=0) + 1
                fila["campana"] = fila["campana"] or campana
                fila["fecha"] = fila["fecha"] or datetime.now().strftime("%Y-%m-%d %H:%M")
                if fila["estado"] not in (COMPLETADO, FALLIDO, DESCARTADO, ABORTADO):
                    fila["estado"] = COMPLETADO
                self._filas.append(fila)
            self._guardar()
        return len([f for f in nuevas if f["variables"]])

    def usables(self, experimento) -> tuple[list[dict], list[str]]:
        """Filas que sirven para optimizar 'experimento' y los motivos de las que no.

        Una fila sirve si terminó (completado o fallido) y tiene valor para TODAS
        las variables del experimento actual.
        """
        nombres = [v.nombre for v in experimento.variables]
        buenas, motivos = [], []
        for f in self.filas():
            if f["estado"] not in USABLES:
                continue
            faltan = [n for n in nombres if n not in f["variables"]]
            if faltan:
                motivos.append(f"Experimento {f['n']}: no tiene dato de {', '.join(faltan)}.")
                continue
            buenas.append(f)
        return buenas, motivos


def _formato(valor) -> str:
    if valor is None:
        return ""
    return f"{valor:.6g}"
