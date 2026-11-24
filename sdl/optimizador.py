"""Optimización bayesiana multiobjetivo (frente de Pareto).

Cómo decide el próximo experimento:

1. EXPLORACIÓN. Mientras haya pocos datos, propone puntos que cubran las zonas
   del espacio que todavía no se ensayaron (secuencia de Sobol + máxima distancia
   a lo ya hecho). Un modelo con 1 o 2 puntos no puede predecir nada.

2. OPTIMIZACIÓN (método ParEGO). En cada vuelta:
   - Convierte cada objetivo en un "costo" a minimizar y lo lleva a escala 0-1.
   - Sortea una prioridad distinta para cada objetivo (pesos al azar). Así, a lo
     largo de la campaña, recorre todo el frente de Pareto y no un solo compromiso.
   - Combina los costos con esos pesos (Chebyshev aumentado) en un único número.
   - Ajusta un proceso gaussiano (GP) con ruido a ese número.
   - Elige el punto con mayor Mejora Esperada (EI) entre miles de candidatos que
     respetan los límites, la resolución de los actuadores y las restricciones.

Los experimentos donde la reacción no ocurrió entran al modelo con un costo
peor que el peor resultado observado (penalización), para alejarse de esa zona.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass, field

import numpy as np
from scipy.stats import norm, qmc
from sklearn.exceptions import ConvergenceWarning
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

from .historial import COMPLETADO, FALLIDO
from .modelos import ALCANZAR, MAXIMIZAR, Experimento
from .restricciones import compilar

PENALIZACION = 1.1          # costo normalizado de un experimento fallido (el peor observado es 1.0)
RHO = 0.05                  # término aumentado de Chebyshev
XI = 0.01                   # margen de exploración de la mejora esperada


@dataclass
class Propuesta:
    valores: dict                        # variable -> valor propuesto
    fase: str                            # "exploracion" | "optimizacion"
    motivo: str                          # explicación en lenguaje simple
    prediccion: dict = field(default_factory=dict)   # objetivo -> (media, desvío)
    pesos: dict = field(default_factory=dict)        # objetivo -> prioridad de esta vuelta


def no_dominados(costos: np.ndarray) -> np.ndarray:
    """Máscara de filas no dominadas (todos los costos se minimizan)."""
    n = len(costos)
    mascara = np.ones(n, dtype=bool)
    for i in range(n):
        if not mascara[i]:
            continue
        domina_a_i = np.all(costos <= costos[i], axis=1) & np.any(costos < costos[i], axis=1)
        if domina_a_i.any():
            mascara[i] = False
    return mascara


class Optimizador:
    def __init__(self, experimento: Experimento, semilla: int | None = None, factible=None):
        """'factible' es una función opcional(valores) -> bool con condiciones extra
        (por ejemplo, que el volumen total no supere el vaso)."""
        self.exp = experimento
        self.factible = factible
        self.variables = experimento.variables
        self.objetivos = experimento.objetivos
        self.d, self.m = len(self.variables), len(self.objetivos)
        self.rng = np.random.default_rng(semilla)
        nombres = [v.nombre for v in self.variables]
        self.restricciones = [compilar(r, nombres) for r in experimento.restricciones if r.strip()]
        self._min = np.array([v.minimo for v in self.variables], dtype=float)
        self._rango = np.array([max(v.maximo - v.minimo, 1e-12) for v in self.variables])

    # --- tamaños ------------------------------------------------------------
    def n_inicial(self) -> int:
        """Experimentos de exploración antes de confiar en el modelo.

        Cerca del 30 % del máximo fijado por el químico, con piso de 5 y sin pasar
        de 2 por variable (más que eso es desperdiciar presupuesto).
        """
        treinta = round(0.3 * max(1, self.exp.max_experimentos))
        return int(max(5, min(2 * self.d, treinta)))

    # --- escalas --------------------------------------------------------------
    def ajustar(self, valores: dict) -> dict:
        """Lleva cada valor a su rango y a la resolución (paso) de la variable."""
        salida = {}
        for v in self.variables:
            x = min(max(float(valores[v.nombre]), v.minimo), v.maximo)
            if v.paso and v.paso > 0:
                x = v.minimo + round((x - v.minimo) / v.paso) * v.paso
                if x > v.maximo + 1e-9:
                    x -= v.paso
                decimales = max(0, -int(math.floor(math.log10(v.paso))) + 2)
                x = round(x, decimales)
            salida[v.nombre] = x
        return salida

    def _a_unidad(self, valores: dict) -> np.ndarray:
        return (np.array([float(valores[v.nombre]) for v in self.variables]) - self._min) / self._rango

    def _de_unidad(self, x: np.ndarray) -> dict:
        crudos = self._min + np.clip(x, 0, 1) * self._rango
        return self.ajustar({v.nombre: crudos[i] for i, v in enumerate(self.variables)})

    def cumple_restricciones(self, valores: dict) -> bool:
        if not all(r(valores) for r in self.restricciones):
            return False
        return self.factible is None or bool(self.factible(valores))

    def costo(self, j: int, y: float) -> float:
        o = self.objetivos[j]
        if o.direccion == MAXIMIZAR:
            return -y
        if o.direccion == ALCANZAR:
            return abs(y - (o.valor or 0.0))
        return y

    # --- datos ----------------------------------------------------------------
    def _matrices(self, filas: list[dict]):
        """X normalizada, costos crudos (NaN si falta) y máscara de éxito."""
        X = np.array([self._a_unidad(f["variables"]) for f in filas]).reshape(len(filas), self.d)
        exito = np.array([f["estado"] == COMPLETADO for f in filas], dtype=bool)
        C = np.full((len(filas), self.m), np.nan)
        for i, f in enumerate(filas):
            if not exito[i]:
                continue
            for j, o in enumerate(self.objetivos):
                y = f["resultados"].get(o.nombre)
                if y is not None:
                    C[i, j] = self.costo(j, y)
        return X, C, exito

    @staticmethod
    def _normalizar(C: np.ndarray, completos: np.ndarray, exito: np.ndarray) -> np.ndarray:
        """Costos a escala 0-1 (0 = mejor observado). Fallidos = PENALIZACION."""
        base = C[completos]
        minimo, maximo = base.min(axis=0), base.max(axis=0)
        rango = np.where(maximo - minimo > 1e-12, maximo - minimo, 1.0)
        N = (C - minimo) / rango
        N[~exito] = PENALIZACION
        return N

    # --- modelo ----------------------------------------------------------------
    def _gp(self, X: np.ndarray, y: np.ndarray) -> GaussianProcessRegressor:
        nucleo = (ConstantKernel(1.0, (1e-2, 1e2))
                  * Matern(length_scale=np.full(self.d, 0.5), length_scale_bounds=(0.05, 10.0), nu=2.5)
                  + WhiteKernel(noise_level=1e-2, noise_level_bounds=(1e-5, 0.5)))
        gp = GaussianProcessRegressor(nucleo, normalize_y=True, n_restarts_optimizer=4,
                                      random_state=int(self.rng.integers(1 << 31)))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", ConvergenceWarning)
            gp.fit(X, y)
        return gp

    def _candidatos(self, X_obs: np.ndarray, centros: np.ndarray | None = None) -> tuple[np.ndarray, list[dict]]:
        """Puntos posibles: respetan resolución y restricciones, y no repiten lo ya hecho."""
        sobol = qmc.Sobol(self.d, scramble=True, seed=int(self.rng.integers(1 << 31)))
        puntos = [sobol.random_base2(11)]
        if centros is not None and len(centros):
            for sigma in (0.03, 0.10):
                for c in centros:
                    puntos.append(np.clip(c + self.rng.normal(0, sigma, (96, self.d)), 0, 1))
        puntos = np.vstack(puntos)
        tolerancia = np.array([0.5 * v.paso / r if v.paso else 0.004
                               for v, r in zip(self.variables, self._rango)])
        vistos, X, valores = set(), [], []
        for p in puntos:
            v = self._de_unidad(p)
            clave = tuple(v.values())
            if clave in vistos or not self.cumple_restricciones(v):
                continue
            vistos.add(clave)
            x = self._a_unidad(v)
            if len(X_obs) and np.any(np.all(np.abs(X_obs - x) <= tolerancia + 1e-12, axis=1)):
                continue                           # ya se hizo ese experimento
            X.append(x)
            valores.append(v)
        return np.array(X).reshape(len(X), self.d), valores

    def _predicciones(self, X: np.ndarray, filas: list[dict], exito: np.ndarray, x: np.ndarray) -> dict:
        """Resultado esperado de cada objetivo en el punto propuesto (media, desvío)."""
        salida = {}
        for o in self.objetivos:
            y = np.array([f["resultados"].get(o.nombre, np.nan) if e else np.nan
                          for f, e in zip(filas, exito)], dtype=float)
            validos = ~np.isnan(y)
            # Con muy pocos datos la predicción no significa nada: no se muestra.
            if validos.sum() < max(5, self.d + 2) or np.ptp(y[validos]) < 1e-12:
                continue
            try:
                media, desvio = self._gp(X[validos], y[validos]).predict(x.reshape(1, -1), return_std=True)
                salida[o.nombre] = (float(media[0]), float(desvio[0]))
            except Exception:
                continue
        return salida

    # --- propuesta ---------------------------------------------------------------
    def proponer(self, filas: list[dict], excluir: list[dict] | None = None) -> Propuesta | None:
        """Próximo experimento. None si ya no quedan combinaciones posibles.

        'excluir' son combinaciones que no deben volver a proponerse (por ejemplo,
        las que el químico rechazó).
        """
        filas = [f for f in filas if f["estado"] in (COMPLETADO, FALLIDO)]
        if filas:
            X, C, exito = self._matrices(filas)
        else:
            X, C, exito = np.empty((0, self.d)), np.empty((0, self.m)), np.empty(0, dtype=bool)
        completos = exito & ~np.isnan(C).any(axis=1)
        evitar = X
        if excluir:
            evitar = np.vstack([X, np.array([self._a_unidad(v) for v in excluir]).reshape(-1, self.d)])

        if len(filas) < self.n_inicial() or completos.sum() < 3:
            return self._explorar(X, filas, exito, completos, evitar)

        N = self._normalizar(C, completos, exito)
        usar = completos | ~exito                       # éxitos completos + fallidos penalizados
        pesos = self.rng.dirichlet(np.ones(self.m)) if self.m > 1 else np.ones(1)
        escalar = (N[usar] * pesos).max(axis=1) + RHO * (N[usar] * pesos).sum(axis=1)
        Xu = X[usar]
        if np.ptp(escalar) < 1e-12:
            return self._explorar(X, filas, exito, completos, evitar)
        gp = self._gp(Xu, escalar)

        mejores = Xu[np.argsort(escalar)[:5]]
        Xc, valores = self._candidatos(evitar, mejores)
        if not len(Xc):
            return None
        media, desvio = gp.predict(Xc, return_std=True)
        mejor = float(gp.predict(Xu).min())             # mejor valor "creíble" (filtra el ruido)
        mejora = mejor - media - XI
        desvio = np.maximum(desvio, 1e-9)
        z = mejora / desvio
        ei = mejora * norm.cdf(z) + desvio * norm.pdf(z)
        k = int(np.argmax(ei))

        pesos_por_objetivo = {o.nombre: float(w) for o, w in zip(self.objetivos, pesos)}
        if self.m > 1:
            partes = ", ".join(f"{o.etiqueta} {w * 100:.0f} %" for o, w in zip(self.objetivos, pesos))
            motivo = ("Optimización: punto con mayor mejora esperada según el modelo. "
                      f"Prioridad sorteada en esta vuelta: {partes}.")
        else:
            motivo = "Optimización: punto con mayor mejora esperada según el modelo."
        return Propuesta(valores[k], "optimizacion", motivo,
                         self._predicciones(X, filas, exito, Xc[k]), pesos_por_objetivo)

    def _explorar(self, X, filas, exito, completos, evitar) -> Propuesta | None:
        Xc, valores = self._candidatos(evitar)
        if not len(Xc):
            return None
        if len(evitar):
            distancia = np.min(np.linalg.norm(Xc[:, None, :] - evitar[None, :, :], axis=2), axis=1)
            k = int(np.argmax(distancia))
        else:
            k = int(np.argmin(np.linalg.norm(Xc - 0.5, axis=1)))
        faltan = max(0, self.n_inicial() - len(filas))
        if faltan:
            motivo = (f"Exploración: punto alejado de todo lo ya ensayado, para conocer el espacio. "
                      f"Quedan {faltan} experimento(s) de exploración antes de optimizar.")
        else:
            motivo = ("Exploración: todavía no hay 3 experimentos exitosos con todos los resultados, "
                      "así que se sigue cubriendo el espacio.")
        prediccion = self._predicciones(X, filas, exito, Xc[k]) if completos.sum() >= 3 else {}
        return Propuesta(valores[k], "exploracion", motivo, prediccion)

    # --- análisis de resultados ---------------------------------------------------
    def analizar(self, filas: list[dict]) -> dict:
        """Frente de Pareto, mejores resultados y avance de la campaña."""
        filas = [f for f in filas if f["estado"] in (COMPLETADO, FALLIDO)]
        salida = {"pareto": [], "mejor_por_objetivo": {}, "equilibrio": None, "cumplen": [],
                  "acumulado": {o.nombre: [] for o in self.objetivos}, "hipervolumen": [],
                  "orden": [f["n"] for f in filas], "n_exitosos": 0, "n_fallidos": 0}
        if not filas:
            return salida
        _, C, exito = self._matrices(filas)
        completos = exito & ~np.isnan(C).any(axis=1)
        salida["n_exitosos"] = int(exito.sum())
        salida["n_fallidos"] = int((~exito).sum())

        # mejor acumulado por objetivo (en unidades reales)
        for j, o in enumerate(self.objetivos):
            mejor_costo, mejor_y, serie = np.inf, None, []
            for i, f in enumerate(filas):
                if exito[i] and not np.isnan(C[i, j]) and C[i, j] < mejor_costo:
                    mejor_costo, mejor_y = C[i, j], f["resultados"][o.nombre]
                    salida["mejor_por_objetivo"][o.nombre] = f["n"]
                serie.append(mejor_y)
            salida["acumulado"][o.nombre] = serie

        con_meta = [o for o in self.objetivos if o.tiene_meta()]
        if con_meta:
            salida["cumplen"] = [f["n"] for i, f in enumerate(filas) if completos[i]
                                 and all(o.cumple(f["resultados"].get(o.nombre)) for o in con_meta)]
        if not completos.any():
            salida["hipervolumen"] = [0.0] * len(filas)
            return salida

        N = self._normalizar(C, completos, exito)
        indices = np.where(completos)[0]
        frente = indices[no_dominados(N[indices])]
        salida["pareto"] = [filas[i]["n"] for i in frente]
        # mejor equilibrio: el punto del frente con menor "peor costo" (Chebyshev, pesos iguales)
        salida["equilibrio"] = filas[frente[np.argmin(N[frente].max(axis=1))]]["n"]

        # hipervolumen dominado acumulado (Monte Carlo, referencia = PENALIZACION en cada eje)
        if self.m == 1:
            mejor, serie = np.inf, []
            for i in range(len(filas)):
                if completos[i]:
                    mejor = min(mejor, N[i, 0])
                serie.append(float((PENALIZACION - mejor) / PENALIZACION) if np.isfinite(mejor) else 0.0)
            salida["hipervolumen"] = serie
        else:
            muestras = np.random.default_rng(0).uniform(0, PENALIZACION, (20000, self.m))
            dominado, serie = np.zeros(len(muestras), dtype=bool), []
            for i in range(len(filas)):
                if completos[i]:
                    dominado |= np.all(muestras >= N[i], axis=1)
                serie.append(float(dominado.mean()))
            salida["hipervolumen"] = serie
        return salida
