"""Comprueba que el optimizador mejora más que elegir experimentos al azar."""
import sys, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np
from sdl.modelos import Experimento, Variable, Objetivo
from sdl.optimizador import Optimizador
from sdl.simulacion import ReaccionSimulada

def experimento(n_obj=2):
    objetivos = [Objetivo("rendimiento", "Rendimiento", "%", "maximizar", meta=90),
                 Objetivo("impureza", "Impureza", "%", "minimizar", meta=30),
                 Objetivo("ph", "pH final", "", "alcanzar", valor=7.0, tolerancia=0.2)][:n_obj]
    return Experimento(id="prueba", nombre="Prueba", reaccion="prueba", max_experimentos=30,
        variables=[Variable("vol_a", "Volumen A", "mL", 1, 10, 0.1), Variable("vol_b", "Volumen B", "mL", 0.5, 8, 0.1),
                   Variable("vel", "Velocidad", "%", 20, 80, 1), Variable("t", "Tiempo", "s", 10, 300, 5)],
        objetivos=objetivos, restricciones=["vol_a + vol_b <= 15"])

def campaña(exp, modo, semilla, n=30):
    sim = ReaccionSimulada(exp); opt = Optimizador(exp, semilla); rng = np.random.default_rng(semilla)
    filas = []
    def ejecutar(v, origen):
        ok = sim.ocurre(v)
        filas.append({"n": len(filas)+1, "estado": "completado" if ok else "fallido", "variables": v, "origen": origen,
                      "resultados": {o.nombre: sim.valor(o.nombre, v) for o in exp.objetivos} if ok else {}})
    ejecutar(opt.ajustar({"vol_a": 5, "vol_b": 4, "vel": 50, "t": 100}), "previo")
    while len(filas) < n:
        if modo == "bo":
            p = opt.proponer(filas); v = p.valores
            assert opt.cumple_restricciones(v) and all(x.minimo <= v[x.nombre] <= x.maximo for x in exp.variables)
        else:
            while True:
                v = opt.ajustar({x.nombre: rng.uniform(x.minimo, x.maximo) for x in exp.variables})
                if opt.cumple_restricciones(v): break
        ejecutar(v, modo)
    return opt.analizar(filas), filas

def hipervolumen_comun(exp, grupos):
    """Hipervolumen de cada campaña con una escala común (para poder compararlas)."""
    opt = Optimizador(exp, 0)
    def costos(filas):
        return np.array([[opt.costo(j, f["resultados"][o.nombre]) for j, o in enumerate(exp.objetivos)]
                         for f in filas if f["estado"] == "completado"])
    todos = np.vstack([costos(f) for f in grupos])
    lo, rango = todos.min(axis=0), np.ptp(todos, axis=0) + 1e-12
    muestras = np.random.default_rng(0).uniform(0, 1.1, (20000, exp.objetivos.__len__()))
    salida = []
    for filas in grupos:
        N = (costos(filas) - lo) / rango
        salida.append(np.mean([np.any(np.all(N <= m, axis=1)) for m in muestras]))
    return salida

for n_obj in (1, 2, 3):
    exp = experimento(n_obj); t0 = time.time()
    bo = [campaña(exp, "bo", s) for s in range(4)]
    az = [campaña(exp, "azar", s) for s in range(4)]
    hv = hipervolumen_comun(exp, [f for _, f in bo] + [f for _, f in az])
    hv_bo, hv_az = hv[:4], hv[4:]
    a = bo[0][0]
    print(f"{n_obj} objetivo(s): hipervolumen BO {np.mean(hv_bo):.3f} vs azar {np.mean(hv_az):.3f} | "
          f"pareto={len(a['pareto'])} cumplen={len(a['cumplen'])} fallidos={a['n_fallidos']} | {time.time()-t0:.0f} s")
    assert np.mean(hv_bo) > np.mean(hv_az), "la optimización no supera al azar"
print("OK")
