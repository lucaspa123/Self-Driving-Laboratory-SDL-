"""Ejecuta todas las pruebas automáticas. Uso:  python pruebas/ejecutar_todas.py"""
import subprocess
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
PRUEBAS = ["prueba_bureta_ph.py", "prueba_motor.py", "prueba_firmware.py", "prueba_optimizador.py"]

fallas = 0
for nombre in PRUEBAS:
    inicio = time.time()
    r = subprocess.run([sys.executable, str(AQUI / nombre)], capture_output=True, text=True)
    bien = r.returncode == 0 and r.stdout.strip().endswith("OK")
    print(f"{'BIEN ' if bien else 'FALLA'} {nombre}  ({time.time() - inicio:.0f} s)")
    if not bien:
        fallas += 1
        print(r.stdout[-1500:], r.stderr[-1500:])
print("Todas las pruebas pasaron." if not fallas else f"{fallas} prueba(s) fallaron.")
sys.exit(1 if fallas else 0)
