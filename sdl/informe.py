"""Informe final de una campaña, en PDF.

Contiene: resumen, definición del experimento, mejores resultados (mejor por
objetivo, frente de Pareto y mejor equilibrio), gráficos de avance y la tabla
completa de experimentos con cada variable y su resultado.
"""
from __future__ import annotations

import io
from datetime import datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
                                Table, TableStyle)

from .historial import ABORTADO, COMPLETADO, DESCARTADO, FALLIDO
from .modelos import ALCANZAR, MAXIMIZAR, Experimento, numero_txt
from .optimizador import Optimizador

# Colores (los mismos que la interfaz)
TINTA, PIZARRA, LINEA, NIEBLA = "#1f2933", "#5b6672", "#dde3ea", "#f3f6f9"
AZUL, GRIS_MARCA, CELESTE_SUAVE = "#2a78d6", "#8a949e", "#e8f3fb"

TEXTO_ESTADO = {COMPLETADO: "Completado", FALLIDO: "Sin reacción", ABORTADO: "Abortado",
                DESCARTADO: "Descartado", "en_curso": "En curso"}
TEXTO_ORIGEN = {"previo": "Previo", "exploracion": "Exploración", "optimizacion": "Optimización",
                "repeticion": "Repetición", "manual": "Manual"}


def _fuentes() -> tuple[str, str]:
    """Usa DejaVu (viene con matplotlib) para que salgan bien acentos, ° y subíndices."""
    try:
        carpeta = Path(matplotlib.get_data_path()) / "fonts" / "ttf"
        if "SDL" not in pdfmetrics.getRegisteredFontNames():
            pdfmetrics.registerFont(TTFont("SDL", str(carpeta / "DejaVuSans.ttf")))
            pdfmetrics.registerFont(TTFont("SDL-Negrita", str(carpeta / "DejaVuSans-Bold.ttf")))
        return "SDL", "SDL-Negrita"
    except Exception:
        return "Helvetica", "Helvetica-Bold"


# --- gráficos -----------------------------------------------------------------
def _estilo_ejes(ax) -> None:
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)
    for lado in ("left", "bottom"):
        ax.spines[lado].set_color(LINEA)
    ax.tick_params(colors=PIZARRA, labelsize=8, length=0)
    ax.grid(True, axis="y", color=LINEA, linewidth=0.6)
    ax.set_axisbelow(True)


def _png(fig) -> io.BytesIO:
    memoria = io.BytesIO()
    fig.savefig(memoria, format="png", dpi=200, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    memoria.seek(0)
    return memoria


def grafico_avance(exp: Experimento, filas: list[dict], analisis: dict) -> io.BytesIO:
    """Un panel por objetivo: valor medido en cada experimento y mejor valor hasta ese momento."""
    m = len(exp.objetivos)
    fig, ejes = plt.subplots(m, 1, figsize=(9.5, 2.3 * m), squeeze=False, sharex=True)
    orden = list(range(1, len(filas) + 1))
    for j, o in enumerate(exp.objetivos):
        ax = ejes[j][0]
        _estilo_ejes(ax)
        xs = [i for i, f in zip(orden, filas) if f["estado"] == COMPLETADO and o.nombre in f["resultados"]]
        ys = [f["resultados"][o.nombre] for f in filas if f["estado"] == COMPLETADO and o.nombre in f["resultados"]]
        mejor = analisis["acumulado"].get(o.nombre, [])
        puntos = [(i, y) for i, y in zip(orden, mejor) if y is not None]
        if puntos:
            ax.step([p[0] for p in puntos], [p[1] for p in puntos], where="post", color=TINTA, linewidth=1.6,
                    label="Mejor hasta ese momento")
        ax.scatter(xs, ys, s=34, color=AZUL, edgecolors="white", linewidths=1.2, zorder=3, label="Medido")
        fallidos = [i for i, f in zip(orden, filas) if f["estado"] == FALLIDO]
        if fallidos and ys:
            base = min(ys) - 0.08 * (max(ys) - min(ys) or 1.0)
            ax.scatter(fallidos, [base] * len(fallidos), s=30, marker="x", color=GRIS_MARCA, linewidths=1.4,
                       zorder=3, label="Sin reacción")
        referencia = o.valor if o.direccion == ALCANZAR else o.meta
        if referencia is not None:
            ax.axhline(referencia, color=AZUL, linewidth=1.0, alpha=0.55)
            ax.annotate("meta" if o.direccion != ALCANZAR else "valor buscado", (1.0, referencia),
                        xycoords=("axes fraction", "data"), xytext=(-4, 4), textcoords="offset points",
                        ha="right", fontsize=7.5, color=PIZARRA)
        unidad = f" ({o.unidad})" if o.unidad else ""
        ax.set_title(f"{o.etiqueta}{unidad}", loc="left", fontsize=9.5, color=TINTA, pad=6)
        if j == 0:
            ax.legend(frameon=False, fontsize=7.5, loc="upper left", bbox_to_anchor=(0.42, 1.24), ncol=3,
                      labelcolor=PIZARRA, handlelength=1.4, columnspacing=1.2)
    ejes[-1][0].set_xlabel("Orden del experimento", fontsize=8.5, color=PIZARRA)
    if orden:
        paso = max(1, len(orden) // 15)
        ejes[-1][0].set_xticks(orden[::paso])
    fig.tight_layout()
    return _png(fig)


def grafico_pareto(exp: Experimento, filas: list[dict], analisis: dict) -> io.BytesIO | None:
    """Dos primeros objetivos enfrentados; se destaca el frente de Pareto."""
    if len(exp.objetivos) < 2:
        return None
    a, b = exp.objetivos[0], exp.objetivos[1]
    completos = [f for f in filas if f["estado"] == COMPLETADO and a.nombre in f["resultados"]
                 and b.nombre in f["resultados"]]
    if len(completos) < 2:
        return None
    frente = [f for f in completos if f["n"] in analisis["pareto"]]
    resto = [f for f in completos if f["n"] not in analisis["pareto"]]
    fig, ax = plt.subplots(figsize=(6.2, 4.2))
    _estilo_ejes(ax)
    ax.grid(True, axis="x", color=LINEA, linewidth=0.6)
    ax.scatter([f["resultados"][a.nombre] for f in resto], [f["resultados"][b.nombre] for f in resto],
               s=30, color=GRIS_MARCA, edgecolors="white", linewidths=1.0, label="Otros experimentos", zorder=2)
    frente.sort(key=lambda f: f["resultados"][a.nombre])
    ax.plot([f["resultados"][a.nombre] for f in frente], [f["resultados"][b.nombre] for f in frente],
            color=AZUL, linewidth=1.4, alpha=0.6, zorder=3)
    ax.scatter([f["resultados"][a.nombre] for f in frente], [f["resultados"][b.nombre] for f in frente],
               s=52, color=AZUL, edgecolors="white", linewidths=1.3, label="Frente de Pareto", zorder=4)
    for f in frente:
        etiqueta = f"n.º {f['n']}" + (" (mejor equilibrio)" if f["n"] == analisis["equilibrio"] else "")
        ax.annotate(etiqueta, (f["resultados"][a.nombre], f["resultados"][b.nombre]), xytext=(6, 6),
                    textcoords="offset points", fontsize=7.5, color=TINTA)

    def titulo(o):
        sentido = {MAXIMIZAR: "más es mejor", ALCANZAR: f"buscado: {numero_txt(o.valor)}"}.get(o.direccion, "menos es mejor")
        return f"{o.etiqueta}{f' ({o.unidad})' if o.unidad else ''} — {sentido}"
    ax.set_xlabel(titulo(a), fontsize=8.5, color=PIZARRA)
    ax.set_ylabel(titulo(b), fontsize=8.5, color=PIZARRA)
    ax.legend(frameon=False, fontsize=8, loc="best", labelcolor=PIZARRA)
    fig.tight_layout()
    return _png(fig)


# --- documento ------------------------------------------------------------------
def generar_informe(exp: Experimento, historial, carpeta: Path, motivo_fin: str = "", campana: str = "",
                    pasos: list[str] | None = None) -> Path:
    """Escribe el PDF y devuelve su ruta."""
    normal, negrita = _fuentes()
    carpeta = Path(carpeta)
    carpeta.mkdir(parents=True, exist_ok=True)
    ahora = datetime.now()
    ruta = carpeta / f"informe_{exp.id}_{ahora:%Y%m%d-%H%M%S}.pdf"

    todas = historial.filas()
    usables, _ = historial.usables(exp)
    analisis = Optimizador(exp, 0).analizar(usables)
    por_n = {f["n"]: f for f in todas}

    e_titulo = ParagraphStyle("titulo", fontName=negrita, fontSize=17, leading=21, textColor=colors.HexColor(TINTA))
    e_sub = ParagraphStyle("sub", fontName=normal, fontSize=9.5, leading=13, textColor=colors.HexColor(PIZARRA))
    e_h2 = ParagraphStyle("h2", fontName=negrita, fontSize=11.5, leading=15, textColor=colors.HexColor(TINTA),
                          spaceBefore=12, spaceAfter=5)
    e_txt = ParagraphStyle("txt", fontName=normal, fontSize=9, leading=12.5, textColor=colors.HexColor(TINTA),
                           alignment=TA_LEFT)
    e_celda = ParagraphStyle("celda", fontName=normal, fontSize=7.5, leading=9.5, textColor=colors.HexColor(TINTA))
    e_cab = ParagraphStyle("cab", fontName=negrita, fontSize=7.5, leading=9.5, textColor=colors.HexColor(TINTA))

    def tabla(encabezado: list[str], cuerpo: list[list], anchos=None, resaltar: set[int] | None = None) -> Table:
        datos = [[Paragraph(str(c), e_cab) for c in encabezado]]
        datos += [[Paragraph(str(c), e_celda) for c in fila] for fila in cuerpo]
        t = Table(datos, colWidths=anchos, repeatRows=1, hAlign="LEFT")
        estilo = [("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(NIEBLA)),
                  ("LINEBELOW", (0, 0), (-1, -1), 0.4, colors.HexColor(LINEA)),
                  ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                  ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                  ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        for i in sorted(resaltar or ()):
            estilo.append(("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor(CELESTE_SUAVE)))
        t.setStyle(TableStyle(estilo))
        return t

    def con_unidad(etiqueta: str, unidad: str) -> str:
        return f"{etiqueta} ({unidad})" if unidad else etiqueta

    def valores_de(fila: dict) -> list[str]:
        return ([numero_txt(fila["variables"].get(v.nombre)) for v in exp.variables]
                + [numero_txt(fila["resultados"].get(o.nombre)) for o in exp.objetivos])

    cab_valores = ([con_unidad(v.etiqueta, v.unidad) for v in exp.variables]
                   + [con_unidad(o.etiqueta, o.unidad) for o in exp.objetivos])
    h = []

    # 1. Encabezado y resumen
    h.append(Paragraph(f"Informe de campaña: {exp.nombre}", e_titulo))
    h.append(Paragraph(f"Reacción: {exp.reaccion or exp.id} · Generado el {ahora:%d/%m/%Y a las %H:%M}"
                       + (f" · Campaña iniciada el {campana}" if campana else ""), e_sub))
    h.append(Spacer(1, 8))
    de_campana = [f for f in todas if campana and f.get("campana") == campana]
    cuenta = lambda filas, estado: sum(1 for f in filas if f["estado"] == estado)
    lineas = []
    if motivo_fin:
        lineas.append(f"<b>Motivo de finalización:</b> {motivo_fin}")
    if campana:
        lineas.append(f"<b>En esta campaña:</b> {len(de_campana)} experimento(s): {cuenta(de_campana, COMPLETADO)} "
                      f"completado(s), {cuenta(de_campana, FALLIDO)} sin reacción, {cuenta(de_campana, ABORTADO)} abortado(s).")
    lineas.append(f"<b>Historial total de la reacción:</b> {len(todas)} experimento(s): {cuenta(todas, COMPLETADO)} "
                  f"completado(s), {cuenta(todas, FALLIDO)} sin reacción (penalizados), {cuenta(todas, ABORTADO)} "
                  f"abortado(s), {cuenta(todas, DESCARTADO)} descartado(s). El análisis usa {len(usables)}.")
    if exp.descripcion:
        lineas.append(f"<b>Descripción:</b> {exp.descripcion}")
    for linea in lineas:
        h.append(Paragraph(linea, e_txt))
        h.append(Spacer(1, 2))

    # 2. Mejores resultados
    h.append(Paragraph("Mejores resultados", e_h2))
    if not analisis["pareto"]:
        h.append(Paragraph("Todavía no hay experimentos completados con todos los objetivos medidos.", e_txt))
    else:
        cuerpo = []
        for o in exp.objetivos:
            n = analisis["mejor_por_objetivo"].get(o.nombre)
            if n in por_n:
                cuerpo.append([f"Mejor {o.etiqueta}", n] + valores_de(por_n[n]))
        equilibrio = analisis["equilibrio"]
        if equilibrio in por_n and len(exp.objetivos) > 1:
            cuerpo.append(["Mejor equilibrio entre objetivos", equilibrio] + valores_de(por_n[equilibrio]))
        h.append(tabla(["Criterio", "Exp. n.º"] + cab_valores, cuerpo))
        if analisis["cumplen"]:
            h.append(Spacer(1, 4))
            h.append(Paragraph("Experimentos que cumplen todas las metas: n.º "
                               + ", ".join(str(n) for n in analisis["cumplen"]) + ".", e_txt))
        elif any(o.tiene_meta() for o in exp.objetivos):
            h.append(Spacer(1, 4))
            h.append(Paragraph("Ningún experimento cumplió todas las metas a la vez.", e_txt))
        if len(exp.objetivos) > 1:
            h.append(Paragraph("Frente de Pareto", e_h2))
            h.append(Paragraph("Experimentos que ningún otro supera en todos los objetivos a la vez: mejorar un "
                               "objetivo a partir de ellos obliga a empeorar otro. Resaltado: el mejor equilibrio.", e_txt))
            h.append(Spacer(1, 4))
            frente = [por_n[n] for n in analisis["pareto"] if n in por_n]
            h.append(tabla(["Exp. n.º"] + cab_valores, [[f["n"]] + valores_de(f) for f in frente],
                           resaltar={i for i, f in enumerate(frente) if f["n"] == equilibrio}))

    # 3. Gráficos (una página: avance a la izquierda, Pareto a la derecha)
    if any(f["estado"] == COMPLETADO for f in usables):
        h.append(PageBreak())
        h.append(Paragraph("Avance de la campaña", e_h2))
        h.append(Paragraph("Cada punto es un experimento, en el orden en que se hizo. La línea oscura es el mejor "
                           "valor conseguido hasta ese momento." + (" A la derecha, los dos primeros objetivos "
                           "enfrentados." if len(exp.objetivos) > 1 else ""), e_txt))
        h.append(Spacer(1, 6))
        avance = Image(grafico_avance(exp, usables, analisis), width=150 * mm, height=140 * mm, kind="proportional")
        pareto = grafico_pareto(exp, usables, analisis)
        if pareto is not None:
            derecha = Image(pareto, width=110 * mm, height=140 * mm, kind="proportional")
            marco = Table([[avance, derecha]], colWidths=[154 * mm, 112 * mm], hAlign="LEFT")
            marco.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"), ("LEFTPADDING", (0, 0), (-1, -1), 0)]))
            h.append(marco)
        else:
            h.append(avance)

    # 4. Definición del experimento
    h.append(PageBreak())
    h.append(Paragraph("Definición del experimento", e_h2))
    origenes = {"modulo": "Automático", "tiempo": "Tiempo de espera", "manual": "Manual (usuario)"}
    h.append(tabla(["Variable", "Mínimo", "Máximo", "Resolución", "Cómo se ajusta"],
                   [[con_unidad(v.etiqueta, v.unidad), numero_txt(v.minimo), numero_txt(v.maximo),
                     numero_txt(v.paso) if v.paso else "continua",
                     origenes.get(v.origen, v.origen) + (f" · {v.modulo}" if v.origen == "modulo" else "")]
                    for v in exp.variables]))
    h.append(Spacer(1, 6))
    h.append(tabla(["Objetivo", "Qué se busca", "Cómo se mide"],
                   [[con_unidad(o.etiqueta, o.unidad), o.texto_meta(),
                     f"Automático · {o.modulo}" if o.medicion == "modulo" else "Lo ingresa el usuario"]
                    for o in exp.objetivos]))
    h.append(Spacer(1, 6))
    extras = [f"<b>Máximo de experimentos por campaña:</b> {exp.max_experimentos}",
              f"<b>Capacidad del vaso:</b> {numero_txt(exp.capacidad_vaso_ml)} mL"]
    if exp.restricciones:
        extras.append("<b>Restricciones:</b> " + "; ".join(r for r in exp.restricciones if r.strip()))
    if exp.reactivos:
        extras.append("<b>Reactivos:</b> " + "; ".join(f"{m}: {r}" for m, r in exp.reactivos.items() if str(r).strip()))
    for linea in extras:
        h.append(Paragraph(linea, e_txt))
    if pasos:
        h.append(Spacer(1, 4))
        h.append(Paragraph("<b>Protocolo:</b>", e_txt))
        for i, texto in enumerate(pasos, 1):
            h.append(Paragraph(f"{i}. {texto}", e_txt))

    # 5. Tabla completa
    h.append(Paragraph("Todos los experimentos", e_h2))
    registros = sorted({k for f in todas for k in f.get("registros", {})})
    cuerpo, resaltar = [], set()
    for i, f in enumerate(todas):
        cuerpo.append([f["n"], f["fecha"], TEXTO_ORIGEN.get(f["origen"], f["origen"]),
                       TEXTO_ESTADO.get(f["estado"], f["estado"])] + valores_de(f)
                      + [numero_txt(f.get("registros", {}).get(r)) for r in registros] + [f.get("notas", "")])
        if f["n"] in analisis["pareto"]:
            resaltar.add(i)
    h.append(Paragraph("Resaltados: experimentos del frente de Pareto. «Sin reacción»: el químico indicó que la "
                       "reacción no ocurrió; el optimizador penaliza esa zona.", e_txt))
    h.append(Spacer(1, 4))
    h.append(tabla(["N.º", "Fecha", "Origen", "Estado"] + cab_valores + registros + ["Notas"], cuerpo,
                   resaltar=resaltar))

    def pie(lienzo, doc):
        lienzo.saveState()
        lienzo.setFont(normal, 7.5)
        lienzo.setFillColor(colors.HexColor(PIZARRA))
        lienzo.drawString(15 * mm, 9 * mm, f"SDL · {exp.nombre}")
        lienzo.drawRightString(doc.pagesize[0] - 15 * mm, 9 * mm, f"Página {doc.page}")
        lienzo.restoreState()

    doc = SimpleDocTemplate(str(ruta), pagesize=landscape(A4), leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=14 * mm, bottomMargin=16 * mm, title=f"Informe: {exp.nombre}", author="SDL")
    doc.build(h, onFirstPage=pie, onLaterPages=pie)
    return ruta
