"""
Arranque LOCAL en Windows (servidor Waitress).

    .\.venv\Scripts\python.exe app.py               http://127.0.0.1:5000 (solo este equipo)
    .\.venv\Scripts\python.exe app.py --puerto 5050
    .\.venv\Scripts\python.exe app.py --red         también desde otros equipos de tu red

En producción (Render) se usa gunicorn con wsgi.py.
La versión anterior con SQLite está en legado/.
"""
import argparse
import os
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)

from crm import create_app  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="CRM · servidor local")
    ap.add_argument("--puerto", type=int, default=5000)
    ap.add_argument("--red", action="store_true", help="Escuchar en todas las interfaces de red")
    args = ap.parse_args()
    app = create_app()
    host = "0.0.0.0" if args.red else "127.0.0.1"
    print(f"\nCRM en marcha: http://127.0.0.1:{args.puerto}   (Ctrl+C para parar)\n")
    from waitress import serve
    serve(app, host=host, port=args.puerto, threads=8)
