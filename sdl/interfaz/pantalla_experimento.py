"""Pantalla 2 — Experimento: asistente para definir qué se ajusta, qué se mide y el protocolo.

Cada cambio se guarda solo. El químico nunca edita archivos.
"""
from __future__ import annotations

import copy

from nicegui import ui

from ..modelos import (ALCANZAR, MAXIMIZAR, MINIMIZAR, Experimento, Objetivo, Paso, Variable, identificador,
                       numero_txt)
from ..motor import texto_paso
from .comunes import (avisar, boton, boton_icono, confirmar, fila, nivel, numero, seccion, selector, texto,
                      titulo)

ORIGEN_TXT = {"modulo": "Automático", "tiempo": "Tiempo de espera", "manual": "Lo ajusta el usuario"}


def _unico(nombre: str, usados: list[str]) -> str:
    base, n, candidato = nombre, 2, nombre
    while candidato in usados:
        candidato, n = f"{base}_{n}", n + 1
    return candidato


def _usa_variable(paso: Paso, nombre: str) -> bool:
    ref = "$" + nombre
    return (paso.variable == nombre or paso.segundos == ref
            or any(v == ref for v in paso.parametros.values()))


def dialogo_nuevo(motor, al_crear, base: Experimento | None = None) -> None:
    """Crea un experimento nuevo (vacío o como copia de otro)."""
    with ui.dialog() as dialogo, ui.card():
        ui.label("Nuevo experimento" if base is None else f"Duplicar «{base.nombre}»").classes("sdl-h2")
        nombre = texto("Nombre del experimento", "" if base is None else f"{base.nombre} (copia)", "w-full")
        reaccion = texto("Reacción", "" if base is None else base.reaccion, "w-full")
        ui.label("Los experimentos con el mismo nombre de reacción comparten el historial de resultados. "
                 "Si cambia reactivos o condiciones fijas, use un nombre de reacción distinto.").classes("sdl-chico")

        def crear():
            if not (nombre.value or "").strip():
                avisar("Escriba un nombre.", "aviso")
                return
            ident = _unico(identificador(nombre.value), [e.id for e in motor.experimentos()])
            if base is None:
                exp = Experimento(id=ident, nombre=nombre.value.strip())
            else:
                exp = copy.deepcopy(base)
                exp.id, exp.nombre = ident, nombre.value.strip()
            exp.reaccion = identificador(reaccion.value or nombre.value)
            motor.guardar_experimento(exp)
            dialogo.close()
            al_crear(exp.id)
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Crear", crear)
    dialogo.open()


def pantalla_experimento(motor, exp: Experimento | None, refrescar, elegir) -> None:
    g = motor.gestor
    titulo("Experimento", "Defina qué puede ajustar el robot, qué resultado se busca y los pasos a seguir. "
                          "Con eso, el programa decide solo el próximo ensayo.")
    with ui.row().classes("gap-2 q-mt-md"):
        boton("Nuevo experimento", lambda: dialogo_nuevo(motor, elegir), "secundario", "add")
        if exp is not None:
            boton("Duplicar", lambda: dialogo_nuevo(motor, elegir, exp), "texto", "content_copy")

            async def eliminar():
                if await confirmar(f"¿Eliminar el experimento «{exp.nombre}»? El historial de la reacción no se borra.",
                                   "Eliminar", peligro=True):
                    motor.borrar_experimento(exp)
                    elegir(None)
            boton("Eliminar", eliminar, "texto", "delete_outline")
    if exp is None:
        with seccion("Todavía no hay experimentos"):
            ui.label("Pulse «Nuevo experimento» para crear el primero.").classes("sdl-ayuda")
        return
    bloqueado = motor.ocupado() and motor.exp is not None and motor.exp.id == exp.id
    if bloqueado:
        nivel("aviso", "Este experimento tiene una campaña en curso: no se puede modificar hasta que termine.")
        return

    catalogo = g.catalogo()

    def guardar(redibujar: bool = True):
        motor.guardar_experimento(exp)
        if redibujar:
            refrescar()

    def completar_historial(nombre: str, valor: float) -> int:
        """Anota 'valor' para una variable nueva en los experimentos ya hechos que no la tienen."""
        historial = motor.historial_de(exp)
        cambiados = 0
        for f in historial.filas():
            if nombre not in f["variables"]:
                historial.actualizar(f["n"], variables={nombre: float(valor)})
                cambiados += 1
        return cambiados

    # ------------------------------------------------------------------ datos generales
    with seccion("Datos generales"):
        with ui.row().classes("gap-3 items-start w-full"):
            nombre = texto("Nombre", exp.nombre, "w-80")
            reaccion = texto("Reacción (comparte historial)", exp.reaccion, "w-64")
        descripcion = ui.textarea("Descripción (opcional)", value=exp.descripcion).props("outlined dense autogrow") \
            .classes("w-full").style("max-width: 760px")
        with ui.row().classes("gap-3 items-start"):
            maximo = numero("Máximo de experimentos", exp.max_experimentos, "", 1, 500, 1, "w-56")
            vaso = numero("Capacidad del vaso", exp.capacidad_vaso_ml, "mL", 1, 5000, ancho="w-48")
            paciencia = numero("Avisar si no mejora en", exp.paciencia or None, "experimentos", 2, 100, 1, "w-64")
        supervisado = ui.switch("Pedir mi aprobación antes de ejecutar cada propuesta", value=exp.supervisado)
        ui.label("El máximo lo fija usted según el tiempo y los reactivos disponibles. El aviso por falta de "
                 "mejora es opcional (déjelo vacío para no usarlo).").classes("sdl-chico")

        def datos(_=None):
            exp.nombre = (nombre.value or exp.nombre).strip()
            exp.reaccion = identificador(reaccion.value or exp.id)
            exp.descripcion = descripcion.value or ""
            exp.max_experimentos = int(maximo.value or 1)
            exp.capacidad_vaso_ml = float(vaso.value or 100)
            exp.paciencia = int(paciencia.value or 0)
            exp.supervisado = bool(supervisado.value)
            guardar(redibujar=False)
        for control in (nombre, reaccion, descripcion, maximo, vaso, paciencia):
            control.on("blur", datos)
        supervisado.on_value_change(datos)

    # ------------------------------------------------------------------ variables
    with seccion("Variables a ajustar", "Lo que el programa puede cambiar entre un experimento y otro, con sus "
                                        "límites inferior y superior."):
        if exp.variables:
            columnas = "minmax(180px,2fr) 1.1fr 0.8fr minmax(180px,2fr) 76px"
            with fila(columnas, cabecera=True):
                for t in ("Variable", "Límites", "Resolución", "Cómo se ajusta", ""):
                    ui.label(t)
            for v in exp.variables:
                with fila(columnas):
                    ui.label(v.etiqueta).style("font-weight:600")
                    ui.label(f"{numero_txt(v.minimo)} a {numero_txt(v.maximo)} {v.unidad}".strip())
                    ui.label(f"{numero_txt(v.paso)} {v.unidad}".strip() if v.paso else "continua")
                    if v.origen == "modulo":
                        modulo = g.modulos.get(v.modulo)
                        ui.label(f"{ORIGEN_TXT['modulo']} · {modulo.etiqueta if modulo else v.modulo + ' (no disponible)'}")
                    else:
                        ui.label(ORIGEN_TXT.get(v.origen, v.origen))
                    with ui.row().classes("gap-0 no-wrap justify-end"):
                        boton_icono("edit", "Editar", lambda v=v: _dialogo_variable(exp, catalogo, guardar, v))

                        def quitar(v=v):
                            antes = len(exp.protocolo)
                            exp.protocolo = [p for p in exp.protocolo if not _usa_variable(p, v.nombre)]
                            exp.variables.remove(v)
                            if antes != len(exp.protocolo):
                                avisar(f"También se quitaron {antes - len(exp.protocolo)} paso(s) que usaban esa variable.")
                            guardar()
                        boton_icono("delete_outline", "Quitar", quitar)
        else:
            ui.label("Todavía no hay variables.").classes("sdl-chico")
        boton("Agregar variable", lambda: _dialogo_variable(exp, catalogo, guardar, completar=completar_historial),
              "secundario", "add")

    # ------------------------------------------------------------------ objetivos
    with seccion("Objetivos", "Lo que se mide en cada experimento y se quiere aumentar, reducir o llevar a un "
                              "valor. Con varios objetivos, el programa busca los mejores compromisos (frente de Pareto)."):
        if exp.objetivos:
            columnas = "minmax(180px,2fr) minmax(200px,2.4fr) minmax(160px,2fr) 76px"
            with fila(columnas, cabecera=True):
                for t in ("Objetivo", "Qué se busca", "Cómo se mide", ""):
                    ui.label(t)
            for o in exp.objetivos:
                with fila(columnas):
                    ui.label(f"{o.etiqueta}{f' ({o.unidad})' if o.unidad else ''}").style("font-weight:600")
                    ui.label(o.texto_meta())
                    if o.medicion == "modulo":
                        modulo = g.modulos.get(o.modulo)
                        ui.label(f"Automático · {modulo.etiqueta if modulo else o.modulo + ' (no disponible)'}")
                    else:
                        ui.label("Lo mide y lo escribe el usuario")
                    with ui.row().classes("gap-0 no-wrap justify-end"):
                        boton_icono("edit", "Editar", lambda o=o: _dialogo_objetivo(exp, catalogo, guardar, o))

                        def quitar(o=o):
                            exp.protocolo = [p for p in exp.protocolo if not (p.tipo == "medir" and p.objetivo == o.nombre)]
                            exp.objetivos.remove(o)
                            guardar()
                        boton_icono("delete_outline", "Quitar", quitar)
        else:
            ui.label("Todavía no hay objetivos.").classes("sdl-chico")
        boton("Agregar objetivo", lambda: _dialogo_objetivo(exp, catalogo, guardar), "secundario", "add")

    # ------------------------------------------------------------------ protocolo
    with seccion("Protocolo", "Los pasos de cada experimento, en orden. Al agregar una variable o un objetivo, "
                              "su paso se agrega solo al final; acomódelo con las flechas."):
        for i, paso in enumerate(exp.protocolo):
            with fila("28px 1fr 112px"):
                ui.label(f"{i + 1}.").classes("sdl-chico")
                ui.label(texto_paso(exp, paso, g))
                with ui.row().classes("gap-0 no-wrap justify-end"):
                    def mover(i=i, d=-1):
                        j = i + d
                        if 0 <= j < len(exp.protocolo):
                            exp.protocolo[i], exp.protocolo[j] = exp.protocolo[j], exp.protocolo[i]
                            guardar()
                    boton_icono("arrow_upward", "Subir", lambda i=i: mover(i, -1)).set_enabled(i > 0)
                    boton_icono("arrow_downward", "Bajar", lambda i=i: mover(i, 1)) \
                        .set_enabled(i < len(exp.protocolo) - 1)

                    def quitar(i=i):
                        exp.protocolo.pop(i)
                        guardar()
                    boton_icono("delete_outline", "Quitar", quitar)
        if not exp.protocolo:
            ui.label("Todavía no hay pasos.").classes("sdl-chico")
        boton("Agregar paso", lambda: _dialogo_paso(exp, catalogo, guardar), "secundario", "add")

    # ------------------------------------------------------------------ restricciones, reactivos, registros
    with seccion("Condiciones entre variables (opcional)",
                 "Combinaciones que no deben ensayarse. Se escriben como una cuenta simple con los nombres "
                 "internos de las variables."):
        if exp.variables:
            ui.label("Nombres disponibles: " + ", ".join(v.nombre for v in exp.variables)
                     + ".   Ejemplo: " + (f"{exp.variables[0].nombre} + {exp.variables[1].nombre} <= 40"
                                          if len(exp.variables) > 1 else f"{exp.variables[0].nombre} <= 10")) \
                .classes("sdl-chico")
        for i, formula in enumerate(exp.restricciones):
            with fila("1fr 40px"):
                ui.label(formula).style("font-family: ui-monospace, Consolas, monospace; font-size: 14px")

                def quitar(i=i):
                    exp.restricciones.pop(i)
                    guardar()
                boton_icono("delete_outline", "Quitar", quitar)
        with ui.row().classes("items-center gap-2"):
            nueva = texto("Nueva condición", "", "w-96")

            def agregar():
                from ..restricciones import ErrorRestriccion, compilar
                formula = (nueva.value or "").strip()
                if not formula:
                    return
                try:
                    compilar(formula, [v.nombre for v in exp.variables])
                except ErrorRestriccion as error:
                    avisar(str(error), "error")
                    return
                exp.restricciones.append(formula)
                guardar()
            boton("Agregar", agregar, "secundario")

    usados = [p.modulo for p in exp.protocolo if p.tipo == "accion"]
    dosificadores = [m for m in catalogo["dosificadores"] if m in usados]
    if dosificadores:
        with seccion("Reactivos cargados", "Qué hay en cada dosificador. Se le pedirá confirmarlo al iniciar, y el "
                                           "programa avisa si detecta una combinación peligrosa conocida."):
            for ident in dosificadores:
                campo = texto(f"{g.modulos[ident].etiqueta}: reactivo y concentración",
                              str(exp.reactivos.get(ident, "")), "w-96")

                def cambiar(_=None, ident=ident, campo=campo):
                    exp.reactivos[ident] = (campo.value or "").strip()
                    guardar(redibujar=False)
                campo.on("blur", cambiar)

    if catalogo["mediciones"]:
        with seccion("Anotar además en cada experimento (opcional)",
                     "Mediciones automáticas que se guardan con cada resultado sin optimizarlas, "
                     "por ejemplo la temperatura."):
            opciones = {f"{m['modulo']}|{m['magnitud']}": m["etiqueta"] for m in catalogo["mediciones"]}
            actuales = [f"{r['modulo']}|{r['magnitud']}" for r in exp.registros
                        if f"{r['modulo']}|{r['magnitud']}" in opciones]

            def registros(e):
                exp.registros = [dict(zip(("modulo", "magnitud"), clave.split("|"))) for clave in (e.value or [])]
                guardar(redibujar=False)
            selector("Mediciones", opciones, actuales, "w-96", multiple=True, on_change=registros).props("use-chips")

    # ------------------------------------------------------------------ revisión
    with seccion("Revisión", "El programa comprueba que todo lo pedido sea posible con el equipo disponible."):
        for chequeo in motor.verificar(exp):
            nivel(chequeo.nivel, chequeo.texto)


# --------------------------------------------------------------------- diálogos
def _dialogo_variable(exp: Experimento, catalogo: dict, guardar, variable: Variable | None = None,
                      completar=None) -> None:
    nueva = variable is None
    opciones = {f"{o['modulo']}|{o['accion']}|{o['parametro']}": o["etiqueta"] for o in catalogo["optimizables"]}
    opciones["tiempo"] = "Un tiempo de espera"
    opciones["manual"] = "Algo que ajusto yo a mano (el programa me avisa y espera)"
    por_clave = {f"{o['modulo']}|{o['accion']}|{o['parametro']}": o for o in catalogo["optimizables"]}
    with ui.dialog() as dialogo, ui.card():
        ui.label("Agregar variable" if nueva else f"Editar «{variable.etiqueta}»").classes("sdl-h2")
        que = selector("¿Qué se ajusta?", opciones, None, "w-full")
        if not nueva:
            que.set_visibility(False)
        etiqueta = texto("Nombre de la variable", "" if nueva else variable.etiqueta, "w-full")
        with ui.row().classes("gap-3 w-full no-wrap"):
            unidad = texto("Unidad", "" if nueva else variable.unidad, "w-28")
            minimo = numero("Límite inferior", None if nueva else variable.minimo, ancho="w-36")
            maximo = numero("Límite superior", None if nueva else variable.maximo, ancho="w-36")
            paso = numero("Resolución", None if nueva else (variable.paso or None), ancho="w-32")
        ayuda = ui.label("La resolución es el cambio más chico que tiene sentido (por ejemplo 0,1 mL). "
                         "Vacío = cualquier valor.").classes("sdl-chico")
        agregar_paso = ui.switch("Agregar su paso al final del protocolo", value=True)
        agregar_paso.set_visibility(nueva)
        previo = numero("Valor que tuvo en los experimentos ya hechos (opcional)", None, ancho="w-full")
        ayuda_previo = ui.label("Los experimentos del historial que no tengan esta variable no se pueden usar para "
                                "optimizar. Si en todos tuvo el mismo valor, escríbalo acá y se les anota.") \
            .classes("sdl-chico")
        previo.set_visibility(nueva and completar is not None)
        ayuda_previo.set_visibility(nueva and completar is not None)

        def elegido(e):
            o = por_clave.get(e.value)
            if o:
                equipo, resto = o["etiqueta"].split(": ", 1)
                etiqueta.set_value(f"{resto.split(' (')[0].strip().capitalize()} de {equipo}")
                unidad.set_value(o.get("unidad", ""))
                minimo.set_value(o.get("min"))
                maximo.set_value(o.get("max"))
                paso.set_value(o.get("paso") or None)
                ayuda.set_text(f"El equipo admite de {numero_txt(o.get('min'))} a {numero_txt(o.get('max'))} "
                               f"{o.get('unidad', '')}. Elija dentro de ese rango los límites de este experimento.")
            elif e.value == "tiempo":
                unidad.set_value("s")
                etiqueta.set_value(etiqueta.value or "Tiempo de reacción")
        que.on_value_change(elegido)

        def aceptar():
            if nueva and not que.value:
                avisar("Elija qué se ajusta.", "aviso")
                return
            if not (etiqueta.value or "").strip() or minimo.value is None or maximo.value is None:
                avisar("Complete el nombre y los dos límites.", "aviso")
                return
            if not float(maximo.value) > float(minimo.value):
                avisar("El límite superior debe ser mayor que el inferior.", "aviso")
                return
            if nueva:
                nombre = _unico(identificador(etiqueta.value), [v.nombre for v in exp.variables])
                v = Variable(nombre, etiqueta.value.strip())
                if que.value in ("tiempo", "manual"):
                    v.origen = que.value
                else:
                    v.origen = "modulo"
                    v.modulo, v.accion, v.parametro = que.value.split("|")
            else:
                v = variable
                v.etiqueta = etiqueta.value.strip()
            v.unidad = (unidad.value or "").strip()
            v.minimo, v.maximo, v.paso = float(minimo.value), float(maximo.value), float(paso.value or 0)
            if nueva:
                exp.variables.append(v)
                if agregar_paso.value:
                    if v.origen == "modulo":
                        ya = next((p for p in exp.protocolo if p.tipo == "accion" and p.modulo == v.modulo
                                   and p.accion == v.accion and v.parametro not in p.parametros), None)
                        if ya is not None:                # completa un paso existente de la misma acción
                            ya.parametros[v.parametro] = "$" + v.nombre
                        else:
                            exp.protocolo.append(Paso("accion", modulo=v.modulo, accion=v.accion,
                                                      parametros={v.parametro: "$" + v.nombre}))
                    elif v.origen == "tiempo":
                        exp.protocolo.append(Paso("esperar", segundos="$" + v.nombre))
                    else:
                        exp.protocolo.append(Paso("ajuste_manual", variable=v.nombre))
                if completar is not None and previo.value is not None:
                    cambiados = completar(v.nombre, float(previo.value))
                    if cambiados:
                        avisar(f"Se anotó {v.etiqueta} = {numero_txt(previo.value)} {v.unidad} en {cambiados} "
                               f"experimento(s) del historial.", "ok")
            dialogo.close()
            guardar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Agregar" if nueva else "Guardar", aceptar)
    dialogo.open()


def _dialogo_objetivo(exp: Experimento, catalogo: dict, guardar, objetivo: Objetivo | None = None) -> None:
    nuevo = objetivo is None
    o = objetivo
    mediciones = {"manual": "Lo mido yo y escribo el resultado"}
    mediciones.update({f"{m['modulo']}|{m['magnitud']}": f"Automático — {m['etiqueta']}" for m in catalogo["mediciones"]})
    por_clave = {f"{m['modulo']}|{m['magnitud']}": m for m in catalogo["mediciones"]}
    with ui.dialog() as dialogo, ui.card():
        ui.label("Agregar objetivo" if nuevo else f"Editar «{o.etiqueta}»").classes("sdl-h2")
        actual = "manual" if nuevo or o.medicion != "modulo" else f"{o.modulo}|{o.magnitud}"
        if actual not in mediciones:
            mediciones[actual] = f"{o.modulo} (no disponible)"
        como = selector("¿Cómo se mide?", mediciones, actual, "w-full")
        with ui.row().classes("gap-3 w-full no-wrap"):
            etiqueta = texto("Qué se mide (ej. Rendimiento)", "" if nuevo else o.etiqueta, "w-72")
            unidad = texto("Unidad", "" if nuevo else o.unidad, "w-28")
        direccion = ui.radio({MAXIMIZAR: "Aumentar", MINIMIZAR: "Reducir", ALCANZAR: "Llevar a un valor"},
                             value=MAXIMIZAR if nuevo else o.direccion).props("inline")
        with ui.row().classes("gap-3 w-full no-wrap"):
            meta = numero("Meta (opcional)", None if nuevo else o.meta, ancho="w-44")
            valor = numero("Valor buscado", None if nuevo else o.valor, ancho="w-44")
            tolerancia = numero("Tolerancia (±)", None if nuevo else o.tolerancia, ancho="w-44")
        ayuda = ui.label("").classes("sdl-chico")

        def modo(_=None):
            alcanzar = direccion.value == ALCANZAR
            meta.set_visibility(not alcanzar)
            valor.set_visibility(alcanzar)
            tolerancia.set_visibility(alcanzar)
            ayuda.set_text("Se da por cumplido cuando el resultado queda dentro de la tolerancia." if alcanzar else
                           "La meta es el valor con el que el objetivo se considera cumplido. Sin meta, el programa "
                           "sigue mejorando hasta que usted lo detenga o se llegue al máximo de experimentos.")
        direccion.on_value_change(modo)
        modo()

        def medicion(e):
            m = por_clave.get(e.value)
            if m and not etiqueta.value:
                etiqueta.set_value(m["etiqueta"].split(":")[-1].strip().capitalize())
                unidad.set_value(m.get("unidad", ""))
        como.on_value_change(medicion)

        def aceptar():
            if not (etiqueta.value or "").strip():
                avisar("Escriba qué se mide.", "aviso")
                return
            if direccion.value == ALCANZAR and (valor.value is None or not tolerancia.value or tolerancia.value <= 0):
                avisar("Para llevar a un valor hacen falta el valor buscado y una tolerancia mayor que cero.", "aviso")
                return
            if nuevo:
                nombre = _unico(identificador(etiqueta.value), [x.nombre for x in exp.objetivos])
                x = Objetivo(nombre, etiqueta.value.strip())
            else:
                x = o
                x.etiqueta = etiqueta.value.strip()
            x.unidad, x.direccion = (unidad.value or "").strip(), direccion.value
            if x.direccion == ALCANZAR:
                x.valor, x.tolerancia, x.meta = float(valor.value), float(tolerancia.value), None
            else:
                x.meta = float(meta.value) if meta.value is not None else None
                x.valor = x.tolerancia = None
            if como.value == "manual":
                x.medicion, x.modulo, x.magnitud = "manual", "", ""
            else:
                x.medicion = "modulo"
                x.modulo, x.magnitud = como.value.split("|")
            if nuevo:
                exp.objetivos.append(x)
                exp.protocolo.append(Paso("medir", objetivo=x.nombre))
            dialogo.close()
            guardar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Agregar" if nuevo else "Guardar", aceptar)
    dialogo.open()


def _dialogo_paso(exp: Experimento, catalogo: dict, guardar) -> None:
    acciones = {f"{a['modulo']}|{a['accion']}": a for a in catalogo["acciones"]}
    tipos = {"accion": "Una acción del robot", "esperar": "Esperar un tiempo",
             "confirmar": "Pedirle algo al usuario y esperar su confirmación",
             "ajuste_manual": "Ajuste manual de una variable", "medir": "Medir un objetivo"}
    lectores: dict = {}
    with ui.dialog() as dialogo, ui.card().style("min-width: 540px"):
        ui.label("Agregar paso").classes("sdl-h2")
        tipo = selector("Tipo de paso", tipos, "accion", "w-full")
        zona = ui.column().classes("w-full gap-2")

        def variables_para(modulo: str, accion: str, parametro: str) -> dict:
            return {"$" + v.nombre: f"Variable: {v.etiqueta}" for v in exp.variables
                    if v.origen == "modulo" and (v.modulo, v.accion, v.parametro) == (modulo, accion, parametro)}

        def parametros(clave: str, destino):
            destino.clear()
            for sobrante in [k for k in lectores if k != "__accion"]:
                del lectores[sobrante]
            a = acciones.get(clave)
            if a is None:
                return
            with destino:
                for nombre, d in a["parametros"].items():
                    tipo_p = d.get("tipo", "numero")
                    if tipo_p == "opcion":
                        lectores[nombre] = selector(d["etiqueta"], d.get("opciones") or [], None, "w-full")
                        if not d.get("opciones"):
                            ui.label("No hay opciones todavía (por ejemplo, faltan enseñar las estaciones del brazo "
                                     "en la pantalla Equipo).").classes("sdl-chico")
                    elif tipo_p == "texto":
                        lectores[nombre] = texto(d["etiqueta"], "", "w-full")
                    else:
                        variables = variables_para(a["modulo"], a["accion"], nombre)
                        with ui.row().classes("gap-3 w-full no-wrap items-start"):
                            rotulo = f"{d['etiqueta']} (opcional)" if d.get("opcional") else f"{d['etiqueta']} (valor fijo)"
                            fijo = numero(rotulo, None, d.get("unidad", ""), d.get("min"),
                                          d.get("max"), d.get("paso") or None, "w-56")
                            if variables:
                                usar = selector("o usar una variable", variables, next(iter(variables)), "w-64",
                                                clearable=True)
                                lectores[nombre] = (fijo, usar)
                            else:
                                lectores[nombre] = (fijo, None)
                        if d.get("opcional") and nombre == "caudal":
                            ui.label(f"Vacío = caudal habitual del módulo. Se usa la apertura calibrada más cercana "
                                     f"(entre {numero_txt(d.get('min'))} y {numero_txt(d.get('max'))} {d.get('unidad', '')}).") \
                                .classes("sdl-chico")

        def dibujar(_=None):
            zona.clear()
            lectores.clear()
            with zona:
                if tipo.value == "accion":
                    accion = selector("Acción", {k: a["etiqueta"] for k, a in acciones.items()}, None, "w-full")
                    destino = ui.column().classes("w-full gap-2")
                    accion.on_value_change(lambda e: parametros(e.value, destino))
                    lectores["__accion"] = accion
                    if not acciones:
                        ui.label("No hay módulos activos con acciones. Revise la pantalla Equipo.").classes("sdl-chico")
                elif tipo.value == "esperar":
                    tiempos = {"$" + v.nombre: f"Variable: {v.etiqueta}" for v in exp.variables if v.origen == "tiempo"}
                    with ui.row().classes("gap-3 w-full no-wrap"):
                        lectores["segundos"] = (numero("Tiempo fijo", None, "s", 0, 86400, ancho="w-48"),
                                                selector("o usar una variable", tiempos, None, "w-64", clearable=True)
                                                if tiempos else None)
                elif tipo.value == "confirmar":
                    lectores["mensaje"] = ui.textarea("Qué debe hacer el usuario (ej. «Agregue 2 g de catalizador»)") \
                        .props("outlined dense autogrow").classes("w-full")
                    ui.label("Puede incluir el valor de una variable escribiendo $ y su nombre interno, "
                             "por ejemplo: «Caliente a $temperatura».").classes("sdl-chico")
                elif tipo.value == "ajuste_manual":
                    manuales = {v.nombre: v.etiqueta for v in exp.variables if v.origen == "manual"}
                    lectores["variable"] = selector("Variable", manuales, next(iter(manuales), None), "w-full")
                    if not manuales:
                        ui.label("Primero agregue una variable del tipo «la ajusto yo a mano».").classes("sdl-chico")
                elif tipo.value == "medir":
                    objetivos = {o.nombre: o.etiqueta for o in exp.objetivos}
                    lectores["objetivo"] = selector("Objetivo", objetivos, next(iter(objetivos), None), "w-full")
        tipo.on_value_change(dibujar)
        dibujar()

        def leer(par):
            fijo, usar = par
            if usar is not None and usar.value:
                return usar.value
            return fijo.value

        def aceptar():
            t = tipo.value
            if t == "accion":
                clave = lectores["__accion"].value
                if not clave:
                    avisar("Elija la acción.", "aviso")
                    return
                a = acciones[clave]
                valores = {}
                for nombre, control in lectores.items():
                    if nombre == "__accion":
                        continue
                    valor = leer(control) if isinstance(control, tuple) else control.value
                    if valor in (None, ""):
                        if a["parametros"][nombre].get("opcional"):
                            continue
                        avisar(f"Falta completar «{a['parametros'][nombre]['etiqueta']}».", "aviso")
                        return
                    valores[nombre] = valor
                paso = Paso("accion", modulo=a["modulo"], accion=a["accion"], parametros=valores)
            elif t == "esperar":
                segundos = leer(lectores["segundos"])
                if segundos in (None, ""):
                    avisar("Indique el tiempo.", "aviso")
                    return
                paso = Paso("esperar", segundos=segundos)
            elif t == "confirmar":
                if not (lectores["mensaje"].value or "").strip():
                    avisar("Escriba qué debe hacer el usuario.", "aviso")
                    return
                paso = Paso("confirmar", mensaje=lectores["mensaje"].value.strip())
            elif t == "ajuste_manual":
                if not lectores["variable"].value:
                    return
                paso = Paso("ajuste_manual", variable=lectores["variable"].value)
            else:
                if not lectores["objetivo"].value:
                    return
                paso = Paso("medir", objetivo=lectores["objetivo"].value)
            exp.protocolo.append(paso)
            dialogo.close()
            guardar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Agregar", aceptar)
    dialogo.open()
