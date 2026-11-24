"""Bitácora: registro de todo lo que hace el programa (auditoría).

Cada línea queda en datos/bitacora.txt con fecha y hora, y las últimas se
muestran en la pantalla de ejecución.
"""
from __future__ import annotations

import threading
from collections import deque
from datetime import datetime
from pathlib import Path


class Bitacora:
    def __init__(self, ruta: Path, recordar: int = 400):
        self.ruta = Path(ruta)
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.lineas: deque[tuple[str, str, str]] = deque(maxlen=recordar)   # (hora, nivel, texto)
        self.version = 0                      # cambia con cada línea (para refrescar la pantalla)
        self._candado = threading.Lock()

    def agregar(self, texto: str, nivel: str = "info") -> None:
        """nivel: 'info' | 'aviso' | 'error'"""
        ahora = datetime.now()
        with self._candado:
            self.lineas.append((ahora.strftime("%H:%M:%S"), nivel, texto))
            self.version += 1
            try:
                with open(self.ruta, "a", encoding="utf-8") as f:
                    f.write(f"{ahora:%Y-%m-%d %H:%M:%S} [{nivel.upper():5}] {texto}\n")
            except OSError:
                pass                          # la bitácora nunca debe frenar un experimento

    def ultimas(self, n: int = 100) -> list[tuple[str, str, str]]:
        with self._candado:
            return list(self.lineas)[-n:]
