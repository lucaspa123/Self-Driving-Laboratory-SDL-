"""Experimento de ejemplo, para aprender a usar el programa en modo simulación.

Se crea solo la primera vez que se abre el programa (si no hay ningún
experimento guardado). Los tres experimentos previos del historial son
INVENTADOS: sirven para probar, no son datos reales.
"""
from __future__ import annotations

from .modelos import Experimento, Objetivo, Paso, Variable
from .simulacion import ReaccionSimulada


def experimento_ejemplo() -> Experimento:
    return Experimento(
        id="ejemplo_magnetita",
        nombre="Ejemplo: síntesis de magnetita",
        reaccion="ejemplo_magnetita",
        descripcion=("Ejemplo para practicar en modo simulación. Coprecipitación de magnetita: se dosifica la "
                     "solución de hierro y el NaOH con agitación y se mide el rendimiento y el pH final."),
        max_experimentos=15,
        capacidad_vaso_ml=100.0,
        supervisado=True,
        variables=[
            Variable("vol_fe", "Volumen de solución de Fe", "mL", 5.0, 30.0, 0.5,
                     origen="modulo", modulo="bomba", accion="bombear", parametro="volumen"),
            Variable("vol_naoh", "Volumen de NaOH", "mL", 2.0, 20.0, 0.1,
                     origen="modulo", modulo="bureta_1", accion="dosificar", parametro="volumen"),
            Variable("velocidad", "Velocidad de agitación", "%", 20.0, 80.0, 1.0,
                     origen="modulo", modulo="agitador", accion="encender", parametro="velocidad"),
            Variable("tiempo", "Tiempo de reacción", "s", 20.0, 120.0, 5.0, origen="tiempo"),
            Variable("temperatura", "Temperatura de la placa", "°C", 25.0, 60.0, 5.0, origen="manual"),
        ],
        objetivos=[
            Objetivo("rendimiento", "Rendimiento", "%", "maximizar", meta=85.0),
            Objetivo("ph_final", "pH final", "", "alcanzar", valor=10.0, tolerancia=0.5),
        ],
        restricciones=["vol_fe + vol_naoh <= 45"],
        protocolo=[
            Paso("confirmar", mensaje="Coloque un vaso limpio y vacío en la posición de reacción."),
            Paso("ajuste_manual", variable="temperatura"),
            Paso("accion", modulo="bomba", accion="bombear", parametros={"volumen": "$vol_fe"}),
            Paso("accion", modulo="agitador", accion="encender", parametros={"velocidad": "$velocidad"}),
            Paso("accion", modulo="bureta_1", accion="dosificar", parametros={"volumen": "$vol_naoh"}),
            Paso("esperar", segundos="$tiempo"),
            Paso("accion", modulo="agitador", accion="apagar"),
            Paso("medir", objetivo="rendimiento"),
            Paso("medir", objetivo="ph_final"),
        ],
        reactivos={"bomba": "Solución de Fe(II)/Fe(III)", "bureta_1": "NaOH 1 M"},
    )


PREVIOS = [   # condiciones de los tres experimentos previos de ejemplo
    {"vol_fe": 15.0, "vol_naoh": 8.0, "velocidad": 50.0, "tiempo": 60.0, "temperatura": 40.0},
    {"vol_fe": 25.0, "vol_naoh": 5.0, "velocidad": 30.0, "tiempo": 30.0, "temperatura": 25.0},
    {"vol_fe": 10.0, "vol_naoh": 15.0, "velocidad": 70.0, "tiempo": 90.0, "temperatura": 55.0},
]


def crear_ejemplo(motor) -> None:
    """Si no hay ningún experimento guardado, crea el de ejemplo con su historial."""
    if motor.experimentos():
        return
    exp = experimento_ejemplo()
    motor.guardar_experimento(exp)
    historial = motor.historial_de(exp)
    if not historial.filas():
        reaccion = ReaccionSimulada(exp)          # la misma reacción inventada que usa la demostración
        for variables in PREVIOS:
            resultados = {o.nombre: reaccion.valor(o.nombre, variables) for o in exp.objetivos}
            historial.agregar(variables, resultados, origen="previo", notas="Dato de ejemplo (inventado).")
