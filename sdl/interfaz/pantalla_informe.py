"""Pantalla 5 — Informe: mejores resultados, frente de Pareto, gráficos y descarga del PDF."""
from __future__ import annotations

from nicegui import run, ui

from ..informe import generar_informe
from ..modelos import Experimento, numero_txt
from ..motor import texto_paso
from .comunes import avisar, boton, fila, nivel, seccion, titulo
from .graficos import opciones_avance, opciones_pareto
from .pantalla_historial import columnas_y_filas


def bloque_graficos(exp: Experimento, usables: list[dict], analisis: dict) -> None:
    """Un gráfico de avance por objetivo y, si hay dos o más objetivos, el frente de Pareto."""
    if not analisis["n_exitosos"]:
        ui.label("Los gráficos aparecen cuando hay al menos un experimento completado.").classes("sdl-chico")
        return
    pareto = opciones_pareto(exp, usables, analisis)
    with ui.element("div").style("display:grid; gap: 18px 28px; width:100%; grid-template-columns: "
                                 + ("minmax(0,1.15fr) minmax(0,1fr)" if pareto else "minmax(0,1fr)")):
        with ui.column().classes("gap-3 w-full"):
            for j, o in enumerate(exp.objetivos):
                ui.echart(opciones_avance(o, usables, analisis, ultimo=j == len(exp.objetivos) - 1)) \
                    .classes("w-full").style("height: 220px")
        if pareto:
            with ui.column().classes("gap-1 w-full"):
                ui.echart(pareto).classes("w-full").style("height: 340px")
                ui.label("El frente de Pareto reúne los experimentos que ningún otro supera en los dos objetivos "
                         "a la vez. Elegir entre ellos es una decisión suya.").classes("sdl-chico")


def tabla_mejores(exp: Experimento, por_n: dict, analisis: dict) -> None:
    columnas = "minmax(190px,1.6fr) 60px " + " ".join(["minmax(70px,1fr)"] * (len(exp.variables) + len(exp.objetivos)))
    con_unidad = lambda x: f"{x.etiqueta} ({x.unidad})" if x.unidad else x.etiqueta
    with fila(columnas, cabecera=True):
        ui.label("Criterio")
        ui.label("N.º")
        for x in [*exp.variables, *exp.objetivos]:
            ui.label(con_unidad(x))

    def renglon(criterio: str, n: int):
        f = por_n.get(n)
        if f is None:
            return
        with fila(columnas):
            ui.label(criterio).style("font-weight:600")
            ui.label(str(n))
            for v in exp.variables:
                ui.label(numero_txt(f["variables"].get(v.nombre)))
            for o in exp.objetivos:
                ui.label(numero_txt(f["resultados"].get(o.nombre))).style("font-weight:600")
    for o in exp.objetivos:
        if o.nombre in analisis["mejor_por_objetivo"]:
            renglon(f"Mejor {o.etiqueta}", analisis["mejor_por_objetivo"][o.nombre])
    if len(exp.objetivos) > 1 and analisis["equilibrio"] is not None:
        renglon("Mejor equilibrio", analisis["equilibrio"])


def pantalla_informe(motor, exp: Experimento | None, refrescar) -> None:
    titulo("Informe", "Resumen de todos los experimentos de la reacción: qué se ensayó, qué resultó y cuáles "
                      "fueron los mejores.")
    if exp is None:
        with seccion("Sin experimento"):
            ui.label("Primero cree un experimento en el paso 2.").classes("sdl-ayuda")
        return
    historial = motor.historial_de(exp)
    todas = historial.filas()
    usables, _ = historial.usables(exp)
    analisis = motor.analizar(exp)
    por_n = {f["n"]: f for f in todas}

    async def descargar_pdf():
        try:
            misma = motor.exp is not None and motor.exp.id == exp.id
            ruta = await run.io_bound(
                generar_informe, exp, historial, motor.carpeta_reaccion(exp) / "informes",
                motor.motivo_fin if misma else "", motor.campana if misma else "",
                [texto_paso(exp, p, motor.gestor) for p in exp.protocolo])
        except Exception as error:
            avisar(f"No se pudo generar el informe: {error}", "error")
            return
        ui.download(ruta)
        avisar(f"Informe generado. También queda guardado en la carpeta de la reacción: {ruta.name}", "ok")

    with ui.row().classes("gap-2 q-mt-md"):
        boton("Descargar informe (PDF)", descargar_pdf, "principal", "picture_as_pdf").set_enabled(bool(usables))
        boton("Exportar datos (CSV para Excel)", lambda: ui.download.content(
            "﻿" + historial.texto_csv(decimal=","), f"historial_{exp.reaccion or exp.id}.csv"),
            "texto", "download").set_enabled(bool(todas))

    with seccion("Resumen"):
        if motor.exp is not None and motor.exp.id == exp.id and motor.motivo_fin:
            nivel("error" if motor.error_fin else "info", f"Última campaña: {motor.motivo_fin}")
        with ui.row().classes("gap-12 q-mt-xs"):
            datos = [("Experimentos analizados", len(usables)), ("Completados", analisis["n_exitosos"]),
                     ("Sin reacción", analisis["n_fallidos"])]
            if any(o.tiene_meta() for o in exp.objetivos):
                datos.append(("Cumplen todas las metas", len(analisis["cumplen"])))
            if len(exp.objetivos) > 1:
                datos.append(("En el frente de Pareto", len(analisis["pareto"])))
            for etiqueta, valor in datos:
                with ui.column().classes("gap-0"):
                    ui.label(str(valor)).classes("sdl-dato")
                    ui.label(etiqueta).classes("sdl-chico")
    if not usables:
        return

    with seccion("Mejores resultados"):
        if analisis["pareto"]:
            tabla_mejores(exp, por_n, analisis)
            if analisis["cumplen"]:
                nivel("ok", "Cumplen todas las metas: experimento(s) n.º " + ", ".join(map(str, analisis["cumplen"])) + ".")
            elif any(o.tiene_meta() for o in exp.objetivos):
                nivel("nada", "Ningún experimento cumplió todas las metas a la vez.")
        else:
            ui.label("Todavía no hay experimentos completados con todos los objetivos medidos.").classes("sdl-chico")

    with seccion("Avance"):
        bloque_graficos(exp, usables, analisis)

    with seccion("Todos los experimentos", "Cada fila es un experimento con el valor de cada variable y su resultado."):
        columnas, cuerpo = columnas_y_filas(exp, todas, set(analisis["pareto"]))
        ui.table(columns=columnas, rows=cuerpo, row_key="n",
                 pagination={"rowsPerPage": 20, "sortBy": "n", "descending": False}) \
            .props("dense flat wrap-cells").classes("w-full")
