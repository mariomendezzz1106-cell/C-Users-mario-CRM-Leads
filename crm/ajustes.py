"""
Configuración de la plataforma, leída SIEMPRE de variables de entorno.

En local se cargan desde el fichero .env (que no se sube a Git).
En Render se definen en el panel del servicio o en render.yaml.
Ninguna contraseña ni clave vive en el código.
"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parent.parent
load_dotenv(RAIZ / ".env", override=False)


def _bool(nombre: str, defecto: bool = False) -> bool:
    valor = os.environ.get(nombre)
    if valor is None:
        return defecto
    return valor.strip().lower() in ("1", "true", "si", "sí", "yes", "on")


def url_base_datos() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        raise RuntimeError("Falta la variable DATABASE_URL (conexión a PostgreSQL). Revisa el fichero .env.")
    # Render y otros proveedores dan postgres:// o postgresql://; SQLAlchemy necesita el driver psycopg
    for prefijo in ("postgres://", "postgresql://"):
        if url.startswith(prefijo):
            return "postgresql+psycopg://" + url[len(prefijo):]
    return url


def clave_secreta() -> str:
    clave = os.environ.get("SECRET_KEY", "").strip()
    if len(clave) < 32:
        raise RuntimeError("Falta SECRET_KEY o es demasiado corta (mínimo 32 caracteres). Revisa el fichero .env.")
    return clave


PRODUCCION = _bool("PRODUCCION", defecto=bool(os.environ.get("RENDER")))
PERMITIR_REGISTRO = _bool("ALLOW_SIGNUP", defecto=True)
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "").strip()
MODELO_IA = os.environ.get("MODELO_IA", "claude-opus-5-5").strip()
LIMITE_IA_DIARIO = int(os.environ.get("LIMITE_IA_DIARIO", "60"))  # llamadas a la IA por empresa y día
