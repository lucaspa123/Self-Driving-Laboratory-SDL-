"""Gráficos de la interfaz (ECharts): avance por objetivo y frente de Pareto.

Un gráfico por objetivo (nunca dos escalas en un mismo gráfico). El azul marca
lo medido; la línea oscura, el mejor valor conseguido hasta ese momento.
"""
from __future__ import annotations

from ..historial import COMPLETADO, FALLIDO
from ..modelos import ALCANZAR, MAXIMIZAR, Experimento, numero_txt
from .comunes import AZUL_DATOS, GRIS_DATOS, LINEA, PIZARRA, TINTA

_EJE = {"axisLine": {"lineStyle": {"color": LINEA}}, "axisTick": {"show": False},
        "axisLabel": {"color": PIZARRA, "fontSize": 12, ":formatter": "v => String(v).replace('.', ',')"},
        "nameTextStyle": {"color": PIZARRA, "fontSize": 12}}
_LEYENDA = {"top": 0, "right": 0, "itemWidth": 14, "itemHeight": 8, "textStyle": {"color": PIZARRA, "fontSize": 12}}
_TITULO = {"left": 0, "top": 0, "textStyle": {"fontSize": 13.5, "fontWeight": 600, "color": TINTA}}
_PUNTO = {"borderColor": "#ffffff", "borderWidth": 2}


def _con_unidad(o) -> str:
    return f"{o.etiqueta} ({o.unidad})" if o.unidad else o.etiqueta


def opciones_avance(o, filas: list[dict], analisis: dict, ultimo: bool = True) -> dict:
    orden = list(range(1, len(filas) + 1))
    medidos = [[i, f["resultados"][o.nombre], f["n"]] for i, f in zip(orden, filas)
               if f["estado"] == COMPLETADO and o.nombre in f["resultados"]]
    mejor = [[i, y] for i, y in zip(orden, analisis["acumulado"].get(o.nombre, [])) if y is not None]
    valores = [m[1] for m in medidos]
    series = [
        {"name": "Mejor hasta ese momento", "type": "line", "step": "end", "data": mejor, "showSymbol": False,
         "lineStyle": {"width": 2, "color": TINTA}, "itemStyle": {"color": TINTA}, "z": 2},
        {"name": "Medido", "type": "scatter", "data": medidos, "symbolSize": 10, "z": 3,
         "itemStyle": {"color": AZUL_DATOS, **_PUNTO}},
    ]
    if valores and any(f["estado"] == FALLIDO for f in filas):
        piso = min(valores) - 0.1 * ((max(valores) - min(valores)) or 1.0)
        series.append({"name": "Sin reacción", "type": "scatter", "symbol": "diamond", "symbolSize": 10, "z": 3,
                       "data": [[i, piso, f["n"]] for i, f in zip(orden, filas) if f["estado"] == FALLIDO],
                       "itemStyle": {"color": "#ffffff", "borderColor": GRIS_DATOS, "borderWidth": 2}})
    referencia = o.valor if o.direccion == ALCANZAR else o.meta
    if referencia is not None:
        series[1]["markLine"] = {
            "silent": True, "symbol": "none", "data": [{"yAxis": referencia}],
            "lineStyle": {"color": AZUL_DATOS, "opacity": 0.55, "type": "solid", "width": 1},
            "label": {"formatter": "valor buscado" if o.direccion == ALCANZAR else "meta", "position": "insideEndTop",
                      "color": PIZARRA, "fontSize": 11}}
    unidad = f" {o.unidad}" if o.unidad else ""
    return {
        "animation": False,
        "title": {**_TITULO, "text": _con_unidad(o)},
        "legend": _LEYENDA,
        "grid": {"left": 8, "right": 14, "top": 40, "bottom": 30 if ultimo else 12, "containLabel": True},
        "tooltip": {"trigger": "item", "confine": True,
                    ":formatter": "p => p.seriesName === 'Mejor hasta ese momento' ? p.seriesName + ': <b>' + "
                                  "String(p.value[1]).replace('.', ',') + '" + unidad + "</b>' : "
                                  "(p.seriesName === 'Sin reacción' ? 'Experimento n.º ' + p.value[2] + ': la reacción no ocurrió' : "
                                  "'Experimento n.º ' + p.value[2] + ': <b>' + String(p.value[1]).replace('.', ',') + '"
                                  + unidad + "</b>')"},
        "xAxis": {**_EJE, "type": "value", "min": 1, "max": max(len(filas), 5), "minInterval": 1,
                  "splitLine": {"show": False}, "name": "Orden del experimento" if ultimo else "",
                  "nameLocation": "middle", "nameGap": 24},
        "yAxis": {**_EJE, "type": "value", "scale": True, "splitLine": {"lineStyle": {"color": LINEA}},
                  "axisLine": {"show": False}},
        "series": series,
    }


def opciones_pareto(exp: Experimento, filas: list[dict], analisis: dict) -> dict | None:
    if len(exp.objetivos) < 2:
        return None
    a, b = exp.objetivos[0], exp.objetivos[1]
    completos = [f for f in filas if f["estado"] == COMPLETADO and a.nombre in f["resultados"]
                 and b.nombre in f["resultados"]]
    if len(completos) < 2:
        return None
    punto = lambda f: [f["resultados"][a.nombre], f["resultados"][b.nombre], f["n"]]
    frente = sorted((punto(f) for f in completos if f["n"] in analisis["pareto"]), key=lambda p: p[0])
    resto = [punto(f) for f in completos if f["n"] not in analisis["pareto"]]

    def sentido(o) -> str:
        if o.direccion == ALCANZAR:
            return f"buscado: {numero_txt(o.valor)}"
        return "más es mejor" if o.direccion == MAXIMIZAR else "menos es mejor"
    equilibrio = analisis.get("equilibrio")
    return {
        "animation": False,
        "title": {**_TITULO, "text": f"{a.etiqueta} frente a {b.etiqueta}"},
        "legend": _LEYENDA,
        "grid": {"left": 8, "right": 20, "top": 40, "bottom": 34, "containLabel": True},
        "tooltip": {"trigger": "item", "confine": True,
                    ":formatter": "p => 'Experimento n.º ' + p.value[2] + '<br>" + a.etiqueta + ": <b>' + "
                                  "String(p.value[0]).replace('.', ',') + '</b><br>" + b.etiqueta + ": <b>' + "
                                  "String(p.value[1]).replace('.', ',') + '</b>'"},
        "xAxis": {**_EJE, "type": "value", "scale": True, "name": f"{_con_unidad(a)} — {sentido(a)}",
                  "nameLocation": "middle", "nameGap": 26, "splitLine": {"lineStyle": {"color": LINEA}}},
        "yAxis": {**_EJE, "type": "value", "scale": True, "name": f"{_con_unidad(b)} — {sentido(b)}",
                  "nameLocation": "middle", "nameGap": 40, "splitLine": {"lineStyle": {"color": LINEA}},
                  "axisLine": {"show": False}},
        "series": [
            {"name": "Otros experimentos", "type": "scatter", "data": resto, "symbolSize": 9,
             "itemStyle": {"color": GRIS_DATOS, **_PUNTO}},
            {"name": "Frente de Pareto", "type": "line", "data": frente, "symbolSize": 12, "symbol": "circle",
             "lineStyle": {"width": 2, "color": AZUL_DATOS, "opacity": 0.55},
             "itemStyle": {"color": AZUL_DATOS, **_PUNTO}, "labelLayout": {"hideOverlap": True},
             "label": {"show": True, "position": "top", "color": TINTA, "fontSize": 11.5,
                       ":formatter": f"p => p.value[2] === {equilibrio if equilibrio is not None else -1} ? "
                                     "'n.º ' + p.value[2] + ' · mejor equilibrio' : 'n.º ' + p.value[2]"}},
        ],
    }
