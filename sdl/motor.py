"""Motor de campañas: el bucle  proponer -> ejecutar -> medir -> aprender.

Corre en un hilo aparte de la interfaz. La interfaz solo lee el estado del
motor y le contesta las preguntas (Solicitud). Si se cierra el navegador, el
experimento en curso no queda a medias.

Una CAMPAÑA es una sesión de optimización: termina cuando se cumplen las
metas, cuando el químico la finaliza, cuando se llega al máximo de
experimentos o cuando hay una parada de emergencia.
"""
from __future__ import annotations

import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import seguridad
from .comunicacion import ErrorEnlace, ParadaEmergencia
from .historial import ABORTADO, COMPLETADO, EN_CURSO, FALLIDO, Historial
from .modelos import Experimento, Paso, es_referencia, identificador, listar_experimentos, numero_txt
from .modulos import ErrorModulo, GestorModulos, NecesitaUsuario
from .optimizador import Optimizador, Propuesta
from .registro import Bitacora
from .simulacion import ReaccionSimulada

INACTIVO, PREPARANDO, PROPONIENDO, EJECUTANDO, PAUSADO, PARADA, TERMINADO = (
    "inactivo", "preparando", "proponiendo", "ejecutando", "pausado", "parada", "terminado")

TEXTO_ESTADO = {
    INACTIVO: "Sin campaña en curso", PREPARANDO: "Preparando la campaña",
    PROPONIENDO: "Calculando el próximo experimento", EJECUTANDO: "Ejecutando el experimento",
    PAUSADO: "En pausa", PARADA: "PARADA DE EMERGENCIA", TERMINADO: "Campaña terminada",
}


@dataclass
class Solicitud:
    """Algo que el programa necesita del usuario. La interfaz lo muestra y contesta."""
    titulo: str
    mensaje: str = ""
    campos: list[dict] = field(default_factory=list)     # {"clave","etiqueta","unidad","valor","min","max"}
    opciones: list[dict] = field(default_factory=list)   # {"clave","etiqueta","principal": bool}
    propuesta: Propuesta | None = None                   # si es la aprobación de un experimento
    numero: int = 0                                      # identificador único
    vencida: bool = False                                # pasó el tiempo de espera sin respuesta

    def __post_init__(self):
        if not self.opciones:
            self.opciones = [{"clave": "ok", "etiqueta": "Listo, continuar", "principal": True}]


def texto_paso(exp: Experimento, paso: Paso, gestor: GestorModulos, valores: dict | None = None) -> str:
    """Describe un paso del protocolo en lenguaje simple."""
    def valor(x, unidad=""):
        u = f" {unidad}" if unidad else ""
        if es_referencia(x):
            v = exp.variable(x[1:])
            nombre = v.etiqueta if v else x[1:]
            if valores and x[1:] in valores:
                return f"{numero_txt(valores[x[1:]])}{u}"
            return f"[{nombre}]"
        return f"{numero_txt(x) if isinstance(x, (int, float)) else x}{u}"

    if paso.tipo == "accion":
        modulo = gestor.modulos.get(paso.modulo)
        if modulo is None:
            return f"{paso.modulo}: {paso.accion} (módulo no disponible)"
        d = modulo.acciones().get(paso.accion) or {}
        partes = [f"{dp.get('etiqueta', k).lower()} {valor(paso.parametros.get(k), dp.get('unidad', ''))}"
                  for k, dp in (d.get("parametros") or {}).items() if k in paso.parametros]
        detalle = f" — {', '.join(partes)}" if partes else ""
        return f"{modulo.etiqueta}: {d.get('etiqueta', paso.accion).lower()}{detalle}"
    if paso.tipo == "esperar":
        return f"Esperar {valor(paso.segundos, 's')}"
    if paso.tipo == "confirmar":
        return f"Acción manual: {paso.mensaje}"
    if paso.tipo == "ajuste_manual":
        v = exp.variable(paso.variable)
        if v is None:
            return f"Ajuste manual de {paso.variable}"
        return f"Ajuste manual: {v.etiqueta} = {valor('$' + v.nombre, v.unidad)}"
    if paso.tipo == "medir":
        o = exp.objetivo(paso.objetivo)
        if o is None:
            return f"Medir {paso.objetivo}"
        modo = "automático" if o.medicion == "modulo" else "lo ingresa el usuario"
        return f"Medir {o.etiqueta} ({modo})"
    return paso.tipo


class Motor:
    def __init__(self, base: Path):
        self.base = Path(base)
        self.carpeta_config = self.base / "config"
        self.carpeta_experimentos = self.base / "datos" / "experimentos"
        self.carpeta_reacciones = self.base / "datos" / "reacciones"
        self.bitacora = Bitacora(self.base / "datos" / "bitacora.txt")
        self.gestor = GestorModulos(self.carpeta_config, registrar=self.bitacora.agregar)
        self.gestor.al_evento = self._evento
        self.seguridad = seguridad.cargar_config(self.carpeta_config)
        self._historiales: dict[str, Historial] = {}
        self._candado = threading.RLock()
        self._hilo: threading.Thread | None = None
        self._abortar = threading.Event()
        self._respuesta_lista = threading.Event()
        self._respuesta: dict | None = None
        self._contador = 0
        self._limpiar()
        self.estado = INACTIVO

    def _limpiar(self) -> None:
        self.exp: Experimento | None = None
        self.historial: Historial | None = None
        self.optimizador: Optimizador | None = None
        self.simulador: ReaccionSimulada | None = None
        self.demo = False
        self.campana = ""
        self.hechos = 0                    # experimentos ejecutados en esta campaña
        self.propuesta: Propuesta | None = None
        self.fila_actual: int | None = None
        self.paso_actual = -1
        self.paso_inicio = 0.0
        self.paso_duracion = 0.0
        self.solicitud: Solicitud | None = None
        self.motivo_fin = ""
        self.motivo_parada = ""
        self.error_fin = False
        self.ruta_informe: Path | None = None
        self.version = 0                   # cambia cuando hay algo nuevo para mostrar
        self._pausa = False
        self._finalizar = False
        self._excluir: list[dict] = []
        self._repetir: dict | None = None
        self._estancamiento_desde = 0

    # ------------------------------------------------------------------ datos
    def experimentos(self) -> list[Experimento]:
        return listar_experimentos(self.carpeta_experimentos)

    def guardar_experimento(self, exp: Experimento) -> None:
        exp.guardar(self.carpeta_experimentos)

    def borrar_experimento(self, exp: Experimento) -> None:
        ruta = self.carpeta_experimentos / f"{exp.id}.yaml"
        if ruta.exists():
            ruta.unlink()

    def carpeta_reaccion(self, exp: Experimento) -> Path:
        return self.carpeta_reacciones / identificador(exp.reaccion or exp.id)

    def historial_de(self, exp: Experimento) -> Historial:
        """Historial de la reacción del experimento (compartido entre pantallas)."""
        ruta = self.carpeta_reaccion(exp) / "historial.csv"
        clave = str(ruta)
        with self._candado:
            if clave not in self._historiales:
                historial = Historial(ruta)
                cerrados = historial.cerrar_interrumpidos()
                if cerrados:
                    self.bitacora.agregar(f"Historial de «{exp.reaccion or exp.id}»: {cerrados} experimento(s) "
                                          f"que quedaron a medias se marcaron como abortados.", "aviso")
                self._historiales[clave] = historial
            return self._historiales[clave]

    def verificar(self, exp: Experimento) -> list[seguridad.Chequeo]:
        return seguridad.verificar(exp, self.gestor, self.historial_de(exp), self.seguridad)

    def analizar(self, exp: Experimento) -> dict:
        filas, _ = self.historial_de(exp).usables(exp)
        return Optimizador(exp, 0).analizar(filas)

    # ------------------------------------------------------------------ control
    def ocupado(self) -> bool:
        return self._hilo is not None and self._hilo.is_alive()

    def iniciar(self, exp: Experimento, demo: bool = False) -> None:
        """Arranca una campaña. 'demo' (solo en simulación) contesta sola las preguntas."""
        if self.ocupado():
            raise RuntimeError("Ya hay una campaña en curso.")
        if self.estado == PARADA:
            raise RuntimeError("Hay una parada de emergencia activa. Rearme el sistema primero.")
        self._limpiar()
        self._abortar.clear()
        self.exp = exp
        self.demo = bool(demo) and self.gestor.conectado() and self.gestor.enlace.simulado
        self.historial = self.historial_de(exp)
        self.campana = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.estado = PREPARANDO
        self._hilo = threading.Thread(target=self._campana, name="campana", daemon=True)
        self._hilo.start()

    def pausar(self) -> None:
        self._pausa = True
        self.bitacora.agregar("Pausa pedida: se detendrá al terminar el paso en curso.")

    def reanudar(self) -> None:
        self._pausa = False
        self.bitacora.agregar("Se reanuda la campaña.")

    def finalizar(self) -> None:
        """El usuario está satisfecho: termina después del experimento en curso."""
        self._finalizar = True
        self._pausa = False
        self.bitacora.agregar("El usuario pidió finalizar la campaña al terminar el experimento en curso.")
        if self.solicitud is not None and self.solicitud.propuesta is not None:
            self.responder("finalizar")

    def responder(self, opcion: str = "ok", valores: dict | None = None) -> None:
        """La interfaz contesta la solicitud pendiente."""
        if self.solicitud is None:
            return
        self._respuesta = {"opcion": opcion, "valores": dict(valores or {})}
        self._respuesta_lista.set()

    def parada(self, motivo: str = "Botón de la pantalla") -> None:
        """PARADA DE EMERGENCIA: corta todo de inmediato y deja el equipo en estado seguro."""
        if self.estado == PARADA and self._abortar.is_set():
            return                                           # ya está en parada
        self.motivo_parada = motivo
        self._abortar.set()
        enlace = self.gestor.enlace
        if enlace is not None:
            enlace.parar()                                   # no espera turno: va directo al ESP32
        self.bitacora.agregar(f"PARADA DE EMERGENCIA ({motivo}).", "error")
        self.estado = PARADA
        self._respuesta_lista.set()                          # destraba cualquier espera
        self.version += 1

    def rearmar(self) -> tuple[bool, str]:
        """Después de una parada: vuelve a habilitar el equipo (lo decide una persona)."""
        if self.ocupado():
            self._hilo.join(timeout=5)
        try:
            if self.gestor.enlace is not None:
                estado = self.gestor.enlace.enviar("estado")
                if estado.get("boton"):
                    return False, "El botón físico de parada sigue apretado. Libérelo primero."
                self.gestor.enlace.enviar("rearmar")
        except Exception as error:
            return False, f"No se pudo rearmar: {error}"
        self._abortar.clear()
        self.motivo_parada = ""
        self.estado = TERMINADO if self.exp is not None else INACTIVO
        if self.exp is not None and not self.motivo_fin:
            self.motivo_fin = "Campaña interrumpida por una parada de emergencia."
        self.bitacora.agregar("Sistema rearmado por el usuario.", "aviso")
        self.version += 1
        return True, "Sistema rearmado."

    def cerrar_campana(self) -> None:
        """Deja el motor listo para preparar otra campaña (la anterior ya terminó)."""
        if not self.ocupado() and self.estado == TERMINADO:
            self._limpiar()
            self.estado = INACTIVO

    def _evento(self, evento: dict) -> None:
        """Eventos espontáneos del ESP32 (botón de parada, desconexión)."""
        if evento.get("ev") == "aviso":
            self.bitacora.agregar(f"Aviso del ESP32: {evento.get('texto', evento)}", "aviso")
        elif evento.get("ev") == "parada":
            self.parada(f"ESP32: {evento.get('motivo', 'parada')}")
        elif evento.get("ev") == "desconexion":
            if self.ocupado():
                self.parada("Se perdió la conexión con el ESP32")

    # ------------------------------------------------------------------ esperas
    def _punto_de_control(self) -> None:
        """Entre pasos: atiende la pausa y la parada de emergencia."""
        if self._abortar.is_set():
            raise ParadaEmergencia(self.motivo_parada or "parada")
        if self._pausa:
            anterior, self.estado = self.estado, PAUSADO
            self.version += 1
            while self._pausa:
                if self._abortar.wait(0.2):
                    raise ParadaEmergencia(self.motivo_parada or "parada")
            self.estado = anterior
            self.version += 1

    def _aceleracion(self) -> float:
        enlace = self.gestor.enlace
        return float(getattr(enlace, "aceleracion", 1.0)) if enlace is not None and enlace.simulado else 1.0

    def _dormir(self, segundos: float) -> None:
        if self._abortar.wait(max(0.0, segundos) / self._aceleracion()):
            raise ParadaEmergencia(self.motivo_parada or "parada")

    def _preguntar(self, solicitud: Solicitud, automatica: dict | None = None) -> dict:
        """Muestra una solicitud y espera la respuesta del usuario.

        En modo demo contesta sola con 'automatica'. Si nadie responde en el
        tiempo configurado, deja todos los actuadores en estado seguro y sigue esperando.
        """
        if self.demo and automatica is not None:
            self._dormir(2.0)
            return automatica
        self._contador += 1
        solicitud.numero = self._contador
        self._respuesta, self.solicitud = None, solicitud
        self._respuesta_lista.clear()
        self.version += 1
        self.bitacora.agregar(f"Esperando al usuario: {solicitud.titulo}.")
        limite = time.time() + float(self.seguridad.get("tiempo_espera_usuario_s", 900))
        try:
            while not self._respuesta_lista.wait(0.2):
                if not solicitud.vencida and time.time() > limite:
                    solicitud.vencida = True
                    errores = self.gestor.todos_seguros()
                    self.bitacora.agregar("Sin respuesta del usuario: se dejó todo en estado seguro "
                                          "mientras se espera." + (f" ({'; '.join(errores)})" if errores else ""),
                                          "aviso")
                    self.version += 1
            if self._abortar.is_set():
                raise ParadaEmergencia(self.motivo_parada or "parada")
            respuesta = self._respuesta or {"opcion": "ok", "valores": {}}
            return respuesta
        finally:
            self.solicitud = None
            self.version += 1

    # ------------------------------------------------------------------ campaña
    def _campana(self) -> None:
        exp = self.exp
        try:
            self.bitacora.agregar(f"=== Inicio de campaña «{exp.nombre}» ({self.gestor.enlace.descripcion}"
                                  f"{', demostración automática' if self.demo else ''}) ===")
            chequeos = seguridad.verificar(exp, self.gestor, self.historial, self.seguridad)
            if seguridad.hay_errores(chequeos):
                errores = [c.texto for c in chequeos if c.nivel == seguridad.ERROR]
                self._terminar("No se pudo iniciar: " + " ".join(errores), error=True)
                return
            limite_vaso = float(self.seguridad.get("llenado_maximo", 0.8)) * float(exp.capacidad_vaso_ml)
            self.optimizador = Optimizador(
                exp, factible=lambda v: seguridad.volumen_total(exp, self.gestor, v) <= limite_vaso + 1e-9)
            self.simulador = ReaccionSimulada(exp) if self.demo else None
            self._preparar_modulos()

            while True:
                self._punto_de_control()
                if self._finalizar:
                    motivo = "El usuario dio por terminada la campaña."
                    break
                if self.hechos >= exp.max_experimentos:
                    motivo = f"Se alcanzó el máximo de {exp.max_experimentos} experimentos."
                    break
                propuesta = self._proponer()
                if propuesta is None:
                    motivo = ("El usuario dio por terminada la campaña." if self._finalizar else
                              "No quedan combinaciones de variables posibles para ensayar.")
                    break
                self._ejecutar_experimento(propuesta)
                self.hechos += 1
                motivo = self._evaluar()
                if motivo:
                    break
            self._terminar(motivo)
        except ParadaEmergencia:
            # El ESP32 ya cortó todo al recibir la parada; acá solo se deja constancia.
            self._cerrar_abortado("Interrumpido por parada de emergencia.")
            self.estado = PARADA
            self.motivo_fin = f"Parada de emergencia: {self.motivo_parada or 'activada'}."
            self.propuesta, self.paso_actual = None, -1
            self.bitacora.agregar("Campaña detenida por parada de emergencia.", "error")
            self.version += 1
        except (ErrorEnlace, ErrorModulo) as error:
            self._cerrar_abortado(f"Interrumpido por un error: {error}")
            self._terminar(f"La campaña se detuvo por un error del equipo: {error}", error=True)
        except Exception as error:                          # un error de programa nunca deja actuadores encendidos
            self._cerrar_abortado(f"Interrumpido por un error inesperado: {error}")
            self._terminar(f"La campaña se detuvo por un error inesperado: {error!r}", error=True)

    def _terminar(self, motivo: str, error: bool = False) -> None:
        errores = self.gestor.todos_seguros() if self.gestor.enlace is not None else []
        self.motivo_fin, self.error_fin = motivo, error
        self.propuesta, self.paso_actual = None, -1
        self.bitacora.agregar(f"=== Fin de campaña: {motivo} ===", "error" if error else "info")
        for texto in errores:
            self.bitacora.agregar(f"Al dejar el equipo seguro: {texto}", "aviso")
        try:
            from .informe import generar_informe
            self.ruta_informe = generar_informe(
                self.exp, self.historial, self.carpeta_reaccion(self.exp) / "informes", motivo_fin=motivo,
                campana=self.campana, pasos=[texto_paso(self.exp, p, self.gestor) for p in self.exp.protocolo])
            self.bitacora.agregar(f"Informe generado: {self.ruta_informe.name}")
        except Exception as fallo:
            self.bitacora.agregar(f"No se pudo generar el informe: {fallo!r}", "aviso")
        self.estado = TERMINADO
        self.version += 1

    def _cerrar_abortado(self, nota: str) -> None:
        if self.fila_actual is not None and self.historial is not None:
            fila = self.historial.fila(self.fila_actual)
            if fila and fila["estado"] == EN_CURSO:
                self.historial.actualizar(self.fila_actual, estado=ABORTADO, notas=nota)
        self.fila_actual = None

    # ------------------------------------------------------------------ etapas
    def _modulos_usados(self) -> list[str]:
        usados = []
        for paso in self.exp.protocolo:
            if paso.tipo == "accion" and paso.modulo not in usados:
                usados.append(paso.modulo)
        for o in self.exp.objetivos:
            if o.medicion == "modulo" and o.modulo not in usados:
                usados.append(o.modulo)
        return [m for m in usados if m in self.gestor.modulos]

    def _preparar_modulos(self) -> None:
        """Lo que cada módulo necesita saber antes de empezar (p. ej. nivel de las buretas)."""
        for ident in self._modulos_usados():
            modulo = self.gestor.modulos[ident]
            pedido = modulo.al_iniciar_campana(str(self.exp.reactivos.get(ident, "")))
            if pedido is not None:
                self._atender(modulo, pedido, "Preparación")

    def _atender(self, modulo, pedido: NecesitaUsuario, titulo: str) -> None:
        automatica = {"opcion": "ok", "valores": {c["clave"]: c.get("valor", 0.0) for c in pedido.campos}}
        respuesta = self._preguntar(Solicitud(f"{titulo}: {modulo.etiqueta}", pedido.mensaje,
                                              campos=pedido.campos), automatica)
        modulo.resolver(pedido.clave, respuesta["valores"])
        informado = ", ".join(f"{c['etiqueta']} = {numero_txt(respuesta['valores'].get(c['clave']))} "
                              f"{c.get('unidad', '')}".strip() for c in pedido.campos)
        self.bitacora.agregar(f"{modulo.etiqueta}: el usuario informó {informado}.")

    def _proponer(self) -> Propuesta | None:
        exp = self.exp
        self.estado, self.propuesta = PROPONIENDO, None
        self.version += 1
        if self._repetir is not None:
            valores, self._repetir = self._repetir, None
            return Propuesta(valores, "repeticion", "Repetición del experimento anterior para confirmar el resultado.")
        for _ in range(25):
            filas, _motivos = self.historial.usables(exp)
            propuesta = self.optimizador.proponer(filas, self._excluir)
            if propuesta is None:
                return None
            problemas = seguridad.comprobar_propuesta(exp, self.gestor, propuesta.valores, self.seguridad)
            if problemas:                                  # capa 3 de seguridad: nunca se ejecuta
                self.bitacora.agregar("Propuesta descartada por seguridad: " + " ".join(problemas), "aviso")
                self._excluir.append(propuesta.valores)
                continue
            self.propuesta = propuesta
            self.version += 1
            self.bitacora.agregar(f"Propuesta ({propuesta.fase}): " + ", ".join(
                f"{v.etiqueta} = {numero_txt(propuesta.valores[v.nombre])} {v.unidad}".strip()
                for v in exp.variables))
            if exp.supervisado:
                respuesta = self._preguntar(Solicitud(
                    f"Experimento {self.hechos + 1} de {exp.max_experimentos}: ¿ejecutar esta propuesta?",
                    propuesta.motivo, propuesta=propuesta,
                    opciones=[{"clave": "aprobar", "etiqueta": "Aprobar y ejecutar", "principal": True},
                              {"clave": "otra", "etiqueta": "Proponer otra"},
                              {"clave": "finalizar", "etiqueta": "Finalizar la campaña"}]),
                    {"opcion": "aprobar", "valores": {}})
                if respuesta["opcion"] == "otra":
                    self.bitacora.agregar("El usuario rechazó la propuesta y pidió otra.")
                    self._excluir.append(propuesta.valores)
                    continue
                if respuesta["opcion"] == "finalizar":
                    self._finalizar = True
                    return None
            return propuesta
        return None

    def _texto(self, mensaje: str, valores: dict) -> str:
        """Reemplaza $variable por su valor en los mensajes de pasos manuales."""
        def cambio(m):
            v = self.exp.variable(m.group(1))
            if v is None or v.nombre not in valores:
                return m.group(0)
            return f"{numero_txt(valores[v.nombre])} {v.unidad}".strip()
        return re.sub(r"\$([A-Za-z_][A-Za-z0-9_]*)", cambio, mensaje or "")

    def _ejecutar_experimento(self, propuesta: Propuesta) -> None:
        exp, valores = self.exp, propuesta.valores
        self.propuesta = propuesta
        n = self.historial.agregar(valores, estado=EN_CURSO, origen=propuesta.fase, campana=self.campana)
        self.fila_actual = n
        self.estado = EJECUTANDO
        self.bitacora.agregar(f"--- Experimento {n} (n.º {self.hechos + 1} de la campaña) ---")
        resultados: dict = {}
        ocurrio: bool | None = None                       # todavía no se sabe
        for i, paso in enumerate(exp.protocolo):
            self._punto_de_control()
            self.paso_actual, self.paso_inicio = i, time.time()
            self.paso_duracion = 0.0
            self.version += 1
            descripcion = texto_paso(exp, paso, self.gestor, valores)
            if paso.tipo == "accion":
                modulo = self.gestor.modulos[paso.modulo]
                p = {k: seguridad.resolver(x, valores) for k, x in paso.parametros.items()}
                self.paso_duracion = modulo.duracion(paso.accion, p) / self._aceleracion()
                self.bitacora.agregar(f"Paso {i + 1}: {descripcion}")
                for _intento in range(6):
                    try:
                        resultado = modulo.ejecutar(paso.accion, p)
                        if isinstance(resultado, dict) and resultado.get("nota"):
                            self.bitacora.agregar(f"         {modulo.etiqueta}: {resultado['nota']}.")
                        break
                    except NecesitaUsuario as pedido:
                        self._atender(modulo, pedido, "Hace falta su ayuda")
                        self.paso_inicio = time.time()
                else:
                    raise ErrorModulo(f"{modulo.etiqueta} no pudo completar «{paso.accion}».")
            elif paso.tipo == "esperar":
                segundos = float(seguridad.resolver(paso.segundos, valores))
                self.paso_duracion = segundos / self._aceleracion()
                self.bitacora.agregar(f"Paso {i + 1}: {descripcion}")
                self._dormir(segundos)
            elif paso.tipo == "confirmar":
                self.bitacora.agregar(f"Paso {i + 1}: {descripcion}")
                self._preguntar(Solicitud("Acción manual", self._texto(paso.mensaje, valores)),
                                {"opcion": "ok", "valores": {}})
            elif paso.tipo == "ajuste_manual":
                v = exp.variable(paso.variable)
                self.bitacora.agregar(f"Paso {i + 1}: {descripcion}")
                extra = f"\n{self._texto(paso.mensaje, valores)}" if paso.mensaje else ""
                self._preguntar(Solicitud(
                    "Ajuste manual",
                    f"Ajuste {v.etiqueta} a {numero_txt(valores[v.nombre])} {v.unidad} y confirme.{extra}",
                    opciones=[{"clave": "ok", "etiqueta": "Ya lo ajusté", "principal": True}]),
                    {"opcion": "ok", "valores": {}})
            elif paso.tipo == "medir":
                if ocurrio is False:
                    continue                                # la reacción no ocurrió: no hay nada que medir
                o = exp.objetivo(paso.objetivo)
                valor, ocurrio = self._medir(o, valores, ocurrio)
                if valor is not None:
                    resultados[o.nombre] = valor
                    self.historial.actualizar(n, resultados={o.nombre: valor})
                    self.bitacora.agregar(f"Paso {i + 1}: {o.etiqueta} = {numero_txt(valor)} {o.unidad}".strip())
                else:
                    self.bitacora.agregar(f"Paso {i + 1}: el usuario indicó que la reacción no ocurrió.", "aviso")
        self.paso_actual = len(exp.protocolo)

        registros = {}
        for r in exp.registros:
            modulo = self.gestor.modulos.get(r.get("modulo"))
            if modulo is None:
                continue
            try:
                registros[f"{r['modulo']}.{r['magnitud']}"] = modulo.medir(r["magnitud"])
            except (ErrorEnlace, ErrorModulo) as error:
                self.bitacora.agregar(f"No se pudo registrar {r['magnitud']} de {modulo.etiqueta}: {error}", "aviso")

        if ocurrio is False:
            self.historial.actualizar(n, estado=FALLIDO, registros=registros,
                                      notas="La reacción no ocurrió (penalizado).")
            self.bitacora.agregar(f"Experimento {n}: la reacción no ocurrió. Se penaliza esa zona.", "aviso")
        else:
            self.historial.actualizar(n, estado=COMPLETADO, resultados=resultados, registros=registros)
            self.bitacora.agregar(f"Experimento {n} completado: " + ", ".join(
                f"{o.etiqueta} = {numero_txt(resultados.get(o.nombre))} {o.unidad}".strip() for o in exp.objetivos))
        self.fila_actual = None
        for texto in self.gestor.todos_seguros():          # nada queda encendido entre experimentos
            self.bitacora.agregar(f"Al dejar el equipo seguro: {texto}", "aviso")
        self.version += 1

    def _medir(self, o, valores: dict, ocurrio: bool | None) -> tuple[float | None, bool]:
        """Devuelve (valor, ocurrió). valor es None si la reacción no ocurrió."""
        no_ocurrio = {"clave": "no", "etiqueta": "La reacción no ocurrió"}
        if self.demo:
            if ocurrio is None:
                ocurrio = self.simulador.ocurre(valores)
            self._dormir(2.0)
            return (self.simulador.valor(o.nombre, valores), True) if ocurrio else (None, False)
        if o.medicion == "modulo":
            if ocurrio is None:
                respuesta = self._preguntar(Solicitud(
                    "¿Ocurrió la reacción?",
                    "Observe el vaso. Si la reacción no ocurrió, el experimento se anota como fallido "
                    "y el optimizador evitará esa zona.",
                    opciones=[{"clave": "si", "etiqueta": "Sí, ocurrió", "principal": True}, no_ocurrio]))
                if respuesta["opcion"] == "no":
                    return None, False
            modulo = self.gestor.modulos[o.modulo]
            return float(modulo.medir(o.magnitud)), True
        campo = {"clave": o.nombre, "etiqueta": o.etiqueta, "unidad": o.unidad, "valor": None}
        respuesta = self._preguntar(Solicitud(
            f"Medición: {o.etiqueta}",
            f"Mida {o.etiqueta} y escriba el resultado. Objetivo: {o.texto_meta()}.",
            campos=[campo],
            opciones=[{"clave": "ok", "etiqueta": "Guardar resultado", "principal": True}, no_ocurrio]))
        if respuesta["opcion"] == "no":
            return None, False
        return float(respuesta["valores"][o.nombre]), True

    def _evaluar(self) -> str:
        """Después de cada experimento: ¿se cumplieron las metas? ¿hay estancamiento?

        Devuelve el motivo de finalización, o '' para seguir.
        """
        exp = self.exp
        filas, _ = self.historial.usables(exp)
        analisis = self.optimizador.analizar(filas)
        ultimo = filas[-1]["n"] if filas else None
        if ultimo is not None and ultimo in analisis["cumplen"]:
            self.bitacora.agregar(f"El experimento {ultimo} cumple todas las metas.")
            respuesta = self._preguntar(Solicitud(
                "Se cumplieron las metas",
                f"El experimento {ultimo} cumple todas las metas fijadas. Una medición puede tener suerte: "
                "repetir el experimento confirma el resultado.",
                opciones=[{"clave": "finalizar", "etiqueta": "Finalizar la campaña", "principal": True},
                          {"clave": "repetir", "etiqueta": "Repetir para confirmar"},
                          {"clave": "seguir", "etiqueta": "Seguir optimizando"}]),
                {"opcion": "finalizar", "valores": {}})
            if respuesta["opcion"] == "finalizar":
                return f"Se cumplieron las metas en el experimento {ultimo}."
            if respuesta["opcion"] == "repetir":
                self._repetir = dict(filas[-1]["variables"])
            return ""
        paciencia = int(exp.paciencia or 0)
        avance = analisis["hipervolumen"]
        if paciencia > 0 and self.hechos - self._estancamiento_desde >= paciencia and len(avance) > paciencia \
                and avance[-1] - avance[-1 - paciencia] <= 1e-9:
            self.bitacora.agregar(f"Sin mejora en los últimos {paciencia} experimentos.", "aviso")
            respuesta = self._preguntar(Solicitud(
                "No hay mejora",
                f"Los últimos {paciencia} experimentos no mejoraron los resultados.",
                opciones=[{"clave": "seguir", "etiqueta": "Seguir un poco más", "principal": True},
                          {"clave": "finalizar", "etiqueta": "Finalizar la campaña"}]),
                {"opcion": "finalizar", "valores": {}})
            if respuesta["opcion"] == "finalizar":
                return f"Sin mejora en los últimos {paciencia} experimentos."
            self._estancamiento_desde = self.hechos
        return ""
