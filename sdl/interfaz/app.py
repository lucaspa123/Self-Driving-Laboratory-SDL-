"""Armazón de la interfaz: barra superior con la parada de emergencia, menú de pasos y pantallas."""
from __future__ import annotations

from pathlib import Path

from nicegui import app, run, ui

from ..ejemplo import crear_ejemplo
from ..motor import INACTIVO, PARADA, TERMINADO, TEXTO_ESTADO, Motor
from .comunes import ROJO, aplicar_estilo, avisar, boton, selector
from .pantalla_ejecucion import pantalla_ejecucion
from .pantalla_experimento import pantalla_experimento
from .pantalla_historial import pantalla_historial
from .pantalla_informe import pantalla_informe
from .pantalla_modulos import pantalla_modulos

PASOS = [("equipo", "Equipo"), ("experimento", "Experimento"), ("historial", "Historial"),
         ("ejecucion", "Ejecución"), ("informe", "Informe")]

# Lo que se está mirando (se recuerda aunque se recargue la página)
vista = {"pantalla": "equipo", "exp_id": None}


def construir(motor: Motor) -> None:
    @ui.page("/")
    def pagina():
        aplicar_estilo()

        def experimento_actual():
            if motor.ocupado() and motor.exp is not None:
                return motor.exp                           # durante una campaña manda el que se está ejecutando
            experimentos = motor.experimentos()
            elegido = next((e for e in experimentos if e.id == vista["exp_id"]), None)
            if elegido is None and experimentos:
                elegido = experimentos[0]
                vista["exp_id"] = elegido.id
            return elegido

        def refrescar():
            barra.refresh()
            menu.refresh()
            contenido.refresh()

        def ir_a(pantalla: str):
            vista["pantalla"] = pantalla
            refrescar()

        def elegir(exp_id):
            vista["exp_id"] = exp_id
            refrescar()

        async def parada():
            await run.io_bound(motor.parada, "Botón de la pantalla")
            refrescar()

        async def rearmar():
            ok, mensaje = await run.io_bound(motor.rearmar)
            avisar(mensaje, "ok" if ok else "error")
            refrescar()

        # ---------------------------------------------------------------- barra superior
        with ui.header().classes("items-center justify-between q-px-lg").style("height: 60px"):
            ui.html('<div class="sdl-marca">SDL<span>Laboratorio autónomo</span></div>', sanitize=False)

            @ui.refreshable
            def barra():
                exp = experimento_actual()
                with ui.row().classes("items-center gap-3 no-wrap"):
                    experimentos = {e.id: e.nombre for e in motor.experimentos()}
                    if experimentos:
                        selector("Experimento", experimentos, exp.id if exp else None, "w-80",
                                 on_change=lambda e: elegir(e.value)).set_enabled(not motor.ocupado())
                    g = motor.gestor
                    if not g.conectado():
                        conexion = "Sin conexión"
                    else:
                        conexion = "Simulación" if g.enlace.simulado else "Equipo conectado"
                    ui.html(f'<span class="sdl-chip">{conexion}</span>', sanitize=False)
                    if motor.estado not in (INACTIVO, TERMINADO):
                        estado = "Esperando su respuesta" if motor.solicitud is not None and motor.estado != PARADA \
                            else TEXTO_ESTADO.get(motor.estado, motor.estado)
                        ui.html(f'<span class="sdl-chip" style="border-color:var(--celeste); color:var(--tinta)">'
                                f'{estado}</span>', sanitize=False)
            barra()
            ui.button("Parada de emergencia", on_click=parada, icon="front_hand") \
                .props("unelevated color=negative").style("font-size: 15px; padding: 8px 18px")

        # ---------------------------------------------------------------- menú de pasos
        with ui.left_drawer(fixed=True, bordered=False).props("width=228").classes("q-pa-none q-pt-md"):
            @ui.refreshable
            def menu():
                for i, (clave, nombre) in enumerate(PASOS, 1):
                    activa = " activa" if vista["pantalla"] == clave else ""
                    with ui.element("div").classes("sdl-nav" + activa).on("click", lambda c=clave: ir_a(c)) \
                            .props('role="button" tabindex="0"').on("keydown.enter", lambda c=clave: ir_a(c)):
                        ui.label(str(i)).classes("n")
                        ui.label(nombre)
                ui.label("Siga los pasos en orden la primera vez. Después puede ir directo a Ejecución.") \
                    .classes("sdl-chico q-pa-md q-mt-md")
            menu()

        # ---------------------------------------------------------------- contenido
        @ui.refreshable
        def aviso_parada():
            if motor.estado == PARADA:
                with ui.row().classes("sdl-parada"):
                    ui.icon("front_hand", size="26px")
                    with ui.column().classes("gap-0"):
                        ui.label("PARADA DE EMERGENCIA ACTIVA").style("font-weight:700; font-size:16px")
                        ui.label(f"Motivo: {motor.motivo_parada or 'activada'}. Válvulas cerradas y motores apagados. "
                                 "Revise el equipo antes de rearmar.").style("font-size:14px")
                    ui.space()
                    ui.button("Rearmar el sistema", on_click=rearmar).props("unelevated color=white text-color=negative")
        aviso_parada()

        @ui.refreshable
        def contenido():
            exp = experimento_actual()
            with ui.column().classes("sdl-pagina"):
                pantalla = vista["pantalla"]
                if pantalla == "equipo":
                    pantalla_modulos(motor, refrescar)
                elif pantalla == "experimento":
                    pantalla_experimento(motor, exp, refrescar, elegir)
                elif pantalla == "historial":
                    pantalla_historial(motor, exp, refrescar)
                elif pantalla == "ejecucion":
                    pantalla_ejecucion(motor, exp, refrescar, ir_a)
                else:
                    pantalla_informe(motor, exp, refrescar)
        contenido()

        # La barra y el aviso de parada se actualizan solos (por ejemplo, si se aprieta el botón físico)
        visto = {"clave": None}

        def vigilar():
            clave = (motor.estado, motor.solicitud is not None, motor.gestor.conectado(), motor.ocupado())
            if clave != visto["clave"]:
                primera = visto["clave"] is None
                parada_cambio = not primera and (clave[0] == PARADA) != (visto["clave"][0] == PARADA)
                visto["clave"] = clave
                barra.refresh()
                aviso_parada.refresh()
                if parada_cambio and vista["pantalla"] != "ejecucion":
                    contenido.refresh()
        ui.timer(0.7, vigilar)


def iniciar(base: Path, puerto: int = 8080, abrir_navegador: bool = True) -> None:
    """Crea el motor, abre la conexión simulada si corresponde y lanza la interfaz."""
    motor = Motor(Path(base))
    crear_ejemplo(motor)
    if motor.gestor.datos.get("conexion", {}).get("modo", "simulacion") != "esp32":
        motor.gestor.conectar()                           # la simulación no mueve nada: se conecta sola
    construir(motor)

    def al_cerrar():
        if motor.ocupado():
            motor.parada("Se cerró el programa")
        motor.gestor.desconectar()                        # deja todo en estado seguro
    app.on_shutdown(al_cerrar)
    ui.run(host="127.0.0.1", port=puerto, title="SDL · Laboratorio autónomo", language="es", reload=False,
           show=abrir_navegador, favicon="🧪", show_welcome_message=False)
