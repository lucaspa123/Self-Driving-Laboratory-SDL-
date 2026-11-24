"""Brazo robótico: 4 motores paso a paso (DRV8825) y una pinza con servo.

El brazo trabaja con ESTACIONES: posiciones fijas con nombre ("bureta_1",
"vaso", "lavado"...) que se enseñan una vez desde la pantalla Módulos.
Mueve una articulación por vez. Antes de moverse necesita que se le fije el
origen (no tiene finales de carrera): se coloca a mano en la postura de
referencia y se ejecuta "Fijar origen".
"""
from __future__ import annotations

from .base import ErrorModulo, Modulo

PASOS_MOTOR = 200           # pasos por vuelta de un NEMA17 (1,8°)


class Brazo(Modulo):
    TIPO = "brazo"
    DRIVER = "brazo"
    NOMBRE = "Brazo robótico"
    DESCRIPCION = "Lleva objetos o la manguera entre estaciones fijas."
    CONFIG = {
        "estaciones": {"etiqueta": "Estaciones (ángulos de cada articulación)", "valor": {}},
        "estacion_transito": {"etiqueta": "Estación de paso obligado (vacío = ninguna)", "valor": ""},
        "pinza_abierta": {"etiqueta": "Ángulo de la pinza abierta", "valor": 30, "unidad": "°"},
        "pinza_cerrada": {"etiqueta": "Ángulo de la pinza cerrada", "valor": 95, "unidad": "°"},
        "micropasos": {"etiqueta": "Micropasos del DRV8825", "valor": 8, "avanzado": True},
        "ejes": {"etiqueta": "Articulaciones", "avanzado": True, "valor": [
            {"nombre": "Cintura", "reduccion": 8.8, "min": -90, "max": 90, "vel": 20, "invertir": False},
            {"nombre": "Hombro", "reduccion": 28.03, "min": 0, "max": 90, "vel": 8, "invertir": False},
            {"nombre": "Codo", "reduccion": 10.4, "min": -120, "max": 120, "vel": 20, "invertir": False},
            {"nombre": "Muñeca", "reduccion": 3.05, "min": -90, "max": 90, "vel": 40, "invertir": False},
        ]},
        "origen": {"etiqueta": "Ángulos de la postura de referencia", "valor": [0, 0, 0, 0], "avanzado": True},
        "orden_salida": {"etiqueta": "Orden de ejes al salir de una estación", "valor": [1, 2, 3, 0], "avanzado": True},
        "orden_llegada": {"etiqueta": "Orden de ejes al llegar a una estación", "valor": [0, 3, 2, 1], "avanzado": True},
        "pasos_s_max": {"etiqueta": "Pasos por segundo máximos", "valor": 2000, "avanzado": True},
        "pines_step": {"etiqueta": "Pines STEP (GPIO)", "valor": [4, 6, 8, 10], "avanzado": True},
        "pines_dir": {"etiqueta": "Pines DIR (GPIO)", "valor": [5, 7, 9, 11], "avanzado": True},
        "pin_habilitar": {"etiqueta": "Pin ENABLE común (GPIO)", "valor": 12, "avanzado": True},
        "pin_pinza": {"etiqueta": "Pin del servo de la pinza (GPIO)", "valor": 15, "avanzado": True},
    }

    # --- geometría -------------------------------------------------------
    def _ejes(self) -> list[dict]:
        return self.config["ejes"]

    def _pasos_por_grado(self, i: int) -> float:
        eje = self._ejes()[i]
        return PASOS_MOTOR * float(self.config["micropasos"]) * float(eje["reduccion"]) / 360.0

    def angulos(self) -> list[float]:
        return list(self.estado.get("angulos") or self.config["origen"])

    # --- qué ofrece -----------------------------------------------------
    def acciones(self) -> dict:
        estaciones = sorted(self.config.get("estaciones") or {})
        nombres = [e["nombre"] for e in self._ejes()]
        return {
            "ir_a": {"etiqueta": "Ir a una estación", "en_protocolo": True,
                     "parametros": {"estacion": {"etiqueta": "Estación", "tipo": "opcion",
                                                 "opciones": estaciones}}},
            "abrir_pinza": {"etiqueta": "Abrir la pinza", "en_protocolo": True, "parametros": {}},
            "cerrar_pinza": {"etiqueta": "Cerrar la pinza", "en_protocolo": True, "parametros": {}},
            "fijar_origen": {"etiqueta": "Fijar origen (el brazo está en la postura de referencia)",
                             "parametros": {}},
            "mover_eje": {"etiqueta": "Mover una articulación", "parametros": {
                "eje": {"etiqueta": "Articulación", "tipo": "opcion", "opciones": nombres},
                "grados": {"etiqueta": "Giro (relativo)", "unidad": "°", "min": -45, "max": 45}}},
            "guardar_estacion": {"etiqueta": "Guardar la posición actual como estación", "parametros": {
                "nombre": {"etiqueta": "Nombre de la estación", "tipo": "texto"}}},
            "borrar_estacion": {"etiqueta": "Borrar una estación", "parametros": {
                "estacion": {"etiqueta": "Estación", "tipo": "opcion", "opciones": estaciones}}},
            "liberar_motores": {"etiqueta": "Liberar motores (para mover el brazo a mano)", "parametros": {}},
        }

    def config_firmware(self) -> dict:
        c = self.config
        limites = []
        for i, eje in enumerate(self._ejes()):
            ppg, cero = self._pasos_por_grado(i), float(c["origen"][i])
            a, b = (float(eje["min"]) - cero) * ppg, (float(eje["max"]) - cero) * ppg
            if eje.get("invertir"):
                a, b = -b, -a
            limites.append([int(min(a, b)), int(max(a, b))])
        return {"step": c["pines_step"], "dir": c["pines_dir"], "en": c["pin_habilitar"],
                "pinza": c["pin_pinza"], "limites": limites, "vmax": int(c["pasos_s_max"])}

    def avisos(self) -> list[str]:
        avisos = []
        if not self.estado.get("referenciado"):
            avisos.append(f"{self.etiqueta}: falta fijar el origen (pantalla Módulos).")
        return avisos

    def resumen(self) -> str:
        if not self.estado.get("referenciado"):
            return "Sin origen fijado"
        partes = [f"{e['nombre']} {a:.0f}°" for e, a in zip(self._ejes(), self.angulos())]
        return " · ".join(partes)

    def duracion(self, accion: str, p: dict) -> float:
        if accion != "ir_a":
            return 1.5
        destino = (self.config.get("estaciones") or {}).get(p.get("estacion"))
        if not destino:
            return 5.0
        total = sum(abs(d - a) / max(1.0, float(e["vel"]))
                    for d, a, e in zip(destino, self.angulos(), self._ejes()))
        return total * (2.0 if self.config.get("estacion_transito") else 1.0) + 2.0

    # --- qué hace -------------------------------------------------------
    def autotest(self) -> tuple[bool, str]:
        self._sincronizar()
        if not self.estado.get("referenciado"):
            return True, "Responde. Falta fijar el origen."
        return True, "Responde. Origen fijado."

    def _sincronizar(self) -> None:
        """Lee del ESP32 dónde está cada motor (él lleva la cuenta de pasos)."""
        r = self.enlace.accion(self.id, "estado")
        self.estado["referenciado"] = bool(r.get("ref"))
        if r.get("ref"):
            angulos = []
            for i, pasos in enumerate(r.get("pasos", [])):
                signo = -1 if self._ejes()[i].get("invertir") else 1
                angulos.append(round(float(self.config["origen"][i])
                                     + signo * pasos / self._pasos_por_grado(i), 2))
            self.estado["angulos"] = angulos
        self.guardar_estado()

    def _mover_eje(self, i: int, destino: float) -> None:
        eje = self._ejes()[i]
        if not float(eje["min"]) - 1e-6 <= destino <= float(eje["max"]) + 1e-6:
            raise ErrorModulo(f"{self.etiqueta}: {eje['nombre']} a {destino:.1f}° está fuera de su "
                              f"recorrido ({eje['min']}° a {eje['max']}°).")
        actual = self.angulos()[i]
        ppg = self._pasos_por_grado(i)
        pasos = int(round((destino - actual) * ppg)) * (-1 if eje.get("invertir") else 1)
        if pasos == 0:
            return
        velocidad = min(float(eje["vel"]) * ppg, float(self.config["pasos_s_max"]))
        try:
            self.enlace.accion(self.id, "mover", eje=i, pasos=pasos, vel=int(velocidad),
                               espera=abs(pasos) / velocidad * 1.5 + 10)
        finally:
            self._sincronizar()          # pase lo que pase, la posición real la dice el ESP32

    def _ir_a_angulos(self, destino: list[float], orden: list[int]) -> None:
        for i in orden:
            self._mover_eje(i, float(destino[i]))

    def _exigir_origen(self) -> None:
        if not self.estado.get("referenciado"):
            raise ErrorModulo(f"{self.etiqueta}: primero hay que fijar el origen (pantalla Módulos).")

    def ejecutar(self, accion: str, p: dict) -> dict:
        self.comprobar(accion, p)
        c = self.config
        estaciones = c.setdefault("estaciones", {})
        if accion == "ir_a":
            self._exigir_origen()
            transito = c.get("estacion_transito")
            if transito and transito in estaciones and transito != p["estacion"]:
                self._ir_a_angulos(estaciones[transito], c["orden_salida"])
            self._ir_a_angulos(estaciones[p["estacion"]], c["orden_llegada"])
        elif accion in ("abrir_pinza", "cerrar_pinza"):
            angulo = c["pinza_abierta"] if accion == "abrir_pinza" else c["pinza_cerrada"]
            self.enlace.accion(self.id, "pinza", angulo=float(angulo))
        elif accion == "fijar_origen":
            self.enlace.accion(self.id, "fijar_origen", pasos=[0, 0, 0, 0])
            self._sincronizar()
        elif accion == "mover_eje":
            self._exigir_origen()
            i = [e["nombre"] for e in self._ejes()].index(p["eje"])
            self._mover_eje(i, self.angulos()[i] + float(p["grados"]))
        elif accion == "guardar_estacion":
            self._exigir_origen()
            nombre = str(p["nombre"]).strip()
            if not nombre:
                raise ErrorModulo("La estación necesita un nombre.")
            estaciones[nombre] = [round(a, 2) for a in self.angulos()]
            return {"guardar_config": True}
        elif accion == "borrar_estacion":
            estaciones.pop(p["estacion"], None)
            return {"guardar_config": True}
        elif accion == "liberar_motores":
            self.enlace.accion(self.id, "liberar")
            self.estado["referenciado"] = False     # a mano se pierde la posición
            self.guardar_estado()
        return {}

    def estado_seguro(self) -> None:
        # El brazo se queda quieto donde está, con los motores sosteniendo la carga.
        self.enlace.accion(self.id, "detener")
