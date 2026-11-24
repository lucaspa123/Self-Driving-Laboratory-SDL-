"""Pantalla 3 — Historial: experimentos ya hechos sobre la reacción (el programa aprende de ellos)."""
from __future__ import annotations

from nicegui import ui

from ..historial import ABORTADO, COMPLETADO, DESCARTADO, EN_CURSO, FALLIDO
from ..informe import TEXTO_ESTADO, TEXTO_ORIGEN
from ..modelos import Experimento, numero_txt
from .comunes import avisar, boton, nivel, numero, seccion, texto, titulo


def columnas_y_filas(exp: Experimento, filas: list[dict], destacar: set | None = None) -> tuple[list, list]:
    """Columnas y filas para ui.table con variables y resultados del experimento."""
    con_unidad = lambda x: f"{x.etiqueta} ({x.unidad})" if x.unidad else x.etiqueta
    columnas = [{"name": "n", "label": "N.º", "field": "n", "align": "left", "sortable": True},
                {"name": "estado", "label": "Estado", "field": "estado", "align": "left", "sortable": True},
                {"name": "origen", "label": "Origen", "field": "origen", "align": "left", "sortable": True}]
    columnas += [{"name": "v_" + v.nombre, "label": con_unidad(v), "field": "v_" + v.nombre, "align": "right"}
                 for v in exp.variables]
    columnas += [{"name": "o_" + o.nombre, "label": con_unidad(o), "field": "o_" + o.nombre, "align": "right",
                  "headerStyle": "font-weight:700"} for o in exp.objetivos]
    registros = sorted({k for f in filas for k in f.get("registros", {})})
    columnas += [{"name": "r_" + r, "label": r, "field": "r_" + r, "align": "right"} for r in registros]
    columnas += [{"name": "fecha", "label": "Fecha", "field": "fecha", "align": "left",
                  "style": "white-space: nowrap"},
                 {"name": "notas", "label": "Notas", "field": "notas", "align": "left", "style": "min-width: 180px"}]
    cuerpo = []
    for f in filas:
        fila = {"n": f["n"], "estado": TEXTO_ESTADO.get(f["estado"], f["estado"]),
                "origen": TEXTO_ORIGEN.get(f["origen"], f["origen"]), "fecha": f["fecha"], "notas": f.get("notas", "")}
        if destacar and f["n"] in destacar:
            fila["estado"] += " · Pareto"
        fila.update({"v_" + v.nombre: numero_txt(f["variables"].get(v.nombre)) for v in exp.variables})
        fila.update({"o_" + o.nombre: numero_txt(f["resultados"].get(o.nombre)) for o in exp.objetivos})
        fila.update({"r_" + r: numero_txt(f.get("registros", {}).get(r)) for r in registros})
        cuerpo.append(fila)
    return columnas, cuerpo


def pantalla_historial(motor, exp: Experimento | None, refrescar) -> None:
    titulo("Historial", "Los experimentos ya hechos sobre esta reacción. El programa los analiza para decidir el "
                        "próximo. Hace falta al menos uno para empezar; cuantos más cargue, mejor arranca.")
    if exp is None:
        with seccion("Sin experimento"):
            ui.label("Primero cree un experimento en el paso 2.").classes("sdl-ayuda")
        return
    historial = motor.historial_de(exp)
    filas = historial.filas()
    usables, motivos = historial.usables(exp)
    en_curso = motor.ocupado()

    with seccion(f"Reacción «{exp.reaccion or exp.id}»"):
        cuenta = lambda estado: sum(1 for f in filas if f["estado"] == estado)
        if usables:
            nivel("ok", f"{len(usables)} experimento(s) utilizable(s): {cuenta(COMPLETADO)} completado(s) y "
                        f"{cuenta(FALLIDO)} sin reacción (estos se penalizan).")
        else:
            nivel("error", "No hay ningún experimento utilizable. Cargue al menos uno para poder iniciar.")
        if motivos:
            nivel("aviso", f"{len(motivos)} experimento(s) no se usan porque no tienen valor para todas las "
                           "variables actuales.")
        with ui.row().classes("gap-2 q-mt-xs"):
            boton("Agregar experimento previo", lambda: _dialogo_agregar(exp, historial, refrescar), "secundario",
                  "add").set_enabled(not en_curso)
            boton("Importar desde planilla", lambda: _dialogo_importar(exp, historial, refrescar), "texto",
                  "upload_file").set_enabled(not en_curso)
            boton("Exportar (CSV para Excel)", lambda: ui.download.content(
                "﻿" + historial.texto_csv(decimal=","), f"historial_{exp.reaccion or exp.id}.csv"),
                "texto", "download").set_enabled(bool(filas))

        if not filas:
            return
        columnas, cuerpo = columnas_y_filas(exp, filas)
        tabla = ui.table(columns=columnas, rows=cuerpo, row_key="n", selection="single",
                         pagination={"rowsPerPage": 15, "sortBy": "n", "descending": True}) \
            .props("dense flat wrap-cells").classes("w-full q-mt-sm")

        def cambiar_estado(nuevo: str):
            if not tabla.selected:
                avisar("Seleccione primero un experimento de la tabla.", "aviso")
                return
            n = tabla.selected[0]["n"]
            fila = historial.fila(n)
            if fila["estado"] == EN_CURSO:
                avisar("Ese experimento se está ejecutando.", "aviso")
                return
            if nuevo == COMPLETADO and not fila["resultados"]:
                nuevo = FALLIDO if "no ocurrió" in fila.get("notas", "") else ABORTADO
            historial.actualizar(n, estado=nuevo)
            refrescar()
        with ui.row().classes("gap-2 items-center"):
            ui.label("Con el experimento seleccionado:").classes("sdl-chico")
            boton("Descartar (no usarlo)", lambda: cambiar_estado(DESCARTADO), "texto").set_enabled(not en_curso)
            boton("Volver a usarlo", lambda: cambiar_estado(COMPLETADO), "texto").set_enabled(not en_curso)
        ui.label("Descarte un experimento si sabe que salió mal por un motivo ajeno a las variables "
                 "(un derrame, un reactivo vencido). No se borra: queda anotado y fuera del análisis.").classes("sdl-chico")


def _dialogo_agregar(exp: Experimento, historial, refrescar) -> None:
    with ui.dialog() as dialogo, ui.card().style("min-width: 560px"):
        ui.label("Agregar experimento previo").classes("sdl-h2")
        ui.label("Condiciones usadas").classes("sdl-chico")
        variables = {}
        with ui.element("div").style("display:grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; width: 100%"):
            for v in exp.variables:
                variables[v.nombre] = numero(v.etiqueta, None, v.unidad, ancho="w-full")
        ocurrio = ui.radio({True: "La reacción ocurrió", False: "La reacción no ocurrió"}, value=True).props("inline")
        zona = ui.element("div").style("display:grid; grid-template-columns: 1fr 1fr; gap: 10px 14px; width: 100%")
        resultados = {}
        with zona:
            for o in exp.objetivos:
                resultados[o.nombre] = numero(o.etiqueta, None, o.unidad, ancho="w-full")
        zona.bind_visibility_from(ocurrio, "value")
        notas = texto("Notas (opcional)", "", "w-full")

        def aceptar():
            if any(c.value is None for c in variables.values()):
                avisar("Complete el valor de todas las variables.", "aviso")
                return
            if ocurrio.value and any(c.value is None for c in resultados.values()):
                avisar("Complete el resultado de todos los objetivos (o marque que la reacción no ocurrió).", "aviso")
                return
            fuera = [v.etiqueta for v in exp.variables
                     if not v.minimo <= float(variables[v.nombre].value) <= v.maximo]
            historial.agregar({k: c.value for k, c in variables.items()},
                              {k: c.value for k, c in resultados.items()} if ocurrio.value else {},
                              estado=COMPLETADO if ocurrio.value else FALLIDO, origen="previo",
                              notas=(notas.value or "").strip())
            dialogo.close()
            if fuera:
                avisar("Guardado. Nota: está fuera de los límites actuales de " + ", ".join(fuera)
                       + "; igual se usa para aprender.", "info")
            refrescar()
        with ui.row().classes("w-full justify-end gap-2"):
            boton("Cancelar", dialogo.close, "texto")
            boton("Guardar", aceptar)
    dialogo.open()


def _dialogo_importar(exp: Experimento, historial, refrescar) -> None:
    encabezado = (["estado"] + [f"var:{v.nombre}" for v in exp.variables]
                  + [f"obj:{o.nombre}" for o in exp.objetivos] + ["notas"])
    plantilla = "﻿" + ";".join(encabezado) + "\n" + ";".join(
        ["completado"] + [""] * (len(encabezado) - 2) + ["(borre esta fila; estado: completado o fallido)"]) + "\n"
    with ui.dialog() as dialogo, ui.card().style("min-width: 560px"):
        ui.label("Importar experimentos desde una planilla").classes("sdl-h2")
        ui.label("1. Descargue la plantilla y ábrala con Excel. 2. Escriba un experimento por fila, sin cambiar "
                 "los títulos de las columnas. 3. Guárdela como CSV y súbala acá.").classes("sdl-ayuda")
        boton("Descargar plantilla", lambda: ui.download.content(plantilla, f"plantilla_{exp.id}.csv"),
              "secundario", "download")

        async def subir(e):
            try:
                contenido = await e.file.read()
                try:
                    texto_csv = contenido.decode("utf-8-sig")
                except UnicodeDecodeError:
                    texto_csv = contenido.decode("latin-1")          # Excel a veces guarda así
                cantidad = historial.importar(texto_csv)
            except Exception as error:
                avisar(f"No se pudo leer el archivo: {error}", "error")
                return
            dialogo.close()
            avisar(f"Se importaron {cantidad} experimento(s).", "ok" if cantidad else "aviso")
            refrescar()
        ui.upload(on_upload=subir, auto_upload=True, max_files=1, label="Elegir archivo CSV") \
            .props('accept=".csv,.txt" flat bordered').classes("w-full")
        with ui.row().classes("w-full justify-end"):
            boton("Cerrar", dialogo.close, "texto")
    dialogo.open()
