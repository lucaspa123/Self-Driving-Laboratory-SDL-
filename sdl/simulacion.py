"""Reacción inventada para probar el programa sin hardware ni reactivos.

Para cada objetivo existe un punto óptimo oculto distinto, así que mejorar uno
empeora otro: hay un frente de Pareto real que el optimizador debe descubrir.
Los resultados tienen ruido, como una medición de laboratorio.
"""
from __future__ import annotations

import hashlib
import math
import random

from .modelos import ALCANZAR, MAXIMIZAR, Experimento


class ReaccionSimulada:
    def __init__(self, experimento: Experimento, ruido: float = 0.02):
        self.exp = experimento
        self.ruido = ruido
        self._azar = random.Random(self._semilla("ruido"))

    def _semilla(self, *partes) -> int:
        texto = "|".join([self.exp.reaccion or self.exp.id, *map(str, partes)])
        return int(hashlib.sha256(texto.encode()).hexdigest()[:12], 16)

    def _unidad(self, valores: dict) -> list[float]:
        return [(float(valores[v.nombre]) - v.minimo) / max(v.maximo - v.minimo, 1e-12)
                for v in self.exp.variables]

    def _optimo(self, objetivo: str) -> list[float]:
        azar = random.Random(self._semilla("optimo", objetivo))
        return [azar.uniform(0.2, 0.8) for _ in self.exp.variables]

    def ocurre(self, valores: dict) -> bool:
        """La reacción 'no ocurre' en una esquina del espacio (primera variable muy baja)."""
        x = self._unidad(valores)
        return not (x and x[0] < 0.08)

    def valor(self, objetivo: str, valores: dict) -> float:
        o = self.exp.objetivo(objetivo)
        x, optimo = self._unidad(valores), self._optimo(objetivo)
        distancia2 = sum((a - b) ** 2 for a, b in zip(x, optimo))
        calidad = math.exp(-3.0 * distancia2)                    # 1 en el óptimo, baja al alejarse
        if o.direccion == ALCANZAR:
            pendiente = sum((a - b) * (1 if i % 2 == 0 else -1) for i, (a, b) in enumerate(zip(x, optimo)))
            escala = 4.0 * (o.tolerancia or abs(o.valor or 1.0) * 0.05 or 1.0)
            y = (o.valor or 0.0) + escala * pendiente
            amplitud = escala
        elif o.direccion == MAXIMIZAR:
            amplitud = (o.meta * 1.12) if o.meta else 100.0
            y = amplitud * calidad
        else:
            amplitud = (o.meta / 0.3) if o.meta else 100.0
            y = amplitud * (1.15 - calidad)
        y += self._azar.gauss(0, self.ruido * abs(amplitud))
        if o.direccion != ALCANZAR:
            y = max(0.0, y)                      # un rendimiento o una impureza no pueden ser negativos
        return round(y, 3)
