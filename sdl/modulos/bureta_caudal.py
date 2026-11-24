"""Opción de la bureta: «Dosificar un volumen a un caudal».

Agrega a cada bureta una acción en la que el volumen y el caudal son los dos
obligatorios y los dos se pueden dejar como variables a optimizar en el mismo
paso. La dosis se entrega exactamente igual que con «Dosificar un volumen»
(misma calibración, misma curva caudal-apertura, mismo control de nivel).

Se activa o desactiva por bureta en Equipo → Configurar → «Ofrecer la acción
Dosificar un volumen a un caudal». Viene activada.

Este archivo extiende la clase Bureta al cargarse y no modifica bureta.py:
alcanza con tenerlo en esta carpeta. Borrándolo, la acción desaparece.
Para que el caudal se pueda ajustar como variable, la bureta necesita al menos
una apertura parcial calibrada (además de la del 100 %).
"""
from __future__ import annotations

from .bureta import Bureta

ACCION = "dosificar_caudal"
OPCION = "ofrecer_dosificar_caudal"


def extender(clase) -> None:
    if getattr(clase, "_con_dosificar_caudal", False):
        return                                   # ya aplicada (el módulo se importó dos veces)
    clase._con_dosificar_caudal = True
    clase.CONFIG = {**clase.CONFIG, OPCION: {
        "etiqueta": "Ofrecer la acción «Dosificar un volumen a un caudal» (volumen y caudal ajustables a la vez)",
        "valor": True}}
    acciones_base, ejecutar_base, duracion_base = clase.acciones, clase.ejecutar, clase.duracion

    def acciones(self) -> dict:
        todas = acciones_base(self)
        base = todas.get("dosificar")
        if base is None or not self.config.get(OPCION, True):
            return todas
        caudal = dict(base["parametros"]["caudal"])
        caudal.pop("opcional", None)                         # acá el caudal es obligatorio
        todas[ACCION] = {**base, "etiqueta": "Dosificar un volumen a un caudal",
                         "parametros": {"volumen": dict(base["parametros"]["volumen"]), "caudal": caudal}}
        return todas

    def ejecutar(self, accion: str, p: dict) -> dict:
        if accion == ACCION:
            self.comprobar(ACCION, p)                        # volumen y caudal dentro de los límites
            return ejecutar_base(self, "dosificar", p)       # la dosis se hace como siempre
        return ejecutar_base(self, accion, p)

    def duracion(self, accion: str, p: dict) -> float:
        return duracion_base(self, "dosificar" if accion == ACCION else accion, p)

    clase.acciones, clase.ejecutar, clase.duracion = acciones, ejecutar, duracion


extender(Bureta)
