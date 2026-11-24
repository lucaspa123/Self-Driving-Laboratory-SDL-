"""Pantalla 4 — Ejecución: verificación previa, campaña en vivo y preguntas al usuario."""
from __future__ import annotations

import time

from nicegui import ui

from .. import seguridad
from ..modelos import Experimento, numero_txt, prediccion_txt
from ..motor import EJECUTANDO, INACTIVO, PARADA, PAUSADO, PROPONIENDO, TERMINADO, TEXTO_ESTADO, texto_paso
from ..optimizador import Optimizador
from .comunes import avisar, boton, confirmar, fila, nivel, numero, seccion, titulo
from .pantalla_informe import bloque_graficos


def pantalla_ejecucion(motor, exp: Experimento | None, refrescar, ir_a) -> None:
    titulo("Ejecución", "El programa propone un experimento, lo ejecuta, registra el resultado y vuelve a pensar. "
                        "Usted puede pausar, finalizar o detener todo en cualquier momento.")
    if motor.ocupado() or motor.estado == PARADA:
        _en_vivo(motor, refrescar)
    elif motor.estado == TERMINADO and motor.exp is not None:
        _terminada(motor, refrescar, ir_a)
    elif exp is None:
        with seccion("Sin experimento"):
            ui.label("Primero cree un experimento en el paso 2.").classes("sdl-ayuda")
    else:
        _previa(motor, exp, refrescar, ir_a)


# ------------------------------------------------------------------ antes de empezar
def _previa(motor, exp: Experimento, refrescar, ir_a) -> None:
    g = motor.gestor
    chequeos = motor.verificar(exp)
    errores = seguridad.hay_errores(chequeos)
    with seccion(f"Verificación previa de «{exp.nombre}»"):
        for c in chequeos:
            nivel(c.nivel, c.texto)
        if errores:
            ui.label("Hay que resolver los puntos marcados en rojo antes de iniciar.").classes("sdl-ayuda q-mt-sm")
            with ui.row().classes("gap-2"):
                boton("Ir a Equipo", lambda: ir_a("equipo"), "secundario")
                boton("Ir a Experimento", lambda: ir_a("experimento"), "texto")
                boton("Ir a Historial", lambda: ir_a("historial"), "texto")
            return
        usables, _ = motor.historial_de(exp).usables(exp)
        faltan = max(0, Optimizador(exp, 0).n_inicial() - len(usables))
        ui.label(f"Se harán hasta {exp.max_experimentos} experimentos. "
                 + (f"Los primeros {min(faltan, exp.max_experimentos)} serán de exploración (puntos bien "
                    f"repartidos para conocer el terreno); después el programa optimiza con lo aprendido."
                    if faltan else "Ya hay datos suficientes: el programa optimiza desde el primer experimento.")) \
            .classes("sdl-ayuda q-mt-sm")

    simulado = g.conectado() and g.enlace.simulado
    with seccion("Antes de empezar", "Confirme cada punto. Queda anotado en la bitácora."):
        casillas = []
        for ident, reactivo in exp.reactivos.items():
            if str(reactivo).strip() and ident in g.modulos:
                casillas.append(ui.checkbox(f"{g.modulos[ident].etiqueta} está cargada con: {reactivo}."))
        for punto in motor.seguridad.get("lista_previa", []):
            casillas.append(ui.checkbox(punto))
        demo = ui.switch("Demostración automática: el programa contesta solo, con una reacción inventada", value=False)
        demo.set_visibility(simulado)

        def iniciar():
            if not demo.value and not all(c.value for c in casillas):
                avisar("Confirme todos los puntos de la lista antes de iniciar.", "aviso")
                return
            if not demo.value:
                motor.bitacora.agregar("Lista previa confirmada por el usuario: " + " | ".join(c.text for c in casillas))
            try:
                motor.iniciar(exp, demo=bool(demo.value))
            except RuntimeError as error:
                avisar(str(error), "error")
                return
            refrescar()
        boton("Iniciar campaña", iniciar, "principal", "play_arrow").classes("q-mt-sm")


# ------------------------------------------------------------------ campaña terminada
def _terminada(motor, refrescar, ir_a) -> None:
    exp = motor.exp
    with seccion(f"Campaña terminada: «{exp.nombre}»"):
        nivel("error" if motor.error_fin else "ok", motor.motivo_fin or "Campaña finalizada.")
        ui.label(f"Se ejecutaron {motor.hechos} experimento(s) en esta campaña. El equipo quedó en estado seguro.") \
            .classes("sdl-ayuda")
        with ui.row().classes("gap-2 q-mt-sm"):
            boton("Ver el informe", lambda: ir_a("informe"), "principal", "description")

            def otra():
                motor.cerrar_campana()
                refrescar()
            boton("Preparar otra campaña", otra, "secundario")
    with seccion("Bitácora"):
        _bitacora(motor, 40)


# ------------------------------------------------------------------ campaña en vivo
def _bitacora(motor, cantidad: int = 14) -> None:
    with ui.column().classes("sdl-bitacora gap-0"):
        for hora, tipo, texto in reversed(motor.bitacora.ultimas(cantidad)):
            ui.label(f"{hora}  {texto}").classes(tipo if tipo in ("aviso", "error") else "")


def _en_vivo(motor, refrescar) -> None:
    exp, g = motor.exp, motor.gestor
    visto = {"clave": None, "filas": -1, "bitacora": -1, "ocupado": motor.ocupado(), "estado": motor.estado}
    barra = {"control": None}

    @ui.refreshable
    def cabecera():
        if exp is None:
            nivel("error", f"Parada de emergencia: {motor.motivo_parada or 'activada'}.")
            return
        estado = motor.estado
        if motor.solicitud is not None and estado != PARADA:
            texto_estado = "Esperando su respuesta"
        else:
            texto_estado = TEXTO_ESTADO.get(estado, estado)
        with ui.row().classes("items-end justify-between w-full"):
            with ui.column().classes("gap-0"):
                numero_actual = min(motor.hechos + 1, exp.max_experimentos)
                ui.label(f"Experimento {numero_actual} de {exp.max_experimentos}").classes("sdl-dato")
                ui.label(f"{exp.nombre} · {texto_estado}"
                         + (" · demostración automática" if motor.demo else "")).classes("sdl-ayuda")
            with ui.row().classes("gap-2").bind_visibility_from(motor, "estado", backward=lambda e: e != PARADA):
                if estado == PAUSADO or motor._pausa:
                    boton("Reanudar", motor.reanudar, "secundario", "play_arrow")
                else:
                    boton("Pausar", motor.pausar, "secundario", "pause").set_enabled(estado != PARADA)

                async def finalizar():
                    if await confirmar("¿Finalizar la campaña? El experimento en curso se completa y después se "
                                       "genera el informe.", "Finalizar"):
                        motor.finalizar()
                boton("Estoy conforme: finalizar", finalizar, "texto", "flag").set_enabled(estado != PARADA)
        if motor._pausa and estado != PAUSADO:
            nivel("info", "La pausa se hará efectiva al terminar el paso en curso.")
        if motor._finalizar:
            nivel("info", "La campaña finalizará al terminar el experimento en curso.")

    @ui.refreshable
    def pedido():
        s = motor.solicitud
        if s is None or motor.estado == PARADA:
            return
        with ui.column().classes("sdl-pedido q-mt-md"):
            ui.label(s.titulo).classes("t")
            if s.mensaje:
                ui.label(s.mensaje).style("white-space: pre-line; line-height: 1.5; max-width: 76ch")
            if s.vencida:
                nivel("aviso", "Pasó el tiempo de espera sin respuesta: el equipo se dejó en estado seguro "
                               "(agitación y bombas apagadas). Tenga en cuenta si eso afecta al experimento.")
            if s.propuesta is not None:
                _valores_propuesta(exp, s.propuesta)
            controles = {}
            if s.campos:
                with ui.row().classes("gap-3"):
                    for c in s.campos:
                        controles[c["clave"]] = numero(c["etiqueta"], c.get("valor"), c.get("unidad", ""),
                                                       c.get("min"), c.get("max"), ancho="w-64").props("bg-color=white")
            with ui.row().classes("gap-2 q-mt-xs"):
                for opcion in s.opciones:
                    async def responder(opcion=opcion):
                        valores = {k: c.value for k, c in controles.items()}
                        if opcion["clave"] == "no":
                            if not await confirmar("¿Confirma que la reacción no ocurrió? El experimento se anota "
                                                   "como fallido y el programa evitará esa zona.", "Sí, no ocurrió"):
                                return
                        elif opcion.get("principal") and any(v is None for v in valores.values()):
                            avisar("Escriba el valor antes de continuar.", "aviso")
                            return
                        for c in s.campos:
                            v = valores.get(c["clave"])
                            if v is not None and opcion.get("principal") and (
                                    (c.get("min") is not None and v < c["min"]) or (c.get("max") is not None and v > c["max"])):
                                avisar(f"{c['etiqueta']}: el valor debe estar entre {numero_txt(c['min'])} y "
                                       f"{numero_txt(c['max'])}.", "aviso")
                                return
                        motor.responder(opcion["clave"], valores)
                    boton(opcion["etiqueta"], responder, "principal" if opcion.get("principal") else "secundario")

    @ui.refreshable
    def detalle():
        if exp is None:
            return
        p = motor.propuesta
        with ui.element("div").style("display:grid; grid-template-columns: minmax(0,1fr) minmax(0,1.25fr); "
                                     "gap: 10px 36px; width:100%"):
            with ui.column().classes("gap-2 w-full"):
                ui.label("Condiciones de este experimento").classes("sdl-h2").style("font-size:15px")
                if p is None:
                    ui.label("Calculando la próxima propuesta…" if motor.estado == PROPONIENDO
                             else "Todavía no hay una propuesta.").classes("sdl-chico")
                elif motor.solicitud is not None and motor.solicitud.propuesta is not None:
                    ui.label("La propuesta está arriba, esperando su aprobación.").classes("sdl-chico")
                else:
                    _valores_propuesta(exp, p)
                    ui.label(p.motivo).classes("sdl-chico")
            with ui.column().classes("gap-1 w-full"):
                ui.label("Pasos").classes("sdl-h2").style("font-size:15px")
                en_marcha = motor.estado in (EJECUTANDO, PAUSADO) and motor.fila_actual is not None
                for i, paso in enumerate(exp.protocolo):
                    clase = ""
                    if en_marcha and i < motor.paso_actual:
                        clase = "hecho"
                    elif en_marcha and i == motor.paso_actual:
                        clase = "actual"
                    with ui.element("div").classes(f"sdl-paso {clase}"):
                        ui.label("✓" if clase == "hecho" else f"{i + 1}").classes("n")
                        ui.label(texto_paso(exp, paso, g, p.valores if p else None))
                barra["control"] = ui.linear_progress(0, show_value=False, size="4px").classes("q-mt-xs")
                barra["control"].set_visibility(False)

    @ui.refreshable
    def graficos():
        if exp is None:
            return
        usables, _ = motor.historial.usables(exp)
        analisis = Optimizador(exp, 0).analizar(usables)
        bloque_graficos(exp, usables, analisis)

    @ui.refreshable
    def bitacora():
        _bitacora(motor)

    with ui.column().classes("w-full gap-0 q-mt-lg"):
        cabecera()
        pedido()
    with seccion("Experimento en curso"):
        detalle()
    with seccion("Resultados hasta ahora"):
        graficos()
    with seccion("Bitácora", "Lo último que hizo el programa. El registro completo queda en datos/bitacora.txt."):
        bitacora()

    def tic():
        if motor.ocupado() != visto["ocupado"] or (motor.estado != visto["estado"]
                                                    and TERMINADO in (motor.estado, visto["estado"])) \
                or (motor.estado == INACTIVO):
            refrescar()                                   # cambió todo: se redibuja la pantalla
            return
        s = motor.solicitud
        clave = (motor.estado, motor.hechos, motor.fila_actual, motor.paso_actual, s.numero if s else 0,
                 bool(s and s.vencida), id(motor.propuesta), motor._pausa, motor._finalizar)
        if clave != visto["clave"]:
            cambio_pedido = visto["clave"] is None or clave[4:6] != visto["clave"][4:6] or clave[0] != visto["clave"][0]
            visto["clave"] = clave
            cabecera.refresh()
            detalle.refresh()
            if cambio_pedido:
                pedido.refresh()
        visto["estado"] = motor.estado
        n = len(motor.historial.filas()) if motor.historial is not None else 0
        terminados = (n, motor.fila_actual is None)
        if terminados != visto["filas"]:
            visto["filas"] = terminados
            graficos.refresh()
        if motor.bitacora.version != visto["bitacora"]:
            visto["bitacora"] = motor.bitacora.version
            bitacora.refresh()
        control = barra["control"]
        if control is not None:
            activo = motor.estado == EJECUTANDO and motor.paso_duracion > 1.0 and motor.solicitud is None
            control.set_visibility(activo)
            if activo:
                control.set_value(min(1.0, (time.time() - motor.paso_inicio) / motor.paso_duracion))
    ui.timer(0.5, tic)


def _valores_propuesta(exp: Experimento, propuesta) -> None:
    """Tabla corta: valor de cada variable y, si el modelo ya puede, el resultado que espera."""
    with ui.column().classes("gap-0 w-full").style("max-width: 520px"):
        for v in exp.variables:
            with fila("1fr auto"):
                ui.label(v.etiqueta)
                ui.label(f"{numero_txt(propuesta.valores.get(v.nombre))} {v.unidad}".strip()).style("font-weight:600")
        for o in exp.objetivos:
            if o.nombre in propuesta.prediccion:
                media, desvio = propuesta.prediccion[o.nombre]
                with fila("1fr auto"):
                    ui.label(f"{o.etiqueta} que espera el modelo").classes("sdl-chico")
                    ui.label(f"{prediccion_txt(media, desvio)} {o.unidad}".strip()).classes("sdl-chico")
