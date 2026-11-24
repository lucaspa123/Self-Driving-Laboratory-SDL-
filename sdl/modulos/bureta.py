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

SERVO DE ROTACIÓN CONTINUA: con "servo_continuo" activado el módulo usa el driver
servo_continuo del firmware. Ese servo no tiene posición (el pulso es la velocidad): el
ESP32 lo hace girar un tiempo calculado y lleva la cuenta de dónde cree que está el
robinete. No manda ningún pulso al conectar, y mientras no se le diga "el robinete está
cerrado" se niega a abrir. Todo lo demás (calibración, caudales, volúmenes) funciona igual.

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


CICLOS_AVISO = 30          # aperturas con servo continuo antes de pedir que se verifique el cierre


class Bureta(Modulo):
    TIPO = "bureta"
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
        "caudal_estimado": {"etiqueta": "Sin aperturas parciales calibradas: estimarlas (caudal proporcional a la "
                                        "apertura). Es aproximado; sirve para poder regular el caudal.",
                            "valor": False, "avanzado": True},
        "apertura_estimada_min": {"etiqueta": "Apertura mínima de la estimación", "valor": 25.0, "unidad": "%",
                                  "avanzado": True},
        "tiempo_muerto_s": {"etiqueta": "Tiempo muerto del servo", "valor": 0.15, "unidad": "s"},
        "calibrada": {"etiqueta": "Calibrada", "valor": False},
        "angulo_cerrado": {"etiqueta": "Ángulo del servo: cerrado", "valor": 0, "unidad": "°", "avanzado": True},
        "angulo_abierto": {"etiqueta": "Ángulo del servo: abierto del todo", "valor": 90, "unidad": "°",
                           "avanzado": True},
        "apertura_max_s": {"etiqueta": "Apertura máxima permitida", "valor": 60, "unidad": "s", "avanzado": True},
        "pin_servo": {"etiqueta": "Pin del servo (GPIO)", "valor": 13, "avanzado": True},
        "servo_continuo": {"etiqueta": "El servo es de rotación continua (gira por tiempo, sin posición)",
                           "valor": False, "avanzado": True},
        "servo_deg_por_s": {"etiqueta": "Servo continuo: grados que gira por segundo", "valor": 90.0,
                            "unidad": "°/s", "avanzado": True},
        "servo_vel_us": {"etiqueta": "Servo continuo: velocidad (cuánto se aparta el pulso del neutro)",
                         "valor": 150, "unidad": "µs", "avanzado": True},
        "servo_neutro_us": {"etiqueta": "Servo continuo: pulso con el servo quieto", "valor": 1500,
                            "unidad": "µs", "avanzado": True},
        "servo_sentido": {"etiqueta": "Servo continuo: sentido que abre (1, o -1 para invertirlo)", "valor": 1,
                          "avanzado": True},
        "servo_factor_cierre": {"etiqueta": "Servo continuo: corrección del tiempo de cierre (1 = igual que al abrir)",
                                "valor": 1.0, "avanzado": True},
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
        self._ref_driver: bool | None = None          # servo continuo: ¿el ESP32 sabe dónde está el robinete?
        # Versiones anteriores guardaban la lectura de la escala (0 = llena): se convierte una sola vez.
        if "lectura_ml" in self.estado:
            lectura = self.estado.pop("lectura_ml")
            if lectura is not None and "disponible_ml" not in self.estado:
                self.estado["disponible_ml"] = max(0.0, float(self.config["capacidad_ml"]) - float(lectura))

    # --- servo continuo ----------------------------------------------------------
    @property
    def continuo(self) -> bool:
        return bool(self.config.get("servo_continuo"))

    @property
    def DRIVER(self) -> str:                           # noqa: N802  (mismo nombre que en los demás módulos)
        return "servo_continuo" if self.continuo else "servo_valvula"

    def _recorrido(self) -> float:
        """Grados entre robinete cerrado y abierto del todo."""
        return abs(float(self.config["angulo_abierto"]) - float(self.config["angulo_cerrado"]))

    def _viaje_s(self, apertura: float) -> float:
        """Segundos que tarda el servo continuo en pasar de cerrado a esta apertura (%)."""
        return self._recorrido() * apertura / 100.0 / float(self.config["servo_deg_por_s"])

    def _minimo_s(self, apertura: float) -> float:
        """Tiempo equivalente de apertura mínimo: lo que dura el recorrido de ida y vuelta (la mitad de cada uno)."""
        return self._viaje_s(apertura) * (1.0 + float(self.config["servo_factor_cierre"])) / 2.0

    def _espera_s(self, apertura: float) -> float:
        """Tiempo extra que hay que esperar la respuesta del ESP32: recorrido de ida y de vuelta."""
        return self._viaje_s(apertura) * (1.0 + float(self.config["servo_factor_cierre"])) if self.continuo else 0.0

    def _nota_ref(self, r: dict | None) -> None:
        """Anota lo que el ESP32 contesta sobre la posición del robinete (servo continuo)."""
        if isinstance(r, dict) and "ref" in r:
            self._ref_driver = bool(r["ref"])

    def _exigir_ref(self) -> None:
        """El servo continuo solo se mueve si el ESP32 sabe dónde está el robinete."""
        if self.continuo and not getattr(self.enlace, "simulado", False) and self._ref_driver is False:
            raise ErrorModulo(f"{self.etiqueta}: no se sabe en qué posición está el robinete (el servo continuo no "
                              f"tiene sensor de posición). Ciérrelo a mano y use «Declarar el robinete cerrado» "
                              f"en «Usar manualmente».")

    def _anotar_cerrado(self, cerrado: bool, ciclo: bool = False, reiniciar: bool = False) -> None:
        """Guarda si el robinete quedó cerrado (así se reconoce solo la próxima vez que se conecte).

        'ciclo' cuenta una apertura más desde la última verificación; 'reiniciar' vuelve la cuenta a cero.
        """
        self.estado["servo_cerrado"] = bool(cerrado)
        if reiniciar:
            self.estado["servo_ciclos"] = 0
        elif ciclo:
            self.estado["servo_ciclos"] = int(self.estado.get("servo_ciclos", 0)) + 1
        self.guardar_estado()

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
        estimada = self.apertura_estimada()
        if estimada is not None and len(tabla) == 1:      # sin ninguna parcial medida: se supone caudal ∝ apertura
            tabla[estimada] = tabla[100.0] * estimada / 100.0
        return tabla

    def apertura_estimada(self) -> float | None:
        """Apertura (%) del punto estimado, si la estimación está activada y no hay parciales calibradas."""
        if not self.config.get("caudal_estimado") or any(
                0 < float(par[0]) < 100 for par in (self.config.get("aperturas") or []) if len(par) > 1):
            return None
        pct = float(self.config.get("apertura_estimada_min") or 25.0)
        return round(min(max(pct, 5.0), 95.0), 1)

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
        if self.continuo:                              # grados desde cerrado, no un ángulo del servo
            return round(self._recorrido() * apertura / 100.0, 2)
        return round(c["angulo_cerrado"] + (c["angulo_abierto"] - c["angulo_cerrado"]) * apertura / 100.0, 1)

    def _exigir_parcial(self, apertura: float) -> None:
        """Una apertura parcial solo se usa si el ESP32 tiene el driver que la entiende.

        Con el driver viejo el robinete se abriría del todo durante el tiempo calculado
        para un caudal chico, y entregaría mucho más de lo pedido.
        """
        if apertura >= 100.0 or getattr(self.enlace, "simulado", False) or self.continuo:
            return                                     # (el driver continuo siempre sabe abrir en parte)
        if self._parcial_ok is None:
            try:
                self._parcial_ok = bool(self.enlace.accion(self.id, "info").get("parcial"))
            except ErrorEnlace:
                self._parcial_ok = False
        if not self._parcial_ok:
            raise ErrorModulo(f"{self.etiqueta}: el ESP32 tiene una versión vieja del driver y no sabe abrir el "
                              f"robinete en parte. Copie firmware/drivers/{self.DRIVER}.py al ESP32 y reconecte.")

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
        acciones = {
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
        if self.continuo:
            acciones["declarar_cerrado"] = {
                "etiqueta": "Declarar que el robinete está cerrado ahora (servo continuo)", "parametros": {}}
            acciones["girar"] = {
                "etiqueta": "Girar el servo a mano, para alinear o medir (servo continuo)",
                "parametros": {"segundos": {"etiqueta": "Tiempo de giro (+ abre, − cierra)", "unidad": "s",
                                            "min": -3.0, "max": 3.0}}}
        return acciones

    def config_firmware(self) -> dict:
        c = self.config
        if self.continuo:
            return {"pin": c["pin_servo"], "recorrido": self._recorrido(),
                    "deg_por_s": float(c["servo_deg_por_s"]), "vel_us": int(c["servo_vel_us"]),
                    "neutro_us": int(c["servo_neutro_us"]), "sentido": 1 if float(c["servo_sentido"]) >= 0 else -1,
                    "factor_cierre": float(c["servo_factor_cierre"]),
                    "max_ms": int(float(c["apertura_max_s"]) * 1000)}
        return {"pin": c["pin_servo"], "cerrado": c["angulo_cerrado"], "abierto": c["angulo_abierto"],
                "max_ms": int(float(c["apertura_max_s"]) * 1000)}

    def avisos(self) -> list[str]:
        avisos = []
        if self.apertura_estimada() is not None:
            avisos.append(f"{self.etiqueta}: los caudales menores al 100 % son una estimación (no hay aperturas "
                          f"parciales calibradas): los volúmenes con caudal regulado son aproximados. "
                          f"Calibre una apertura parcial para mejorarlo.")
        if not self.config.get("calibrada"):
            avisos.append(f"{self.etiqueta} no está calibrada: los volúmenes pueden no ser exactos.")
        if self.continuo:
            if self._ref_driver is False and not getattr(self.enlace, "simulado", False):
                avisos.append(f"{self.etiqueta}: falta indicar que el robinete está cerrado (servo continuo). "
                              f"Úselo en «Usar manualmente → Declarar el robinete cerrado».")
            elif int(self.estado.get("servo_ciclos", 0)) >= CICLOS_AVISO:
                avisos.append(f"{self.etiqueta}: hace {self.estado['servo_ciclos']} aperturas que no se verifica el "
                              f"cierre. Un servo continuo acumula error: compruebe que el robinete cierra del todo y "
                              f"use «Declarar el robinete cerrado».")
        return avisos

    def descripcion_aperturas(self) -> str:
        tabla = self.tabla()
        estimada = self.apertura_estimada()
        return ", ".join(f"{pct:g} % → {self.caudal_nominal(tabla[pct]):.3f} mL/s"
                         + (" (estimado)" if pct == estimada else "") for pct in sorted(tabla, reverse=True))

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
                apertura, k = self.elegir_apertura(p.get("caudal"))
                return self.tiempo_para(float(p["volumen"]),
                                        self.config["capacidad_ml"] if disponible is None else disponible, k) + 1.0 \
                    + (self._espera_s(apertura) if self.continuo else 0.0)
            except Exception:
                return 5.0
        return 1.0

    # --- qué hace -------------------------------------------------------
    def _autotest_continuo(self) -> tuple[bool, str]:
        """No mueve el servo: solo pregunta qué sabe el ESP32 y, si hace falta, le informa dónde está el robinete."""
        if getattr(self.enlace, "simulado", False):
            self._ref_driver = True
            return True, "Responde (simulación)."
        info = self.enlace.accion(self.id, "info")
        if not info.get("continuo"):
            return False, (f"{self.etiqueta}: el driver del ESP32 no es el de servo continuo. Copie "
                           f"firmware/drivers/servo_continuo.py al ESP32 y reconecte.")
        self._nota_ref(info)
        if info.get("ref"):
            return True, "Responde. El servo no se movió."
        if self.estado.get("servo_cerrado"):            # el ESP32 se reinició, pero la última vez quedó cerrado
            self._nota_ref(self.enlace.accion(self.id, "referencia", pos=0.0))
            return True, "Responde. Robinete cerrado según el último uso (el servo no se movió)."
        return True, ("Responde, pero falta indicar la posición del robinete: ciérrelo a mano y use "
                      "«Declarar que el robinete está cerrado» en «Usar manualmente».")

    def autotest(self) -> tuple[bool, str]:
        if self.continuo:
            return self._autotest_continuo()
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
            self._exigir_ref()
            self.estado["disponible_ml"] = None        # se pierde la cuenta del nivel
            if self.continuo:
                self._anotar_cerrado(False)            # queda abierto: si el ESP32 se reinicia no se sabe dónde está
                self._nota_ref(self.enlace.accion(self.id, "abrir", angulo=self._angulo(apertura),
                                                  espera=5.0 + self._espera_s(apertura)))
            else:
                self.guardar_estado()
                self.enlace.accion(self.id, "abrir", angulo=self._angulo(apertura))
        elif accion == "cerrar":
            if self.continuo:
                r = self.enlace.accion(self.id, "cerrar", espera=5.0 + self._espera_s(100.0))
                self._nota_ref(r)
                if not getattr(self.enlace, "simulado", False) and not r.get("ref"):
                    raise ErrorModulo(f"{self.etiqueta}: no se sabe en qué posición está el robinete, así que no se "
                                      f"movió. Ciérrelo a mano y use «Declarar el robinete cerrado».")
                self._anotar_cerrado(True)
            else:
                self.enlace.accion(self.id, "cerrar")
        elif accion == "declarar_cerrado":
            if getattr(self.enlace, "simulado", False):
                self._ref_driver = True
            else:
                self._nota_ref(self.enlace.accion(self.id, "referencia", pos=0.0))
            self._anotar_cerrado(True, reiniciar=True)
        elif accion == "girar":
            segundos = float(p["segundos"])
            self._anotar_cerrado(False)                # movido a mano: ya no se sabe dónde está
            self._ref_driver = False
            self.enlace.accion(self.id, "girar", s=segundos, espera=abs(segundos) + 5.0)
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
        self._exigir_ref()
        angulo = self._angulo(apertura)
        # Si la dosis pide más tiempo que la apertura máxima permitida, se entrega en
        # varias aperturas seguidas (el firmware nunca deja el robinete abierto más que ese máximo).
        tramo_max = 0.9 * float(c["apertura_max_s"]) - float(c["tiempo_muerto_s"])
        if tramo_max <= 0:
            raise ErrorModulo(f"{self.etiqueta}: la apertura máxima permitida es demasiado corta.")
        partes = None
        if self.continuo:       # se planea todo antes de mover el servo: ninguna apertura puede quedar muy corta
            partes = self._partes_continuo(volumen, disponible, k, apertura, tramo_max)
        restante, total_s, aperturas = volumen, 0.0, 0
        while restante > 1e-6:
            if partes is None:
                parte = min(restante, self.volumen_en(tramo_max, disponible, k))
            else:
                parte = partes[aperturas] if aperturas < len(partes) else 0.0
            if parte <= 1e-6 or aperturas >= 40:
                raise ErrorModulo(f"{self.etiqueta}: no se puede entregar {volumen:g} mL con el caudal elegido. "
                                  f"Use un caudal mayor o revise la calibración.")
            segundos = self.tiempo_para(parte, disponible, k) + float(c["tiempo_muerto_s"])
            try:
                r = self.enlace.accion(self.id, "abrir_por", ms=int(segundos * 1000), angulo=angulo,
                                       espera=segundos + 10 + self._espera_s(apertura))
                self._nota_ref(r)
            except ParadaEmergencia:
                self.estado["disponible_ml"] = None    # dosis interrumpida: nivel desconocido
                self.guardar_estado()
                raise
            except ErrorEnlace:
                if self.continuo:                      # no se sabe cómo quedó el servo
                    self._anotar_cerrado(False)
                raise
            disponible = round(disponible - parte, 3)
            self.estado["disponible_ml"] = disponible
            self.guardar_estado()
            restante -= parte
            total_s += segundos
            aperturas += 1
            if self.continuo:
                self._anotar_cerrado(True, ciclo=True)
        medio = volumen / max(total_s, 1e-9)
        return {"volumen": volumen, "segundos": round(total_s, 2), "aperturas": aperturas,
                "apertura_pct": apertura, "caudal_medio": round(medio, 4),
                "nota": f"robinete al {apertura:g} % durante {total_s:.1f} s (caudal medio {medio:.3f} mL/s)"}

    def _partes_continuo(self, volumen: float, disponible: float, k: float, apertura: float,
                         tramo_max: float) -> list[float]:
        """Reparte la dosis en aperturas de igual duración y comprueba que cada una dure más que el recorrido.

        El servo continuo tarda en abrir y en cerrar; una apertura más corta que ese recorrido no se puede dar.
        Se reparte en partes iguales (y no "lo más posible y lo que sobre") para no dejar una última apertura
        diminuta.
        """
        c = self.config
        total = self.tiempo_para(volumen, disponible, k)
        n = max(1, math.ceil(total / tramo_max - 1e-9))
        if n > 40:
            raise ErrorModulo(f"{self.etiqueta}: no se puede entregar {volumen:g} mL con el caudal elegido. "
                              f"Use un caudal mayor o revise la calibración.")
        partes, restante, nivel = [], volumen, disponible
        for i in range(n):
            parte = restante if i == n - 1 else min(restante, self.volumen_en(total / n, nivel, k))
            partes.append(parte)
            restante -= parte
            nivel = round(nivel - parte, 3)
        minimo = self._minimo_s(apertura)
        nivel = disponible
        for parte in partes:
            segundos = self.tiempo_para(parte, nivel, k) + float(c["tiempo_muerto_s"])
            if segundos < minimo + 0.05:
                raise ErrorModulo(
                    f"{self.etiqueta}: esta dosis pide abrir el robinete solo {segundos:.2f} s, y el servo continuo "
                    f"tarda {self._viaje_s(apertura):.2f} s en abrirlo a ese {apertura:g} %. Dosifique un volumen "
                    f"mayor o con menos caudal, o acelere el servo (servo_vel_us) y vuelva a medir sus °/s.")
            nivel = round(nivel - parte, 3)
        return partes

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
        if self.continuo:                              # sin referencia el driver no se mueve: nada que hacer
            self._nota_ref(self.enlace.accion(self.id, "cerrar", espera=5.0 + self._espera_s(100.0)))
            return
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
        self._exigir_ref()
        if self.continuo and segundos < self._minimo_s(apertura) + 0.05:
            raise ErrorModulo(f"El servo continuo tarda {self._viaje_s(apertura):.2f} s en abrir a ese {apertura:g} %: "
                              f"elija un tiempo de apertura mayor que {self._minimo_s(apertura) + 0.05:.1f} s.")
        self.estado["disponible_ml"] = None
        self.guardar_estado()
        try:
            r = self.enlace.accion(self.id, "abrir_por", ms=int(segundos * 1000), angulo=self._angulo(apertura),
                                   espera=segundos + 10 + self._espera_s(apertura))
        except ErrorEnlace:
            if self.continuo:
                self._anotar_cerrado(False)
            raise
        self._nota_ref(r)
        if self.continuo:
            self._anotar_cerrado(True, ciclo=True)

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
