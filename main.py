"""
Pipeline completo de lead scoring en 3 capas.

    python main.py                         # capa 1 + capa 3 (usa el análisis si existe)
    python main.py --api                   # capa 1 + capa 2 por API + capa 3
    python main.py --entrada mis_leads.xlsx --fecha-ref 2026-11-23

Flujo sin API:
    1) python capa1_motor.py
    2) En el Project: adjuntar salidas/capa1_leads_puntuados.json
       y guardar la respuesta en salidas/capa2_analisis.json
    3) python capa3_salidas.py
"""
import argparse
from datetime import date
from pathlib import Path

import capa1_motor
import capa3_salidas


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--entrada", default="datos/leads.csv")
    ap.add_argument("--fecha-ref", default=date.today().isoformat())
    ap.add_argument("--api", action="store_true", help="Ejecutar la capa 2 por API")
    args = ap.parse_args()

    res = capa1_motor.ejecutar(Path(args.entrada), Path("salidas"), date.fromisoformat(args.fecha_ref))
    print(f"CAPA 1 · {len(res)} leads puntuados")

    if args.api:
        import capa2_api
        capa2_api.main()
    elif not Path("salidas/capa2_analisis.json").exists():
        print("CAPA 2 · falta salidas/capa2_analisis.json. Hazla en el Project (ver capa2_ia/) "
              "o usa --api. Se continúa con el texto del motor.")

    capa3_salidas.main()


if __name__ == "__main__":
    main()
