"""Caudal como variable cuando solo está calibrado el 100 %: estimación opcional de las aperturas parciales."""
import shutil
import sys
import tempfile
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))
from sdl.modulos import GestorModulos          # noqa: E402

base = Path(tempfile.gettempdir()) / "sdl_prueba_caudal_estimado"
shutil.rmtree(base, ignore_errors=True)
g = GestorModulos(base / "config")
g.datos["conexion"]["aceleracion_simulacion"] = 500
g.ficha("bureta_1")["config"].update({"caudal_k": 0.125, "calibrada": True})
ok, _ = g.conectar()
b = g.modulos["bureta_1"]


def optimizables():
    return [o for o in g.catalogo()["optimizables"] if o["modulo"] == "bureta_1" and o["parametro"] == "caudal"]


# 1. Sin la opción, con solo el 100 % calibrado, el caudal no se puede elegir como variable (comportamiento anterior)
assert ok and not optimizables() and b.apertura_estimada() is None

# 2. Con la opción: aparece como variable en «dosificar» (y en «dosificar a un caudal» si está), con rango válido
g.ficha("bureta_1")["config"]["caudal_estimado"] = True
g.conectar()
b = g.modulos["bureta_1"]
opts = optimizables()
assert opts and b.apertura_estimada() == 25.0, opts
o = opts[0]
pleno = b.caudal_nominal(b.tabla()[100.0])
assert abs(o["max"] - pleno) < 0.03 * pleno and o["min"] < pleno * 0.3, (o, pleno)
assert any("estimación" in a for a in b.avisos())
assert "estimado" in b.descripcion_aperturas()
print("caudal variable:", o["etiqueta"], f"{o['min']:.3f} a {o['max']:.3f} mL/s;", b.descripcion_aperturas())

# 3. Dosificar a un caudal intermedio usa una apertura parcial y tarda más que a caudal pleno
b.ejecutar("fijar_volumen", {"volumen": 25.0})
rapido = b.ejecutar("dosificar", {"volumen": 2.0})
b.ejecutar("fijar_volumen", {"volumen": 25.0})
lento = b.ejecutar("dosificar", {"volumen": 2.0, "caudal": pleno / 2})
assert rapido["apertura_pct"] == 100.0 and 25.0 < lento["apertura_pct"] < 100.0, (rapido, lento)
assert lento["segundos"] > 1.5 * rapido["segundos"], (rapido, lento)
for caudal in (pleno * 0.05, pleno * 1.3):                       # fuera de lo estimable
    try:
        b.ejecutar("dosificar", {"volumen": 2.0, "caudal": caudal})
        raise AssertionError("debía rechazar un caudal fuera de rango")
    except Exception as error:
        assert "caudal" in str(error).lower() or "Caudal" in str(error), error
print(f"dosis a mitad de caudal: apertura {lento['apertura_pct']} %, {lento['segundos']} s (a pleno: {rapido['segundos']} s)")

# 4. Al calibrar una apertura parcial de verdad, la estimación se retira sola
b.calibrar_manual({"apertura": 50, "inicial": 25, "salio": 5, "segundos": 20})
assert b.apertura_estimada() is None and 50.0 in b.tabla() and not any("estimación" in a for a in b.avisos())
assert "estimado" not in b.descripcion_aperturas()
print("con una apertura medida, la estimación desaparece:", b.descripcion_aperturas())
print("OK")
