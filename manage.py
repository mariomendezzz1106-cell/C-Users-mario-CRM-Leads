"""
Tareas de administración.

    python manage.py init-db                       crea las tablas que falten
    python manage.py crear-empresa                 crea una empresa y su propietario (pide los datos)
    python manage.py importar-sqlite RUTA EMAIL    pasa los leads de la versión SQLite (crm.db)
                                                   a la empresa del usuario EMAIL
"""
from __future__ import annotations

import getpass
import json
import sqlite3
import sys
from pathlib import Path

from sqlalchemy import select

from crm import create_app
from crm.auth import hash_clave, problema_clave
from crm.modelos import Lead, Organizacion, Usuario, crear_tablas, db
from crm.servicios import EMAIL_RE, crear_lead, registrar


def crear_empresa():
    empresa = input("Nombre de la empresa: ").strip()
    nombre = input("Tu nombre: ").strip()
    email = input("Email: ").strip().lower()
    clave = getpass.getpass("Contraseña (no se ve al escribir): ")
    if not empresa or not nombre or not EMAIL_RE.match(email):
        sys.exit("Datos no válidos.")
    if problema_clave(clave, email):
        sys.exit(problema_clave(clave, email))
    if db.session.execute(select(Usuario.id).where(Usuario.email == email)).first():
        sys.exit("Ya existe un usuario con ese email.")
    org = Organizacion(nombre=empresa, ajustes={}, resumen={}, siguiente_lead=1)
    db.session.add(org)
    db.session.flush()
    db.session.add(Usuario(org_id=org.id, nombre=nombre, email=email, hash=hash_clave(clave), rol="propietario"))
    db.session.commit()
    print(f"Empresa «{empresa}» creada. Ya puedes entrar con {email}.")


def importar_sqlite(ruta: str, email: str):
    u = db.session.execute(select(Usuario).where(Usuario.email == email.lower())).scalar_one_or_none()
    if not u:
        sys.exit("No hay ningún usuario con ese email. Regístrate antes en la web.")
    org = u.org
    con = sqlite3.connect(f"file:{Path(ruta).resolve()}?mode=ro", uri=True)  # solo lectura
    con.row_factory = sqlite3.Row
    filas = con.execute("SELECT * FROM leads ORDER BY id_lead").fetchall()
    resumen = con.execute("SELECT valor FROM ajustes WHERE clave='resumen'").fetchone()
    existentes = set(db.session.execute(select(Lead.codigo).where(Lead.org_id == org.id)).scalars())
    n = 0
    for f in filas:
        codigo = f["id_lead"] if f["id_lead"] not in existentes else None
        lead = crear_lead(org, json.loads(f["datos"]), "importación SQLite", analisis=json.loads(f["analisis"]), codigo=codigo)
        lead.estado, lead.notas = f["estado"], f["notas"]
        n += 1
    if codigo_max := max([int(c[1:]) for c in db.session.execute(select(Lead.codigo).where(Lead.org_id == org.id)).scalars()
                          if c[1:].isdigit()] or [0]):
        org.siguiente_lead = max(org.siguiente_lead, codigo_max + 1)
    if resumen and not org.resumen:
        org.resumen = json.loads(resumen["valor"])
    registrar(org.id, "organizacion", org.id, u.nombre, "Importación SQLite", f"{n} leads")
    db.session.commit()
    print(f"{n} leads importados en «{org.nombre}».")


if __name__ == "__main__":
    orden = sys.argv[1] if len(sys.argv) > 1 else ""
    app = create_app()
    with app.app_context():
        if orden == "init-db":
            crear_tablas()
            print("Tablas listas.")
        elif orden == "crear-empresa":
            crear_empresa()
        elif orden == "importar-sqlite" and len(sys.argv) == 4:
            importar_sqlite(sys.argv[2], sys.argv[3])
        else:
            print(__doc__)
