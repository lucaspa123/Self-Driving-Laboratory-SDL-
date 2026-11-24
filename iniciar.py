"""Abre el programa del SDL. Uso:  python iniciar.py   (o doble clic en iniciar.bat)"""
import argparse
from pathlib import Path

from sdl.interfaz import iniciar

if __name__ in {"__main__", "__mp_main__"}:
    opciones = argparse.ArgumentParser(description="SDL — Laboratorio autónomo")
    opciones.add_argument("--puerto", type=int, default=8080, help="puerto de la interfaz (por defecto 8080)")
    opciones.add_argument("--sin-navegador", action="store_true", help="no abrir el navegador automáticamente")
    opciones.add_argument("--carpeta", default=str(Path(__file__).resolve().parent),
                          help="carpeta donde se guardan config/ y datos/")
    a = opciones.parse_args()
    print(f"SDL abierto en http://127.0.0.1:{a.puerto}  (para cerrarlo: Ctrl+C en esta ventana)")
    iniciar(Path(a.carpeta), a.puerto, not a.sin_navegador)
