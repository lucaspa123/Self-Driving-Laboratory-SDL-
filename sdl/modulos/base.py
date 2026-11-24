"""Contrato que cumplen todos los módulos (actuadores y sensores).

Para agregar un módulo nuevo alcanza con crear un archivo en esta carpeta con
una clase que herede de Modulo (ver _plantilla.py). El programa lo descubre solo.

Cada módulo declara:
    CONFIG      valores de instalación y calibración (pines, caudales...)
    acciones()  qué sabe hacer y con qué parámetros (y sus límites absolutos)
    mediciones() qué magnitudes puede medir
y sabe ponerse en estado seguro.
"""
from __future__ import annotations

import copy


class NecesitaUsuario(Exception):
    """El módulo necesita que una persona haga algo antes de seguir.

    Ejemplo: recargar una bureta. El motor muestra el mensaje en la interfaz,
    espera la respuesta y llama a modulo.resolver(respuesta).
    """

    def __init__(self, mensaje: str, campos: list[dict] | None = None, clave: str = ""):
        super().__init__(mensaje)
        self.mensaje = mensaje
        self.campos = campos or []       # [{"clave", "etiqueta", "unidad", "valor"}]
        self.clave = clave


class ErrorModulo(Exception):
    """El módulo no pudo hacer lo pedido (fuera de límites, sin calibrar...)."""


class Modulo:
    TIPO = ""                 # nombre corto y único del tipo de módulo
    DRIVER = ""               # driver del firmware que usa (vacío = igual a TIPO)
    NOMBRE = ""               # nombre para mostrar
    DESCRIPCION = ""
    USA_ESP32 = True          # False para módulos que solo usan la PC (cámara)
    CONFIG: dict = {}         # clave -> {"etiqueta", "valor", "unidad", "avanzado"}
    ACCIONES: dict = {}
    MEDICIONES: dict = {}
    CALIBRACION: dict | None = None

    def __init__(self, ident: str, etiqueta: str, config: dict, enlace, estado: dict, guardar):
        self.id = ident
        self.etiqueta = etiqueta or ident
        self.config = copy.deepcopy({k: v.get("valor") for k, v in self.CONFIG.items()})
        self.config.update(copy.deepcopy(config or {}))
        self.enlace = enlace
        self.estado = estado              # memoria persistente del módulo (dict)
        self._guardar = guardar           # función() que la guarda en disco

    # --- qué ofrece -----------------------------------------------------
    def acciones(self) -> dict:
        """Acciones disponibles. Formato:
        {"dosificar": {"etiqueta": "...", "en_protocolo": True,
                       "agrega_volumen": "volumen",          # parámetro que suma líquido al vaso
                       "parametros": {"volumen": {"etiqueta", "unidad", "min", "max", "paso",
                                                  "tipo": "numero"|"opcion"|"texto",
                                                  "opciones": [...], "optimizable": True}}}}
        """
        return self.ACCIONES

    def mediciones(self) -> dict:
        """Magnitudes medibles: {"temperatura": {"etiqueta": "...", "unidad": "°C"}}"""
        return self.MEDICIONES

    def config_firmware(self) -> dict | None:
        """Lo que necesita saber el ESP32 (pines, límites). None si no usa ESP32."""
        return None

    # --- qué hace -------------------------------------------------------
    def autotest(self) -> tuple[bool, str]:
        """Comprueba que el módulo responde. Devuelve (ok, mensaje)."""
        return True, "Disponible"

    def avisos(self) -> list[str]:
        """Advertencias para mostrar antes de empezar (p. ej. 'sin calibrar')."""
        return []

    def ejecutar(self, accion: str, p: dict) -> dict:
        raise ErrorModulo(f"{self.etiqueta} no sabe hacer '{accion}'.")

    def medir(self, magnitud: str) -> float:
        raise ErrorModulo(f"{self.etiqueta} no mide '{magnitud}'.")

    def al_iniciar_campana(self, reactivo: str = "") -> NecesitaUsuario | None:
        """Algo que el usuario deba confirmar antes de empezar (p. ej. el nivel de la bureta)."""
        return None

    def resolver(self, clave: str, respuesta: dict) -> None:
        """Recibe la respuesta del usuario a un NecesitaUsuario."""

    def estado_seguro(self) -> None:
        """Deja el actuador en una condición sin riesgo (válvula cerrada, motor apagado)."""

    def duracion(self, accion: str, p: dict) -> float:
        """Duración estimada en segundos (para la barra de progreso y los tiempos de espera)."""
        return 1.0

    def resumen(self) -> str:
        """Texto corto de estado para la interfaz."""
        return ""

    # --- calibración (opcional) ------------------------------------------
    # CALIBRACION = {"texto", "antes": [campos], "despues": [campos], "texto_despues",
    #                "manual": {"texto", "campos": [campos]}}
    #   antes/despues: el programa hace algo (calibrar_ejecutar) y el usuario mide (calibrar_aplicar).
    #   manual: el usuario ya midió todo a mano (calibrar_previa muestra el resultado, calibrar_manual lo guarda).
    def calibrar_ejecutar(self, datos: dict) -> None:
        raise ErrorModulo("Este módulo no tiene calibración.")

    def calibracion_estado(self) -> list[str]:
        """Qué hay calibrado hasta ahora (texto para mostrar al abrir la calibración)."""
        return []

    def calibrar_previa(self, datos: dict) -> list[str]:
        raise ErrorModulo("Este módulo no tiene calibración manual.")

    def calibrar_manual(self, datos: dict) -> str:
        raise ErrorModulo("Este módulo no tiene calibración manual.")

    def calibrar_aplicar(self, datos: dict) -> str:
        raise ErrorModulo("Este módulo no tiene calibración.")

    # --- utilidades -----------------------------------------------------
    def guardar_estado(self) -> None:
        self._guardar()

    def comprobar(self, accion: str, p: dict) -> None:
        """Capa 1 de seguridad: límites absolutos del módulo."""
        definicion = self.acciones().get(accion)
        if definicion is None:
            raise ErrorModulo(f"{self.etiqueta} no tiene la acción '{accion}'.")
        for nombre, d in (definicion.get("parametros") or {}).items():
            if nombre not in p or p[nombre] is None or p[nombre] == "":
                if d.get("opcional"):
                    continue
                raise ErrorModulo(f"{self.etiqueta}: falta el parámetro '{d.get('etiqueta', nombre)}'.")
            valor = p[nombre]
            tipo = d.get("tipo", "numero")
            if tipo == "numero":
                try:
                    valor = float(valor)
                except (TypeError, ValueError):
                    raise ErrorModulo(f"{self.etiqueta}: '{d.get('etiqueta', nombre)}' debe ser un número.")
                if "min" in d and valor < d["min"] - 1e-9 or "max" in d and valor > d["max"] + 1e-9:
                    raise ErrorModulo(
                        f"{self.etiqueta}: {d.get('etiqueta', nombre)} = {valor:g} {d.get('unidad', '')} "
                        f"está fuera del límite del equipo ({d.get('min', '-')} a {d.get('max', '-')}).")
            elif tipo == "opcion" and valor not in (d.get("opciones") or []):
                raise ErrorModulo(f"{self.etiqueta}: '{valor}' no es una opción válida de "
                                  f"{d.get('etiqueta', nombre)}.")
