"""Modelos de datos: qué es un experimento, una variable, un objetivo y un paso.

La interfaz crea estos objetos y los guarda como archivos YAML en
datos/experimentos/. Los químicos nunca editan esos archivos a mano.
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field, fields, asdict
from pathlib import Path

import yaml

MAXIMIZAR, MINIMIZAR, ALCANZAR = "maximizar", "minimizar", "alcanzar"
TIPOS_PASO = ("accion", "esperar", "confirmar", "ajuste_manual", "medir")


def numero_txt(x) -> str:
    """Número con formato corto y coma decimal (como se escribe en Argentina)."""
    if x is None:
        return "—"
    try:
        return f"{float(x):.4g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(x)


def prediccion_txt(media: float, desvio: float) -> str:
    """Predicción del modelo con las cifras que justifica su incertidumbre: «≈ 43 ± 7»."""
    import math
    if not desvio or desvio <= 0 or not math.isfinite(desvio):
        return f"≈ {numero_txt(media)}"
    decimales = min(4, max(0, 1 - int(math.floor(math.log10(desvio)))))
    if desvio >= 3:
        decimales = 0
    formato = lambda x: f"{x:.{decimales}f}".replace(".", ",")
    return f"≈ {formato(media)} ± {formato(desvio)}"


def identificador(texto: str) -> str:
    """Convierte 'Volumen de NaOH' en 'volumen_de_naoh' (nombre interno)."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    t = re.sub(r"[^a-zA-Z0-9]+", "_", t).strip("_").lower()
    if not t:
        t = "x"
    if t[0].isdigit():
        t = "v_" + t
    return t


def es_referencia(valor) -> bool:
    """Un parámetro que empieza con '$' apunta a una variable del experimento."""
    return isinstance(valor, str) and valor.startswith("$")


@dataclass
class Variable:
    nombre: str                 # identificador interno
    etiqueta: str               # texto que ve el químico
    unidad: str = ""
    minimo: float = 0.0
    maximo: float = 1.0
    paso: float = 0.0           # resolución; 0 = continua
    origen: str = "modulo"      # "modulo" | "tiempo" | "manual"
    modulo: str = ""            # id del módulo que la ajusta (si origen = modulo)
    accion: str = ""
    parametro: str = ""


@dataclass
class Objetivo:
    nombre: str
    etiqueta: str
    unidad: str = ""
    direccion: str = MAXIMIZAR  # maximizar | minimizar | alcanzar
    valor: float | None = None  # valor buscado (solo "alcanzar")
    tolerancia: float | None = None
    meta: float | None = None   # umbral para darlo por cumplido (max/min)
    medicion: str = "manual"    # "manual" | "modulo"
    modulo: str = ""
    magnitud: str = ""

    def cumple(self, y) -> bool:
        """¿Este resultado cumple la meta del objetivo?"""
        if y is None or y != y:
            return False
        if self.direccion == MAXIMIZAR:
            return self.meta is not None and y >= self.meta
        if self.direccion == MINIMIZAR:
            return self.meta is not None and y <= self.meta
        return (self.valor is not None and self.tolerancia is not None
                and abs(y - self.valor) <= self.tolerancia)

    def tiene_meta(self) -> bool:
        if self.direccion == ALCANZAR:
            return self.valor is not None and self.tolerancia is not None
        return self.meta is not None

    def texto_meta(self) -> str:
        u = f" {self.unidad}" if self.unidad else ""
        if self.direccion == ALCANZAR:
            tol = f" ± {numero_txt(self.tolerancia)}" if self.tolerancia is not None else ""
            return f"llevar a {numero_txt(self.valor)}{tol}{u}"
        verbo = "aumentar" if self.direccion == MAXIMIZAR else "reducir"
        if self.meta is None:
            return f"{verbo} todo lo posible"
        signo = "al menos" if self.direccion == MAXIMIZAR else "como máximo"
        return f"{verbo} (meta: {signo} {numero_txt(self.meta)}{u})"


@dataclass
class Paso:
    tipo: str                   # accion | esperar | confirmar | ajuste_manual | medir
    modulo: str = ""
    accion: str = ""
    parametros: dict = field(default_factory=dict)   # número, texto o "$variable"
    segundos: float | str = 0   # número o "$variable" (paso "esperar")
    mensaje: str = ""
    variable: str = ""          # paso "ajuste_manual"
    objetivo: str = ""          # paso "medir"


@dataclass
class Experimento:
    id: str
    nombre: str
    reaccion: str = ""          # los experimentos de una misma reacción comparten historial
    descripcion: str = ""
    max_experimentos: int = 20
    capacidad_vaso_ml: float = 100.0
    supervisado: bool = True    # el químico aprueba cada propuesta antes de ejecutarla
    paciencia: int = 0          # avisar si pasan N experimentos sin mejora (0 = no avisar)
    variables: list[Variable] = field(default_factory=list)
    objetivos: list[Objetivo] = field(default_factory=list)
    restricciones: list[str] = field(default_factory=list)
    protocolo: list[Paso] = field(default_factory=list)
    reactivos: dict = field(default_factory=dict)    # id de módulo -> reactivo cargado
    # Mediciones automáticas que se anotan en cada experimento sin optimizarlas
    # (por ejemplo la temperatura): [{"modulo": "termometro", "magnitud": "temperatura"}]
    registros: list[dict] = field(default_factory=list)

    # --- utilidades -----------------------------------------------------
    def variable(self, nombre: str) -> Variable | None:
        return next((v for v in self.variables if v.nombre == nombre), None)

    def objetivo(self, nombre: str) -> Objetivo | None:
        return next((o for o in self.objetivos if o.nombre == nombre), None)

    def a_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def de_dict(cls, d: dict) -> "Experimento":
        d = dict(d or {})
        def construir(tipo, datos):
            validos = {f.name for f in fields(tipo)}
            return tipo(**{k: v for k, v in (datos or {}).items() if k in validos})
        d["variables"] = [construir(Variable, v) for v in d.get("variables") or []]
        d["objetivos"] = [construir(Objetivo, o) for o in d.get("objetivos") or []]
        d["protocolo"] = [construir(Paso, p) for p in d.get("protocolo") or []]
        d["restricciones"] = list(d.get("restricciones") or [])
        d["reactivos"] = dict(d.get("reactivos") or {})
        d["registros"] = [dict(r) for r in d.get("registros") or []]
        validos = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in d.items() if k in validos})

    def guardar(self, carpeta: Path) -> Path:
        carpeta.mkdir(parents=True, exist_ok=True)
        ruta = carpeta / f"{self.id}.yaml"
        escribir_yaml(ruta, self.a_dict())
        return ruta

    @classmethod
    def cargar(cls, ruta: Path) -> "Experimento":
        return cls.de_dict(leer_yaml(ruta))


# --- archivos -------------------------------------------------------------
def leer_yaml(ruta: Path, defecto=None):
    ruta = Path(ruta)
    if not ruta.exists():
        return defecto
    with open(ruta, encoding="utf-8") as f:
        return yaml.safe_load(f) or defecto


def escribir_yaml(ruta: Path, datos) -> None:
    """Escritura atómica: primero a un temporal y después se reemplaza."""
    ruta = Path(ruta)
    ruta.parent.mkdir(parents=True, exist_ok=True)
    tmp = ruta.with_suffix(ruta.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        yaml.safe_dump(datos, f, allow_unicode=True, sort_keys=False)
    tmp.replace(ruta)


def listar_experimentos(carpeta: Path) -> list[Experimento]:
    carpeta = Path(carpeta)
    if not carpeta.exists():
        return []
    salida = []
    for ruta in sorted(carpeta.glob("*.yaml")):
        try:
            salida.append(Experimento.cargar(ruta))
        except Exception:
            continue
    return salida
