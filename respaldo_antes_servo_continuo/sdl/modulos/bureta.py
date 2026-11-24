"""Bureta con servo en el robinete.

El volumen se dosifica por tiempo de apertura. Como el caudal baja a medida
que baja el nivel (Torricelli: caudal = k · raíz(altura)), el módulo lleva la
cuenta del reactivo que queda en la bureta y calcula el tiempo de apertura de cada dosis.

CAUDAL REGULABLE: el servo puede abrir el robinete solo en parte. Cada apertura
(en % del recorrido entre cerrado y totalmente abierto) tiene su propia
constante de caudal k, que se mide en la calibración. Con esos puntos se arma
una CURVA caudal-apertura (no lineal): entre dos puntos calibrados, el
logaritmo del caudal se interpola en línea recta, porque el caudal de un
robinete crece de forma parecida a una exponencial al abrirlo. Al pedir un
caudal, el módulo busca en esa curva la apertura que lo da.

La curva pasa exactamente por los puntos medidos y nunca se extiende más allá
del más chico ni del más grande. Entre puntos es una estimación: cuantos más
puntos se calibren, mejor. Con la opción desactivada se usa solo la apertura
calibrada más cercana.

Con el usuario siempre se habla de VOLUMEN DE REACTIVO QUE HAY EN LA BURETA
(llena = su capacidad), nunca de la lectura de la escala: en la escala de una
bureta el 0 es "llena" y eso se presta a confusión.
"""
from __future__ import annotations

import math

from ..comunicacion import ErrorEnlace, ParadaEmergencia
from .base import ErrorModulo, Modulo, NecesitaUsuario

_CAMPO_APERTURA = {"clave": "apertura", "etiqueta": "Apertura del robinete (100 = del todo)", "unidad": "%",
                   "valor": 100.0, "min": 5.0, "max": 100.0}


class Bureta(Modulo):
    TIPO = "bureta"
    DRIVER = "servo_valvula"
    NOMBRE = "Bureta con servo"
    DESCRIPCION = "Dosifica un reactivo abriendo el robinete, del todo o en parte, durante un tiempo calculado."
    CONFIG = {
        "capacidad_ml": {"etiqueta": "Capacidad", "valor": 25.0, "unidad": "mL"},
        "dosis_min_ml": {"etiqueta": "Dosis mínima", "valor": 0.2, "unidad": "mL"},
        "resolucion_ml": {"etiqueta": "Resolución de dosificación", "valor": 0.1, "unidad": "mL"},
        "caudal_habitual": {"etiqueta": "Caudal habitual al dosificar (vacío = robinete abierto del todo)",
                            "valor": None, "unidad": "mL/s"},
        "mm_por_ml": {"etiqueta": "Largo de escala por mL", "valor": 13.0, "unidad": "mm/mL"},
        "altura_base_mm": {"etiqueta": "Altura de la marca final a la punta", "valor": 100.0, "unidad": "mm"},
        "caudal_k": {"etiqueta": "Constante de caudal con el robinete abierto del todo (calibración)",
                     "valor": 0.02, "unidad": "mL/s/√mm"},
        "caudal_continuo": {"etiqueta": "Usar la curva caudal-apertura (desactivado: solo aperturas calibradas)",
                            "valor": True},
        "aperturas": {"etiqueta": "Aperturas parciales calibradas: [apertura en %, constante de caudal]",
                      "valor": [], "avanzado": True},
        "tiempo_muerto_s": {"etiqueta": "Tiempo muerto del servo", "valor": 0.15, "unidad": "s"},
        "calibrada": {"etiqueta": "Calibrada", "valor": False},
        "angulo_cerrado": {"etiqueta": "Ángulo del servo: cerrado", "valor": 0, "unidad": "°", "avanzado": True},
        "angulo_abierto": {"etiqueta": "Ángulo del servo: abierto del todo", "valor": 90, "unidad": "°",
                           "avanzado": True},
        "apertura_max_s": {"etiqueta": "Apertura máxima permitida", "valor": 60, "unidad": "s", "avanzado": True},
        "pin_servo": {"etiqueta": "Pin del servo (GPIO)", "valor": 13, "avanzado": True},
    }
    CALIBRACION = {
        # Modo 1: el usuario ya midió a mano cuánto salió y en cuánto tiempo.
        "manual": {
            "titulo": "Ya lo medí yo: escribo el volumen y el tiempo",
            "texto": ("Abra el robinete con el servo (desde «Usar manualmente → Abrir el robinete», con la apertura "
                      "que quiera calibrar), cronometre y ciérrelo. Escriba cuánto líquido salió y cuánto tardó. "
                      "El programa calcula el caudal de esa apertura y cuánto tiempo abrir para cada dosis. "
                      "Repita con cada apertura que quiera usar: 100 % y, por ejemplo, 50 % y 35 %."),
            "campos": [
                dict(_CAMPO_APERTURA),
                {"clave": "inicial", "etiqueta": "Volumen que había en la bureta al empezar", "unidad": "mL",
                 "valor": 25.0, "min": 0.1},
                {"clave": "salio", "etiqueta": "Volumen que salió", "unidad": "mL", "valor": None, "min": 0.01},
                {"clave": "segundos", "etiqueta": "Tiempo que tardó", "unidad": "s", "valor": None, "min": 0.2},
            ],
        },
        # Modo 2: el programa abre el robinete un tiempo fijo y el usuario mide cuánto salió.
        "titulo": "Que el programa abra el robinete un tiempo y yo mido cuánto salió",
        "texto": ("Coloque un vaso o una probeta debajo. El programa abrirá el robinete con la apertura y durante "
                  "el tiempo indicados; después escriba cuánto líquido salió."),
        "antes": [
            dict(_CAMPO_APERTURA),
            {"clave": "inicial", "etiqueta": "Volumen que hay en la bureta", "unidad": "mL", "valor": 25.0,
             "min": 0.1},
            {"clave": "segundos", "etiqueta": "Tiempo de apertura", "unidad": "s", "valor": 5.0, "min": 0.5},
        ],
        "despues": [{"clave": "salio", "etiqueta": "Volumen que salió", "unidad": "mL", "valor": None, "min": 0.01}],
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._parcial_ok: bool | None = None          # ¿el firmware del ESP32 sabe abrir en parte?
        # Versiones anteriores guardaban la lectura de la escala (0 = llena): se convierte una sola vez.
        if "lectura_ml" in self.estado:
            lectura = self.estado.pop("lectura_ml")
            if lectura is not None and "disponible_ml" not in self.estado:
                self.estado["disponible_ml"] = max(0.0, float(self.config["capacidad_ml"]) - float(lectura))

    # --- aperturas calibradas ------------------------------------------------
    def tabla(self) -> dict[float, float]:
        """Aperturas calibradas: {apertura en %: constante de caudal k}. Siempre incluye 100 %."""
        tabla = {100.0: float(self.config["caudal_k"])}
        for par in self.config.get("aperturas") or []:
            try:
                pct, k = float(par[0]), float(par[1])
            except (TypeError, ValueError, IndexError):
                continue
            if 0 < pct < 100 and k > 0:
                tabla[round(pct, 1)] = k
        return tabla

    def caudal_nominal(self, k: float) -> float:
        """Caudal (mL/s) de una apertura con la bureta llena: el número con el que se la identifica."""
        return k * math.sqrt(self._altura(float(self.config["capacidad_ml"])))

    def curva(self) -> list[tuple[float, float]] | None:
        """Puntos (apertura, k) de la curva caudal-apertura, o None si no se puede usar.

        Hace falta la opción activada, al menos dos aperturas calibradas y que el
        caudal crezca con la apertura (si no, alguna medición está mal).
        """
        puntos = sorted(self.tabla().items())
        if not self.config.get("caudal_continuo", True) or len(puntos) < 2:
            return None
        if any(k1 >= k2 for (_, k1), (_, k2) in zip(puntos, puntos[1:])):
            return None
        return puntos

    def k_en(self, apertura: float) -> float | None:
        """Constante de caudal que la curva da para una apertura (None fuera del tramo calibrado)."""
        puntos = self.curva()
        if puntos is None or not puntos[0][0] - 1e-9 <= apertura <= puntos[-1][0] + 1e-9:
            return None
        for (a0, k0), (a1, k1) in zip(puntos, puntos[1:]):
            if apertura <= a1 + 1e-9:
                f = (apertura - a0) / (a1 - a0)
                return math.exp(math.log(k0) + f * (math.log(k1) - math.log(k0)))
        return puntos[-1][1]

    def apertura_para(self, k: float) -> float:
        """Apertura (%) que da la constante de caudal k según la curva (se limita al tramo calibrado)."""
        puntos = self.curva()
        k = min(max(k, puntos[0][1]), puntos[-1][1])
        for (a0, k0), (a1, k1) in zip(puntos, puntos[1:]):
            if k <= k1 * (1 + 1e-12):
                f = (math.log(k) - math.log(k0)) / (math.log(k1) - math.log(k0))
                return a0 + f * (a1 - a0)
        return puntos[-1][0]

    def elegir_apertura(self, caudal: float | None) -> tuple[float, float]:
        """Apertura (%, k) para el caudal pedido (el que daría con la bureta llena).

        Sin pedido usa el caudal habitual y, si no hay, el robinete abierto del todo.
        Con la curva disponible la apertura sale de la curva (redondeada a 0,5 %,
        que es lo que un servo puede repetir); si no, se usa la calibrada más cercana.
        """
        tabla = self.tabla()
        if caudal is None:
            caudal = self.config.get("caudal_habitual")
        if caudal is None or float(caudal) <= 0:
            return 100.0, tabla[100.0]
        if self.curva() is not None:
            k_pedido = float(caudal) / math.sqrt(self._altura(float(self.config["capacidad_ml"])))
            apertura = round(self.apertura_para(k_pedido) * 2) / 2
            apertura = min(max(apertura, min(tabla)), 100.0)
            return apertura, self.k_en(apertura)
        pct = min(tabla, key=lambda x: abs(math.log(self.caudal_nominal(tabla[x]) / float(caudal))))
        return pct, tabla[pct]

    def _angulo(self, apertura: float) -> float:
        c = self.config
        return round(c["angulo_cerrado"] + (c["angulo_abierto"] - c["angulo_cerrado"]) * apertura / 100.0, 1)

    def _exigir_parcial(self, apertura: float) -> None:
        """Una apertura parcial solo se usa si el ESP32 tiene el driver que la entiende.

        Con el driver viejo el robinete se abriría del todo durante el tiempo calculado
        para un caudal chico, y entregaría mucho más de lo pedido.
        """
        if apertura >= 100.0 or getattr(self.enlace, "simulado", False):
            return
        if self._parcial_ok is None:
            try:
                self._parcial_ok = bool(self.enlace.accion(self.id, "info").get("parcial"))
            except ErrorEnlace:
                self._parcial_ok = False
        if not self._parcial_ok:
            raise ErrorModulo(f"{self.etiqueta}: el ESP32 tiene una versión vieja del driver y no sabe abrir el "
                              f"robinete en parte. Copie firmware/drivers/servo_valvula.py al ESP32 y reconecte.")

    # --- qué ofrece -----------------------------------------------------
    def acciones(self) -> dict:
        c = self.config
        nominales = sorted(self.caudal_nominal(k) for k in self.tabla().values())
        # Con la curva, el caudal pedido debe estar dentro de lo calibrado (2 % de margen por redondeos).
        # Sin la curva se usa la apertura calibrada más cercana y se acepta hasta un 25 % por fuera.
        margen = 0.02 if self.curva() is not None else 0.25
        caudal = {"etiqueta": "Caudal", "unidad": "mL/s", "opcional": True,
                  "min": math.floor(nominales[0] * (1 - margen) * 1000) / 1000,
                  "max": math.ceil(nominales[-1] * (1 + margen) * 1000) / 1000,
                  "optimizable": len(nominales) > 1}
        return {
            "dosificar": {
                "etiqueta": "Dosificar un volumen", "en_protocolo": True,
                "agrega_volumen": "volumen", "usa_reactivo": True,
                "parametros": {"volumen": {"etiqueta": "Volumen", "unidad": "mL",
                                           "min": c["dosis_min_ml"], "max": c["capacidad_ml"],
                                           "paso": c["resolucion_ml"], "optimizable": True},
                               "caudal": caudal},
            },
            "abrir": {"etiqueta": "Abrir el robinete (manual)",
                      "parametros": {"apertura": {"etiqueta": "Apertura (100 = del todo)", "unidad": "%",
                                                  "min": 5.0, "max": 100.0, "opcional": True}}},
            "cerrar": {"etiqueta": "Cerrar el robinete", "parametros": {}},
            "fijar_volumen": {"etiqueta": "Indicar cuánto reactivo hay en la bureta",
                              "parametros": {"volumen": {"etiqueta": "Reactivo en la bureta", "unidad": "mL",
                                                         "min": 0.0, "max": c["capacidad_ml"]}}},
        }

    def config_firmware(self) -> dict:
        c = self.config
        return {"pin": c["pin_servo"], "cerrado": c["angulo_cerrado"], "abierto": c["angulo_abierto"],
                "max_ms": int(float(c["apertura_max_s"]) * 1000)}

    def avisos(self) -> list[str]:
        if not self.config.get("calibrada"):
            return [f"{self.etiqueta} no está calibrada: los volúmenes pueden no ser exactos."]
        return []

    def descripcion_aperturas(self) -> str:
        tabla = self.tabla()
        return ", ".join(f"{pct:g} % → {self.caudal_nominal(tabla[pct]):.3f} mL/s" for pct in sorted(tabla, reverse=True))

    def calibracion_estado(self) -> list[str]:
        """Lo que ya está calibrado (se muestra al abrir la calibración)."""
        if not self.config.get("calibrada"):
            return ["Todavía sin calibrar: se usa un caudal supuesto."]
        lineas = [f"Aperturas calibradas (caudal con la bureta llena): {self.descripcion_aperturas()}."]
        puntos = sorted(self.tabla().items())
        if not self.config.get("caudal_continuo", True):
            lineas.append("Curva caudal-apertura desactivada: se usa la apertura calibrada más cercana al caudal pedido.")
        elif len(puntos) < 2:
            lineas.append("Calibre al menos una apertura parcial para poder regular el caudal.")
        elif self.curva() is None:
            lineas.append("Atención: una apertura menor dio más caudal que una mayor. Hasta corregir esa medición "
                          "no se usa la curva, solo la apertura calibrada más cercana.")
        else:
            lineas.append(f"Curva caudal-apertura activa entre {puntos[0][0]:g} % y 100 % con {len(puntos)} puntos"
                          + (". Con 4 o más puntos la estimación entre ellos es más confiable."
                             if len(puntos) < 4 else "."))
        return lineas

    def resumen(self) -> str:
        c = self.config
        disponible = self.estado.get("disponible_ml")
        nivel = ("No se sabe cuánto reactivo tiene" if disponible is None
                 else f"Tiene {disponible:.1f} de {c['capacidad_ml']:g} mL")
        return f"{nivel} · caudal: {self.descripcion_aperturas()}"

    # --- modelo físico -----------------------------------------------------
    def _altura(self, disponible: float) -> float:
        """Altura de líquido sobre la punta (mm) cuando en la bureta hay 'disponible' mL."""
        c = self.config
        return c["altura_base_mm"] + max(0.0, disponible) * c["mm_por_ml"]

    def _k(self, k: float | None) -> float:
        return float(self.config["caudal_k"]) if k is None else float(k)

    def caudal(self, disponible: float, k: float | None = None) -> float:
        """Caudal instantáneo (mL/s) con 'disponible' mL en la bureta."""
        return self._k(k) * math.sqrt(self._altura(disponible))

    def tiempo_para(self, volumen: float, disponible: float, k: float | None = None) -> float:
        """Segundos de apertura para entregar 'volumen' cuando hay 'disponible' mL."""
        h0, h1 = self._altura(disponible), self._altura(disponible - volumen)
        return 2.0 * (math.sqrt(h0) - math.sqrt(h1)) / (self.config["mm_por_ml"] * self._k(k))

    def volumen_en(self, segundos: float, disponible: float, k: float | None = None) -> float:
        """Mililitros que salen en 'segundos' de apertura cuando hay 'disponible' mL."""
        c = self.config
        raiz = math.sqrt(self._altura(disponible)) - segundos * c["mm_por_ml"] * self._k(k) / 2.0
        final = max(raiz, 0.0) ** 2
        return min(max(0.0, disponible), max(0.0, (self._altura(disponible) - final) / c["mm_por_ml"]))

    def duracion(self, accion: str, p: dict) -> float:
        if accion == "dosificar":
            disponible = self.estado.get("disponible_ml")
            try:
                _, k = self.elegir_apertura(p.get("caudal"))
                return self.tiempo_para(float(p["volumen"]),
                                        self.config["capacidad_ml"] if disponible is None else disponible, k) + 1.0
            except Exception:
                return 5.0
        return 1.0

    # --- qué hace -------------------------------------------------------
    def autotest(self) -> tuple[bool, str]:
        self.enlace.accion(self.id, "cerrar")
        if len(self.tabla()) > 1 or self.config.get("caudal_habitual"):
            try:
                self._exigir_parcial(50.0)
            except ErrorModulo as error:
                return False, str(error)
        return True, "Responde. Robinete cerrado."

    def ejecutar(self, accion: str, p: dict) -> dict:
        self.comprobar(accion, p)
        if accion == "dosificar":
            caudal = p.get("caudal")
            return self._dosificar(float(p["volumen"]), None if caudal in (None, "") else float(caudal))
        if accion == "abrir":
            apertura = float(p.get("apertura") or 100.0)
            self._exigir_parcial(apertura)
            self.estado["disponible_ml"] = None        # se pierde la cuenta del nivel
            self.guardar_estado()
            self.enlace.accion(self.id, "abrir", angulo=self._angulo(apertura))
        elif accion == "cerrar":
            self.enlace.accion(self.id, "cerrar")
        elif accion == "fijar_volumen":
            self.estado["disponible_ml"] = float(p["volumen"])
            self.guardar_estado()
        return {}

    def _campo_disponible(self, minimo: float = 0.0, valor: float | None = None) -> list[dict]:
        capacidad = float(self.config["capacidad_ml"])
        return [{"clave": "disponible", "etiqueta": f"Reactivo en la bureta (llena = {capacidad:g})",
                 "unidad": "mL", "valor": capacidad if valor is None else valor,
                 "min": round(minimo, 3), "max": capacidad}]

    def _dosificar(self, volumen: float, caudal: float | None = None) -> dict:
        c = self.config
        disponible = self.estado.get("disponible_ml")
        if disponible is None:
            raise NecesitaUsuario(
                f"No se sabe cuánto reactivo tiene {self.etiqueta}. Escriba cuántos mL hay en la bureta "
                f"(si está llena, {c['capacidad_ml']:g}).", self._campo_disponible(), "disponible")
        if volumen > disponible + 1e-9:
            raise NecesitaUsuario(
                f"{self.etiqueta} no tiene reactivo suficiente: hay {disponible:.1f} mL y esta dosis necesita "
                f"{volumen:.1f} mL. Recárguela y escriba cuántos mL de reactivo tiene ahora "
                f"(si la llenó, {c['capacidad_ml']:g}).", self._campo_disponible(minimo=volumen), "disponible")
        apertura, k = self.elegir_apertura(caudal)
        self._exigir_parcial(apertura)
        angulo = self._angulo(apertura)
        # Si la dosis pide más tiempo que la apertura máxima permitida, se entrega en
        # varias aperturas seguidas (el firmware nunca deja el robinete abierto más que ese máximo).
        tramo_max = 0.9 * float(c["apertura_max_s"]) - float(c["tiempo_muerto_s"])
        if tramo_max <= 0:
            raise ErrorModulo(f"{self.etiqueta}: la apertura máxima permitida es demasiado corta.")
        restante, total_s, aperturas = volumen, 0.0, 0
        while restante > 1e-6:
            parte = min(restante, self.volumen_en(tramo_max, disponible, k))
            if parte <= 1e-6 or aperturas >= 40:
                raise ErrorModulo(f"{self.etiqueta}: no se puede entregar {volumen:g} mL con el caudal elegido. "
                                  f"Use un caudal mayor o revise la calibración.")
            segundos = self.tiempo_para(parte, disponible, k) + float(c["tiempo_muerto_s"])
            try:
                self.enlace.accion(self.id, "abrir_por", ms=int(segundos * 1000), angulo=angulo,
                                   espera=segundos + 10)
            except ParadaEmergencia:
                self.estado["disponible_ml"] = None    # dosis interrumpida: nivel desconocido
                self.guardar_estado()
                raise
            disponible = round(disponible - parte, 3)
            self.estado["disponible_ml"] = disponible
            self.guardar_estado()
            restante -= parte
            total_s += segundos
            aperturas += 1
        medio = volumen / max(total_s, 1e-9)
        return {"volumen": volumen, "segundos": round(total_s, 2), "aperturas": aperturas,
                "apertura_pct": apertura, "caudal_medio": round(medio, 4),
                "nota": f"robinete al {apertura:g} % durante {total_s:.1f} s (caudal medio {medio:.3f} mL/s)"}

    def al_iniciar_campana(self, reactivo: str = "") -> NecesitaUsuario | None:
        que = f" de {reactivo}" if reactivo else " de reactivo"
        return NecesitaUsuario(
            f"Revise {self.etiqueta} y escriba cuántos mL{que} tiene ahora. "
            f"Si está llena, son {self.config['capacidad_ml']:g} mL.",
            self._campo_disponible(valor=self.estado.get("disponible_ml")), "disponible")

    def resolver(self, clave: str, respuesta: dict) -> None:
        if clave == "disponible":
            capacidad = float(self.config["capacidad_ml"])
            self.estado["disponible_ml"] = min(capacidad, max(0.0, float(respuesta["disponible"])))
            self.guardar_estado()

    def estado_seguro(self) -> None:
        self.enlace.accion(self.id, "cerrar")

    # --- calibración -------------------------------------------------------
    def _k_medido(self, inicial: float, salio: float, segundos: float) -> float:
        """Constante de caudal a partir de una medición: salieron 'salio' mL en 'segundos'."""
        c = self.config
        if inicial <= 0 or inicial > float(c["capacidad_ml"]) + 1e-9:
            raise ErrorModulo(f"El volumen inicial debe estar entre 0 y {c['capacidad_ml']:g} mL.")
        if salio <= 0 or salio > inicial + 1e-9:
            raise ErrorModulo("El volumen que salió debe ser mayor que cero y no superar lo que había en la bureta.")
        if segundos <= 0:
            raise ErrorModulo("El tiempo debe ser mayor que cero.")
        h0, h1 = self._altura(inicial), self._altura(inicial - salio)
        return 2.0 * (math.sqrt(h0) - math.sqrt(h1)) / (c["mm_por_ml"] * segundos)

    def _apertura_valida(self, datos: dict) -> float:
        apertura = float(datos.get("apertura") or 100.0)
        if not 5.0 <= apertura <= 100.0:
            raise ErrorModulo("La apertura debe estar entre 5 y 100 %.")
        return round(apertura, 1)

    def _informe_calibracion(self, apertura: float, k: float, salio: float, segundos: float) -> list[str]:
        """Lo que resulta de una calibración, en palabras: caudal y tiempos de apertura."""
        c = self.config
        capacidad = float(c["capacidad_ml"])
        dosis = [d for d in (0.5, 1.0, 5.0, 10.0, 20.0) if d <= capacidad]
        tiempos = ", ".join(f"{d:g} mL → {self.tiempo_para(d, capacidad, k) + c['tiempo_muerto_s']:.1f} s"
                            for d in dosis)
        lineas = [
            f"Apertura {apertura:g} %: caudal medio medido {salio / segundos:.3f} mL/s.",
            f"Con la bureta llena da {self.caudal(capacidad, k):.3f} mL/s; casi vacía, "
            f"{self.caudal(0.0, k):.3f} mL/s (baja a medida que baja el nivel).",
            f"Tiempo que se abrirá el robinete con esta apertura, partiendo de la bureta llena: {tiempos}.",
        ]
        previsto = self.k_en(apertura) if apertura not in self.tabla() else None
        if previsto:
            lineas.append(f"La curva actual preveía {self.caudal(capacidad, previsto):.3f} mL/s para esta apertura: "
                          f"lo medido difiere {abs(k / previsto - 1) * 100:.0f} %. Al guardar, la curva pasa por este punto.")
        completa = self.tabla().get(100.0)
        if apertura < 100.0 and c.get("calibrada") and k >= completa:
            lineas.append("Atención: esta apertura parcial dio más caudal que el robinete abierto del todo. "
                          "Revise la medición o vuelva a calibrar el 100 %.")
        return lineas

    def calibrar_previa(self, datos: dict) -> list[str]:
        """Calibración manual: muestra el resultado sin guardarlo."""
        inicial, salio, segundos = (float(datos[x]) for x in ("inicial", "salio", "segundos"))
        apertura = self._apertura_valida(datos)
        return self._informe_calibracion(apertura, self._k_medido(inicial, salio, segundos), salio, segundos)

    def calibrar_manual(self, datos: dict) -> str:
        """Calibración con el volumen y el tiempo medidos a mano por el usuario."""
        inicial, salio, segundos = (float(datos[x]) for x in ("inicial", "salio", "segundos"))
        return self._guardar_calibracion(self._apertura_valida(datos), inicial, salio, segundos)

    def calibrar_ejecutar(self, datos: dict) -> None:
        segundos = float(datos["segundos"])
        apertura = self._apertura_valida(datos)
        if not 0.5 <= segundos <= float(self.config["apertura_max_s"]):
            raise ErrorModulo("El tiempo de apertura debe estar entre 0,5 s y el máximo permitido.")
        self._exigir_parcial(apertura)
        self.estado["disponible_ml"] = None
        self.guardar_estado()
        self.enlace.accion(self.id, "abrir_por", ms=int(segundos * 1000), angulo=self._angulo(apertura),
                           espera=segundos + 10)

    def calibrar_aplicar(self, datos: dict) -> str:
        efectivo = float(datos["segundos"]) - float(self.config["tiempo_muerto_s"])
        return self._guardar_calibracion(self._apertura_valida(datos), float(datos["inicial"]),
                                         float(datos["salio"]), efectivo)

    def _guardar_calibracion(self, apertura: float, inicial: float, salio: float, segundos: float) -> str:
        c = self.config
        k = self._k_medido(inicial, salio, segundos)
        lineas = self._informe_calibracion(apertura, k, salio, segundos)
        if apertura >= 100.0:
            c["caudal_k"] = round(k, 6)
            c["calibrada"] = True
        else:
            otras = [par for par in (c.get("aperturas") or []) if round(float(par[0]), 1) != apertura]
            c["aperturas"] = sorted(otras + [[apertura, round(k, 6)]], key=lambda par: -par[0])
        self.estado["disponible_ml"] = round(inicial - salio, 3)
        self.guardar_estado()
        aviso = f" {lineas[-1]}" if lineas[-1].startswith("Atención") else ""
        return (f"Calibración guardada. Apertura {apertura:g} %: {self.caudal_nominal(k):.3f} mL/s con la bureta "
                f"llena. Aperturas calibradas: {self.descripcion_aperturas()}.{aviso}")

    def borrar_apertura(self, apertura: float) -> None:
        """Quita una apertura parcial calibrada (la de 100 % no se puede quitar)."""
        c = self.config
        c["aperturas"] = [par for par in (c.get("aperturas") or []) if round(float(par[0]), 1) != round(apertura, 1)]
