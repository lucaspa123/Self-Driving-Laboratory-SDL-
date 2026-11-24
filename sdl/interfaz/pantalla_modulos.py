"""Pantalla 1 — Equipo: conexión, módulos instalados, calibración y uso manual."""
from __future__ import annotations

import yaml
from nicegui import run, ui

from ..comunicacion import ErrorEnlace, ParadaEmergencia, puertos_disponibles
from ..modelos import escribir_yaml, identificador
from ..modulos import ErrorModulo, NecesitaUsuario
from .comunes import (PIZARRA, avisar, boton, boton_icono, confirmar, fila, nivel, numero, seccion, selector,
                      texto, titulo)

ERRORES = (ErrorModulo, ErrorEnlace, ParadaEmergencia, ValueError, KeyError)


def _editor(d: dict, valor):
    """Crea el control adecuado para un valor de configuración y devuelve cómo leerlo."""
    etiqueta = d.get("etiqueta", "")
    if isinstance(valor, bool):
        control = ui.switch(etiqueta, value=valor)
        return lambda: bool(control.value)
    if isinstance(valor, (int, float)) or valor is None:
        control = numero(etiqueta, valor, d.get("unidad", ""), ancho="w-full")
        entero = isinstance(valor, int)

        def leer():
            x = control.value
            if x is None:
                return None
            return int(x) if entero and float(x).is_integer() else float(x)
        return leer
    if d.get("opciones"):
        control = selector(etiqueta, list(d["opciones"]), valor if valor in d["opciones"] else None, "w-full")
        return lambda: control.value
    if isinstance(valor, str):
        control = texto(etiqueta, valor, "w-full")
        return lambda: control.value
    control = ui.textarea(etiqueta, value=yaml.safe_dump(valor, allow_unicode=True, sort_keys=False)) \
        .props("outlined dense autogrow").classes("w-full").style("font-family: ui-monospace, Consolas, monospace")
    return lambda: yaml.safe_load(control.value)


def _campos(definiciones: list[dict]) -> dict:
    """Campos numéricos de una solicitud o calibración. Devuelve clave -> control."""
    controles = {}
    for c in definiciones:
        controles[c["clave"]] = numero(c["etiqueta"], c.get("valor"), c.get("unidad", ""), c.get("min"),
                                       c.get("max"), ancho="w-full")
    return controles


def pantalla_modulos(motor, refrescar) -> None:
    g = motor.gestor
    ocupado = motor.ocupado()
    titulo("Equipo", "Acá se declara qué módulos tiene el robot y se prueba que respondan. El programa solo "
                     "permite ajustar y medir lo que figure como disponible en esta pantalla.")
    if ocupado:
        nivel("aviso", "Hay una campaña en curso: el equipo no se puede modificar hasta que termine.")

    # ------------------------------------------------------------------ conexión
    with seccion("Conexión"):
        conexion = g.datos.setdefault("conexion", {})
        modo = ui.radio({"simulacion": "Simulación (sin equipo, para practicar)",
                         "esp32": "Equipo real (ESP32 por cable USB)"},
                        value=conexion.get("modo", "simulacion")).props("inline")
        with ui.row().classes("items-center gap-3"):
            puertos = puertos_disponibles()
            actual = conexion.get("puerto") or (puertos[0] if puertos else None)
            if actual and actual not in puertos:
                puertos.append(actual)
            puerto = selector("Puerto USB", puertos, actual, "w-56")
            puerto.bind_visibility_from(modo, "value", value="esp32")
            aceleracion = numero("Velocidad de la simulación", conexion.get("aceleracion_simulacion", 20), "×",
                                 1, 200, ancho="w-56")
            aceleracion.bind_visibility_from(modo, "value", value="simulacion")

            async def conectar():
                conexion["modo"], conexion["puerto"] = modo.value, puerto.value or ""
                conexion["aceleracion_simulacion"] = aceleracion.value or 20
                g.guardar()
                ok, mensaje = await run.io_bound(g.conectar)
                avisar(mensaje, "ok" if ok and "no respondieron" not in mensaje else ("aviso" if ok else "error"))
                refrescar()

            async def desconectar():
                await run.io_bound(g.desconectar)
                refrescar()

            b = boton("Conectar y probar módulos" if not g.conectado() else "Volver a conectar", conectar,
                      "principal" if not g.conectado() else "secundario")
            if g.conectado():
                boton("Desconectar", desconectar, "texto").set_enabled(not ocupado)
            b.set_enabled(not ocupado)
        if g.conectado():
            nivel("ok", f"Conectado: {g.enlace.descripcion}."
                        + (f" Firmware {g.firmware.get('fw', '?')}." if not g.enlace.simulado else ""))
        else:
            nivel("nada", "Sin conexión. Elija el modo y pulse «Conectar y probar módulos».")
        if modo.value == "esp32" and not puertos:
            nivel("aviso", "No se encontró ningún puerto USB. Conecte el ESP32 y vuelva a entrar a esta pantalla.")

    # ------------------------------------------------------------------ módulos
    with seccion("Módulos instalados",
                 "Desactive los módulos que no estén colocados. Si un experimento necesita un módulo "
                 "desactivado o que no responde, el programa avisa y no arranca."):
        columnas = "minmax(200px,1.3fr) minmax(220px,2fr) 64px 156px"
        with fila(columnas, cabecera=True):
            for t in ("Módulo", "Estado", "Activo", ""):
                ui.label(t)
        for ficha in g.datos["modulos"]:
            ident = ficha["id"]
            clase = g.tipos.get(ficha.get("tipo"))
            modulo = g.modulos.get(ident)
            with fila(columnas):
                with ui.column().classes("gap-0"):
                    ui.label(ficha.get("etiqueta") or ident).style("font-weight:600")
                    ui.label(clase.NOMBRE if clase else f"Tipo desconocido: {ficha.get('tipo')}").classes("sdl-chico")
                with ui.column().classes("gap-0"):
                    if clase is None:
                        nivel("error", "Falta el archivo del módulo en sdl/modulos.")
                    elif modulo is None:
                        nivel("nada", "Desactivado")
                    elif not g.conectado():
                        nivel("nada", "Sin probar (no hay conexión)")
                    else:
                        ok, mensaje = g.pruebas.get(ident, (False, "Sin probar"))
                        nivel("ok" if ok else "error", mensaje)
                        if ok and modulo.resumen():
                            ui.label(modulo.resumen()).classes("sdl-chico q-ml-lg")

                def cambiar(e, ident=ident):
                    g.activar(ident, bool(e.value))
                    if g.conectado():
                        avisar("Pulse «Volver a conectar» para probar el módulo.", "info")
                    refrescar()
                ui.switch(value=bool(ficha.get("activo", True)), on_change=cambiar).props("dense") \
                    .set_enabled(not ocupado and clase is not None)
                with ui.row().classes("gap-0 no-wrap justify-end"):
                    if modulo is not None:
                        usable = g.conectado() and g.disponible(ident) and not ocupado
                        if modulo.CALIBRACION:
                            boton_icono("straighten", "Calibrar", lambda m=modulo: _dialogo_calibrar(motor, m, refrescar)) \
                                .set_enabled(usable)
                        if modulo.acciones():
                            boton_icono("play_arrow", "Usar manualmente",
                                        lambda m=modulo: _dialogo_manual(motor, m, refrescar)).set_enabled(usable)
                        boton_icono("tune", "Configurar", lambda m=modulo: _dialogo_config(motor, m, refrescar)) \
                            .set_enabled(not ocupado)

                    async def quitar(ident=ident, nombre=ficha.get("etiqueta") or ident):
                        if await confirmar(f"¿Quitar el módulo «{nombre}» de la instalación?", "Quitar", peligro=True):
                            g.quitar(ident)
                            refrescar()
                    boton_icono("delete_outline", "Quitar", quitar).set_enabled(not ocupado)
        for conflicto in g.conflictos_de_pines():
            nivel("error", conflicto + " Corríjalo en «Configurar → Instalación» antes de conectar el equipo real.")
        boton("Agregar módulo", lambda: _dialogo_agregar(motor, refrescar), "secundario", "add") \
            .classes("q-mt-sm").set_enabled(not ocupado)

    # ------------------------------------------------------------------ seguridad
    with seccion("Seguridad", "Ajustes generales de protección. El botón físico de parada se conecta al ESP32 "
                              "(normal cerrado, entre el pin indicado y GND)."):
        sistema = g.datos.setdefault("sistema", {})
        with ui.row().classes("gap-3 items-start"):
            espera = numero("Espera máxima al usuario", round(motor.seguridad.get("tiempo_espera_usuario_s", 900) / 60, 1),
                            "min", 1, 240, ancho="w-56")
            llenado = numero("Llenado máximo del vaso", round(motor.seguridad.get("llenado_maximo", 0.8) * 100),
                             "%", 10, 100, ancho="w-56")
            pin_parada = numero("Pin del botón de parada", sistema.get("pin_parada"), "GPIO", 0, 46, ancho="w-56")
            pin_dc = numero("Pin de habilitación de motores DC", sistema.get("pin_habilitar_dc"), "GPIO", 0, 46,
                            ancho="w-64")
            latido = numero("Corte si la PC no responde en", sistema.get("tiempo_latido_s", 5), "s", 2, 60, ancho="w-64")

        def guardar_seguridad():
            motor.seguridad["tiempo_espera_usuario_s"] = float(espera.value or 15) * 60
            motor.seguridad["llenado_maximo"] = float(llenado.value or 80) / 100
            escribir_yaml(motor.carpeta_config / "seguridad.yaml", motor.seguridad)
            sistema["pin_parada"] = int(pin_parada.value) if pin_parada.value is not None else None
            sistema["pin_habilitar_dc"] = int(pin_dc.value) if pin_dc.value is not None else None
            sistema["tiempo_latido_s"] = float(latido.value or 5)
            g.guardar()
            avisar("Ajustes de seguridad guardados. Los pines se aplican al volver a conectar.", "ok")
        ui.label("Si nadie contesta una pregunta del programa en el tiempo de espera, todo queda en estado seguro "
                 "(válvulas cerradas, motores apagados) hasta que alguien responda.").classes("sdl-chico")
        boton("Guardar ajustes", guardar_seguridad, "secundario").set_enabled(not ocupado)


# --------------------------------------------------------------------- diálogos
def _dialogo_agregar(motor, refrescar) -> None:
    g = motor.gestor
    with ui.dialog() as dialogo, ui.card():
        ui.label("Agregar módulo").classes("sdl-h2")
        tipo = selector("Tipo de módulo", {t: c.NOMBRE for t, c in g.tipos.items()}, ancho="w-full")
        descripcion = ui.label("").classes("sdl-chico")
        nombre = texto("Nombre para mostrar (ej. Bureta 3)", "", "w-full")
        tipo.on_value_change(lambda e: (descripcion.set_text(g.tipos[e.value].DESCRIPCION),
                                        nombre.set_value(nombre.value or g.tipos[e.value].NOMBRE)))
        ui.label("Para un módulo que todavía no existe en la lista (por ejemplo un sensor nuevo), primero hay que "
                 "agregar su archivo de programa: ver «Agregar un módulo nuevo» en el manual.").classes("sdl-chico")

        def agregar():
            if not tipo.value or not (nombre.value or "").strip():
                avisar("Elija el tipo y escriba un nombre.", "aviso")
                return
            try:
                g.agregar(tipo.value, identificador(nombre.value), nombre.value.strip())
            except ValueError as error:
                avisar(str(error), "error")
                return
            dialogo.close()
            avisar("Módulo agregado. Revise su configuración (pines) y vuelva a conectar.", "ok")
            refrescar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Agregar", agregar)
    dialogo.open()


def _dialogo_config(motor, modulo, refrescar) -> None:
    g = motor.gestor
    lectores = {}
    with ui.dialog() as dialogo, ui.card().style("min-width: 560px"):
        ui.label(f"Configurar: {modulo.etiqueta}").classes("sdl-h2")
        etiqueta = texto("Nombre para mostrar", modulo.etiqueta, "w-full")
        simples = {k: d for k, d in modulo.CONFIG.items() if not d.get("avanzado")}
        avanzados = {k: d for k, d in modulo.CONFIG.items() if d.get("avanzado")}
        for clave, d in simples.items():
            lectores[clave] = _editor(d, modulo.config.get(clave))
        if avanzados:
            with ui.expansion("Instalación (pines y límites)").classes("w-full").props("dense"):
                ui.label("Cambie estos valores solo si modificó el cableado.").classes("sdl-chico")
                for clave, d in avanzados.items():
                    lectores[clave] = _editor(d, modulo.config.get(clave))

        async def guardar():
            try:
                nuevos = {clave: leer() for clave, leer in lectores.items()}
            except yaml.YAMLError:
                avisar("Hay un valor con formato incorrecto.", "error")
                return
            modulo.config.update(nuevos)
            g.ficha(modulo.id)["etiqueta"] = (etiqueta.value or modulo.id).strip()
            g.guardar()
            dialogo.close()
            if g.conectado():
                ok, mensaje = await run.io_bound(g.conectar)        # reenvía la configuración al equipo
                avisar("Configuración guardada. " + mensaje, "ok" if ok else "error")
            else:
                g.instanciar()
                avisar("Configuración guardada.", "ok")
            refrescar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Guardar", guardar)
    dialogo.open()


def _dialogo_manual(motor, modulo, refrescar) -> None:
    """Ejecuta a mano cualquier acción del módulo (probar, purgar, enseñar estaciones del brazo...)."""
    g = motor.gestor
    lectores: dict = {}
    with ui.dialog() as dialogo, ui.card().style("min-width: 520px"):
        ui.label(f"Usar manualmente: {modulo.etiqueta}").classes("sdl-h2")
        estado = ui.label(modulo.resumen()).classes("sdl-chico")
        opciones = {a: d["etiqueta"] for a, d in modulo.acciones().items()}
        accion = selector("Acción", opciones, next(iter(opciones), None), "w-full")
        zona = ui.column().classes("w-full gap-2")
        pedido_zona = ui.column().classes("w-full gap-2")

        def dibujar():
            zona.clear()
            lectores.clear()
            definicion = modulo.acciones().get(accion.value) or {}
            with zona:
                for clave, d in (definicion.get("parametros") or {}).items():
                    tipo = d.get("tipo", "numero")
                    if tipo == "opcion":
                        control = selector(d["etiqueta"], d.get("opciones") or [], None, "w-full")
                    elif tipo == "texto":
                        control = texto(d["etiqueta"], "", "w-full")
                    else:
                        minimo = d.get("min")
                        inicial = minimo if isinstance(minimo, (int, float)) and minimo > 0 else None
                        if d.get("opcional"):
                            inicial = None                # lo opcional queda vacío: se usa el valor habitual
                        control = numero(d["etiqueta"], inicial, d.get("unidad", ""), minimo, d.get("max"),
                                         d.get("paso") or None, "w-full")
                    lectores[clave] = control
        accion.on_value_change(lambda e: dibujar())
        dibujar()

        async def ejecutar():
            pedido_zona.clear()
            p = {clave: control.value for clave, control in lectores.items() if control.value not in (None, "")}
            try:
                resultado = await run.io_bound(modulo.ejecutar, accion.value, p)
            except NecesitaUsuario as pedido:
                with pedido_zona:
                    nivel("info", pedido.mensaje)
                    controles = _campos(pedido.campos)

                    def resolver():
                        modulo.resolver(pedido.clave, {k: c.value for k, c in controles.items()})
                        pedido_zona.clear()
                        avisar("Dato guardado. Pulse «Ejecutar» otra vez.", "ok")
                    boton("Guardar dato", resolver, "secundario")
                return
            except ERRORES as error:
                avisar(str(error), "error")
                return
            if (resultado or {}).get("guardar_config"):
                g.guardar()
                accion.set_options({a: d["etiqueta"] for a, d in modulo.acciones().items()}, value=accion.value)
                dibujar()
            estado.set_text(modulo.resumen())
            avisar("Hecho.", "ok")

        async def cerrar():
            dialogo.close()
            if g.conectado():
                await run.io_bound(g.probar, modulo.id)      # actualiza el estado que muestra la lista
            refrescar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cerrar", cerrar, "texto")
            boton("Ejecutar", ejecutar, icono="play_arrow")
    dialogo.open()


def _dialogo_calibrar(motor, modulo, refrescar) -> None:
    """Calibración. Si el módulo lo permite, ofrece dos caminos: escribir lo que el usuario
    ya midió a mano, o que el programa haga la maniobra y el usuario mida el resultado."""
    g = motor.gestor
    calibracion = modulo.CALIBRACION
    manual = calibracion.get("manual")
    automatica = "antes" in calibracion
    with ui.dialog() as dialogo, ui.card().style("min-width: 560px"):
        ui.label(f"Calibrar: {modulo.etiqueta}").classes("sdl-h2")
        for linea in modulo.calibracion_estado():
            nivel("info", linea)
        modo = ui.radio({"manual": (manual or {}).get("titulo", "Ya lo medí yo: escribo los valores"),
                         "auto": calibracion.get("titulo", "Que el programa haga la maniobra y yo mido")},
                        value="manual" if manual else "auto")
        modo.set_visibility(bool(manual and automatica))

        def cerrar_con(mensaje: str) -> None:
            g.guardar()
            dialogo.close()
            avisar(mensaje, "ok")
            refrescar()

        # --- camino 1: medición hecha a mano ---
        zona_manual = ui.column().classes("w-full gap-2")
        if manual:
            with zona_manual:
                ui.label(manual["texto"]).classes("sdl-ayuda")
                campos_manual = _campos(manual["campos"])
                resultado = ui.column().classes("w-full gap-1")

                def datos_manual():
                    datos = {k: c.value for k, c in campos_manual.items()}
                    return None if any(v is None for v in datos.values()) else datos

                def previa(_=None):
                    resultado.clear()
                    datos = datos_manual()
                    if datos is None:
                        return
                    with resultado:
                        try:
                            for linea in modulo.calibrar_previa(datos):
                                nivel("info", linea)
                        except ERRORES as error:
                            nivel("error", str(error))
                for control in campos_manual.values():
                    control.on_value_change(previa)

                def guardar_manual():
                    datos = datos_manual()
                    if datos is None:
                        avisar("Complete los tres valores.", "aviso")
                        return
                    try:
                        mensaje = modulo.calibrar_manual(datos)
                    except ERRORES as error:
                        avisar(str(error), "error")
                        return
                    cerrar_con(mensaje)
        zona_manual.bind_visibility_from(modo, "value", value="manual")

        # --- camino 2: el programa hace la maniobra ---
        zona_auto = ui.column().classes("w-full gap-2")
        antes: dict = {}
        despues: dict = {}
        if automatica:
            with zona_auto:
                ui.label(calibracion["texto"]).classes("sdl-ayuda")
                antes.update(_campos(calibracion.get("antes", [])))
                despues_zona = ui.column().classes("w-full gap-2")

            async def ejecutar():
                if any(c.value is None for c in antes.values()):
                    avisar("Complete los valores.", "aviso")
                    return
                try:
                    await run.io_bound(modulo.calibrar_ejecutar, {k: c.value for k, c in antes.items()})
                except ERRORES as error:
                    avisar(str(error), "error")
                    return
                despues_zona.clear()
                despues.clear()
                with despues_zona:
                    nivel("ok", calibracion.get("texto_despues", "Listo. Ahora escriba lo que midió."))
                    despues.update(_campos(calibracion.get("despues", [])))
                    boton("Guardar calibración", guardar_auto)

            async def guardar_auto():
                datos = {k: c.value for k, c in {**antes, **despues}.items()}
                if any(v is None for v in datos.values()):
                    avisar("Complete todos los valores.", "aviso")
                    return
                try:
                    mensaje = await run.io_bound(modulo.calibrar_aplicar, datos)
                except ERRORES as error:
                    avisar(str(error), "error")
                    return
                cerrar_con(mensaje)
        zona_auto.bind_visibility_from(modo, "value", value="auto")

        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            if manual:
                boton("Guardar calibración", guardar_manual).bind_visibility_from(modo, "value", value="manual")
            if automatica:
                boton("Ejecutar", ejecutar, "secundario", "play_arrow").bind_visibility_from(modo, "value", value="auto")
    dialogo.open()
