"""Estilo y piezas comunes de la interfaz.

Estética: blanco, grises fríos y celeste. Sin sombras ni adornos: las líneas
finas separan, y el celeste se reserva para lo que pide atención o acción.
El rojo solo aparece en la parada de emergencia y en los errores.
"""
from __future__ import annotations

from contextlib import contextmanager

from nicegui import ui

CELESTE, CELESTE_FUERTE, CELESTE_SUAVE = "#2f9bd8", "#1976b8", "#e8f3fb"
TINTA, PIZARRA, LINEA, NIEBLA = "#1f2933", "#5b6672", "#dde3ea", "#f3f6f9"
ROJO, AMBAR, VERDE = "#c62828", "#a15c00", "#2e7d5b"
AZUL_DATOS, GRIS_DATOS = "#2a78d6", "#8a949e"      # colores de las marcas en los gráficos

CSS = """
:root { --blanco:#ffffff; --niebla:#f3f6f9; --linea:#dde3ea; --pizarra:#5b6672; --tinta:#1f2933;
        --celeste:#2f9bd8; --celeste-fuerte:#1976b8; --celeste-suave:#e8f3fb; --rojo:#c62828; }
body { font-family: "Segoe UI Variable Text", "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif;
       color: var(--tinta); background: var(--blanco); font-size: 15px; font-variant-numeric: tabular-nums; }
.nicegui-content { padding: 0; }
.q-header { background: var(--blanco); color: var(--tinta); border-bottom: 1px solid var(--linea); }
.q-drawer { background: var(--niebla); border-right: 1px solid var(--linea); }
.sdl-marca { font-size: 17px; font-weight: 650; letter-spacing: .01em; }
.sdl-marca span { color: var(--pizarra); font-weight: 400; margin-left: 8px; font-size: 14px; }
.sdl-nav { display: flex; align-items: center; gap: 12px; width: 100%; padding: 10px 18px; cursor: pointer;
           border-left: 3px solid transparent; color: var(--pizarra); font-size: 15px; }
.sdl-nav:hover { background: #e9eef3; color: var(--tinta); }
.sdl-nav.activa { background: var(--blanco); border-left-color: var(--celeste); color: var(--tinta); font-weight: 600; }
.sdl-nav .n { width: 22px; height: 22px; border-radius: 50%; border: 1px solid var(--linea); background: var(--blanco);
              font-size: 12px; display: flex; align-items: center; justify-content: center; color: var(--pizarra); }
.sdl-nav.activa .n { background: var(--celeste); border-color: var(--celeste); color: #fff; }
.sdl-pagina { max-width: 1120px; width: 100%; padding: 30px 40px 80px; gap: 0; }
.sdl-h1 { font-size: 26px; font-weight: 600; line-height: 1.2; margin: 0; letter-spacing: 0; }
.sdl-ayuda { color: var(--pizarra); font-size: 14.5px; line-height: 1.5; max-width: 74ch; }
.sdl-seccion { width: 100%; border-top: 1px solid var(--linea); padding: 22px 0 8px; margin-top: 22px; gap: 10px; }
.sdl-h2 { font-size: 17px; font-weight: 600; margin: 0; line-height: 1.3; letter-spacing: 0; }
.sdl-chico { font-size: 13px; color: var(--pizarra); }
.sdl-fila { width: 100%; display: grid; align-items: center; gap: 4px 16px; padding: 9px 0;
            border-bottom: 1px solid var(--linea); }
.sdl-fila.cab { font-size: 13px; color: var(--pizarra); padding: 4px 0 6px; }
.sdl-caja { border: 1px solid var(--linea); border-radius: 8px; padding: 16px 18px; background: var(--blanco);
            box-shadow: none; width: 100%; }
.sdl-pedido { border: 1px solid var(--celeste); border-left: 4px solid var(--celeste); background: var(--celeste-suave);
              border-radius: 8px; padding: 18px 20px; width: 100%; gap: 10px; }
.sdl-pedido .t { font-size: 18px; font-weight: 600; }
.sdl-parada { background: var(--rojo); color: #fff; padding: 12px 40px; width: 100%; align-items: center; gap: 16px;
              position: sticky; top: 60px; z-index: 10; }
.sdl-paso { display: flex; gap: 10px; align-items: baseline; padding: 5px 10px; border-radius: 6px; color: var(--pizarra);
            font-size: 14.5px; width: 100%; }
.sdl-paso.hecho { color: var(--pizarra); }
.sdl-paso.actual { background: var(--celeste-suave); color: var(--tinta); font-weight: 600; }
.sdl-paso .n { min-width: 18px; text-align: right; font-size: 12.5px; }
.sdl-dato { font-size: 26px; font-weight: 600; line-height: 1.1; }
.sdl-bitacora { font-size: 13px; line-height: 1.55; color: var(--pizarra); width: 100%; }
.sdl-bitacora .aviso { color: #a15c00; } .sdl-bitacora .error { color: var(--rojo); }
.sdl-chip { display: inline-flex; align-items: center; gap: 6px; font-size: 13.5px; padding: 3px 10px;
            border: 1px solid var(--linea); border-radius: 999px; color: var(--pizarra); background: var(--blanco); }
.q-btn { text-transform: none; font-weight: 600; letter-spacing: 0; border-radius: 6px; }
.q-field--outlined .q-field__control { border-radius: 6px; }
.q-dialog .q-card { border-radius: 10px; box-shadow: 0 10px 40px rgba(31,41,51,.18); padding: 22px 24px; min-width: 460px;
                    max-width: 640px; gap: 12px; }
.q-table { box-shadow: none; border: 1px solid var(--linea); border-radius: 8px; }
.q-table th { color: var(--pizarra); font-weight: 600; }
:focus-visible { outline: 2px solid var(--celeste); outline-offset: 2px; }
@media (max-width: 900px) { .sdl-pagina { padding: 20px 16px 60px; } }
"""

ICONOS = {"ok": ("check_circle", VERDE), "aviso": ("warning", AMBAR), "error": ("error", ROJO),
          "info": ("info", CELESTE_FUERTE), "nada": ("radio_button_unchecked", PIZARRA)}


def aplicar_estilo() -> None:
    ui.add_css(CSS)
    ui.colors(primary=CELESTE_FUERTE, secondary=PIZARRA, accent=CELESTE, negative=ROJO, positive=VERDE,
              warning="#d98e00", info=CELESTE)


def titulo(texto: str, ayuda: str = "") -> None:
    ui.html(f'<h1 class="sdl-h1">{texto}</h1>', sanitize=False)
    if ayuda:
        ui.label(ayuda).classes("sdl-ayuda q-mt-sm")


@contextmanager
def seccion(texto: str, ayuda: str = ""):
    with ui.column().classes("sdl-seccion") as columna:
        ui.html(f'<h2 class="sdl-h2">{texto}</h2>', sanitize=False)
        if ayuda:
            ui.label(ayuda).classes("sdl-ayuda")
        yield columna


def boton(texto: str, al_pulsar=None, tipo: str = "principal", icono: str | None = None):
    """tipo: principal | secundario | texto | peligro"""
    b = ui.button(texto, on_click=al_pulsar, icon=icono)
    if tipo == "principal":
        b.props("unelevated color=primary")
    elif tipo == "secundario":
        b.props("outline color=primary")
    elif tipo == "peligro":
        b.props("outline color=negative")
    else:
        b.props("flat color=primary")
    return b


def boton_icono(icono: str, ayuda: str, al_pulsar=None, color: str = "secondary"):
    b = ui.button(icon=icono, on_click=al_pulsar).props(f"flat round dense color={color}")
    b.props(f'aria-label="{ayuda}"')
    with b:
        ui.tooltip(ayuda)
    return b


def nivel(tipo: str, texto: str) -> None:
    """Línea con ícono de estado + texto (el color nunca va solo: siempre hay ícono y texto)."""
    icono, color = ICONOS.get(tipo, ICONOS["info"])
    with ui.row().classes("items-start no-wrap gap-2 w-full"):
        ui.icon(icono, size="20px").style(f"color:{color}; margin-top:1px")
        ui.label(texto).classes("sdl-ayuda").style(f"color:{TINTA}; max-width:none")


def fila(columnas: str, cabecera: bool = False):
    """Fila de una tabla hecha con rejilla CSS. columnas = plantilla de grid."""
    return ui.element("div").classes("sdl-fila" + (" cab" if cabecera else "")).style(
        f"grid-template-columns: {columnas}")


def numero(etiqueta: str, valor=None, unidad: str = "", minimo=None, maximo=None, paso=None, ancho: str = "w-44"):
    n = ui.number(etiqueta, value=valor, min=minimo, max=maximo, step=paso, suffix=unidad or None)
    n.props("outlined dense").classes(ancho)
    return n


def texto(etiqueta: str, valor: str = "", ancho: str = "w-72"):
    return ui.input(etiqueta, value=valor).props("outlined dense").classes(ancho)


def selector(etiqueta: str, opciones, valor=None, ancho: str = "w-72", **extra):
    return ui.select(opciones, label=etiqueta, value=valor, **extra).props("outlined dense options-dense").classes(ancho)


def avisar(mensaje: str, tipo: str = "info") -> None:
    ui.notify(mensaje, type={"ok": "positive", "error": "negative", "aviso": "warning"}.get(tipo, "info"),
              position="top", multi_line=True, close_button="Cerrar" if tipo == "error" else False,
              timeout=0 if tipo == "error" else 5000)


async def confirmar(pregunta: str, si: str = "Sí", no: str = "Cancelar", peligro: bool = False) -> bool:
    with ui.dialog() as dialogo, ui.card():
        ui.label(pregunta).style("font-size:16px; line-height:1.45")
        with ui.row().classes("w-full justify-end gap-2 q-mt-sm"):
            boton(no, lambda: dialogo.submit(False), "texto")
            boton(si, lambda: dialogo.submit(True), "peligro" if peligro else "principal")
    return bool(await dialogo)
