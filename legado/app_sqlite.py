"""
Plataforma web del CRM de leads.

Reutiliza el proyecto tal cual:
  capa1_motor.py   valida, puntúa y clasifica cada lead que se crea o edita
  capa3_salidas.py genera el Excel, el informe y el CSV para HubSpot al descargarlos
  plantillas/panel.html  es el mismo panel, que ahora lee y guarda en el servidor
  db.py            guarda todo en crm.db (SQLite), que se conserva al cerrar

Uso (desde la carpeta del proyecto):
  python app.py            abre el CRM en http://127.0.0.1:5000 (solo este ordenador)
  python app.py --red      lo abre también a otros equipos de la misma red
"""
from __future__ import annotations

import argparse
import getpass
import os
import secrets
import socket
import sys
import tempfile
from datetime import timedelta
from functools import wraps
from pathlib import Path

os.chdir(Path(__file__).resolve().parent)  # rutas relativas al proyecto, se arranque desde donde se arranque

from flask import Flask, abort, jsonify, redirect, render_template, request, send_file, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash

import capa1_motor
import capa3_salidas
import config
import db
import reglas

app = Flask(__name__, template_folder="plantillas")


def clave_secreta() -> str:
    """Clave para firmar la sesión; se crea una vez y se guarda junto a la base de datos."""
    ruta = db.RUTA_DB.with_name(".clave_secreta")
    if not ruta.exists():
        ruta.write_text(secrets.token_hex(32), encoding="utf-8")
    return ruta.read_text(encoding="utf-8").strip()


app.config.update(SECRET_KEY=clave_secreta(), SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax",
                  PERMANENT_SESSION_LIFETIME=timedelta(hours=8), MAX_CONTENT_LENGTH=5 * 1024 * 1024)


# ── sesión y permisos ─────────────────────────────────────────────────────
def usuario_actual():
    return session.get("usuario")


def requiere_login(f):
    @wraps(f)
    def envoltura(*a, **k):
        if not usuario_actual():
            if request.path.startswith("/api/") or request.path.startswith("/descargas/"):
                return jsonify(error="Tu sesión ha caducado. Vuelve a entrar."), 401
            return redirect(url_for("login"))
        return f(*a, **k)
    return envoltura


def requiere_admin(f):
    @wraps(f)
    def envoltura(*a, **k):
        if (usuario_actual() or {}).get("rol") != "admin":
            return jsonify(error="Solo un administrador puede hacer esto."), 403
        return f(*a, **k)
    return envoltura


@app.before_request
def proteger_formularios():
    """Las peticiones que cambian datos deben venir del propio panel (cabecera propia).
    Un formulario de otra web no puede añadirla, así se evitan envíos cruzados."""
    if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
        if request.headers.get("X-CRM") != "1":
            abort(403)


# ── páginas ───────────────────────────────────────────────────────────────
@app.get("/login")
def login():
    if usuario_actual():
        return redirect(url_for("panel"))
    return render_template("login.html", empresa=config.EMPRESA, error=None)


@app.post("/login")
def login_post():
    email = request.form.get("email", "").strip().lower()
    clave = request.form.get("clave", "")
    with db.conectar() as con:
        u = con.execute("SELECT * FROM usuarios WHERE email=?", (email,)).fetchone()
    if not u or not check_password_hash(u["hash"], clave):
        return render_template("login.html", empresa=config.EMPRESA,
                               error="El email o la contraseña no son correctos."), 401
    session.clear()
    session.permanent = True
    session["usuario"] = {"id": u["id"], "nombre": u["nombre"], "email": u["email"], "rol": u["rol"]}
    return redirect(url_for("panel"))


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@requiere_login
def panel():
    # El mismo panel del proyecto; con null en lugar de datos incrustados, los pide a /api/datos
    html = Path("plantillas/panel.html").read_text(encoding="utf-8").replace("/*__DATOS__*/", "null")
    return html, 200, {"Content-Type": "text/html; charset=utf-8", "Cache-Control": "no-store"}


# ── API de datos ──────────────────────────────────────────────────────────
def paquete_datos(con) -> dict:
    leads = db.listar(con)
    est = capa3_salidas.estadisticas(leads)
    return {
        "meta": {"empresa": config.EMPRESA, "fecha_referencia": db.fecha_ref().isoformat(),
                 "total_leads": len(leads), "umbrales": {"HOT": reglas.UMBRAL_HOT, "WARM": reglas.UMBRAL_WARM}},
        "resumen": db.resumen_global(con),
        "estadisticas": est,
        "leads": capa3_salidas.orden_plan(leads),
        "usuario": usuario_actual(),
        "opciones": {
            "estados": db.ESTADOS,
            "sectores": sorted({"Tecnología", "Retail", "Logística", "Salud", "Industria", "Energía",
                                "Servicios profesionales", "Hostelería", "Agroalimentario", "Construcción",
                                "Educación", "Administración pública"}),
            "origenes": ["Referido", "Feria", "Webinar", "Web", "LinkedIn", "Email frío"],
            "plazos": ["Inmediato", "1-3 meses", "3-6 meses", "+6 meses", "Sin definir"],
        },
    }


@app.get("/api/datos")
@requiere_login
def api_datos():
    with db.conectar() as con:
        return jsonify(paquete_datos(con))


@app.get("/api/leads/<id_lead>/historial")
@requiere_login
def api_historial(id_lead):
    with db.conectar() as con:
        return jsonify(db.historial(con, id_lead))


@app.post("/api/leads")
@requiere_login
def api_crear():
    datos = request.get_json(silent=True) or {}
    if not str(datos.get("empresa", "")).strip():
        return jsonify(error="Escribe al menos el nombre de la empresa."), 400
    with db.conectar() as con:
        nuevo = db.crear_lead(con, datos, usuario_actual()["nombre"])
    return jsonify(id_lead=nuevo), 201


@app.put("/api/leads/<id_lead>")
@requiere_login
def api_editar(id_lead):
    datos = request.get_json(silent=True) or {}
    try:
        with db.conectar() as con:
            db.editar_lead(con, id_lead, datos, usuario_actual()["nombre"])
    except KeyError:
        return jsonify(error="Ese lead ya no existe."), 404
    return jsonify(ok=True)


@app.patch("/api/leads/<id_lead>/seguimiento")
@requiere_login
def api_seguimiento(id_lead):
    d = request.get_json(silent=True) or {}
    try:
        with db.conectar() as con:
            db.cambiar_estado(con, id_lead, d.get("estado", ""), d.get("notas", ""), usuario_actual()["nombre"])
    except KeyError:
        return jsonify(error="Ese lead ya no existe."), 404
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(ok=True)


@app.delete("/api/leads/<id_lead>")
@requiere_login
def api_borrar(id_lead):
    try:
        with db.conectar() as con:
            db.borrar_lead(con, id_lead, usuario_actual()["nombre"])
    except KeyError:
        return jsonify(error="Ese lead ya no existe."), 404
    return jsonify(ok=True)


@app.post("/api/importar")
@requiere_login
def api_importar():
    f = request.files.get("fichero")
    if not f or not f.filename:
        return jsonify(error="Elige un fichero CSV o Excel."), 400
    sufijo = Path(f.filename).suffix.lower()
    if sufijo not in (".csv", ".xlsx", ".xls"):
        return jsonify(error="El fichero debe ser .csv o .xlsx."), 400
    with tempfile.TemporaryDirectory() as tmp:
        ruta = Path(tmp) / f"importar{sufijo}"
        f.save(ruta)
        try:
            filas = capa1_motor.leer_leads(ruta)
        except Exception:
            return jsonify(error="No se ha podido leer el fichero. Comprueba que tiene las columnas del CSV de ejemplo."), 400
    if not filas or "empresa" not in filas[0]:
        return jsonify(error="El fichero no tiene la columna «empresa». Usa las mismas columnas que datos/leads.csv."), 400
    with db.conectar() as con:
        ids = [db.crear_lead(con, fila, usuario_actual()["nombre"]) for fila in filas]
    return jsonify(importados=len(ids))


# ── usuarios (solo administradores) ───────────────────────────────────────
@app.get("/api/usuarios")
@requiere_login
@requiere_admin
def api_usuarios():
    with db.conectar() as con:
        return jsonify([dict(u) for u in con.execute("SELECT id, nombre, email, rol, creado FROM usuarios ORDER BY id")])


@app.post("/api/usuarios")
@requiere_login
@requiere_admin
def api_crear_usuario():
    d = request.get_json(silent=True) or {}
    nombre, email, clave = d.get("nombre", "").strip(), d.get("email", "").strip().lower(), d.get("clave", "")
    rol = "admin" if d.get("rol") == "admin" else "comercial"
    if not nombre or "@" not in email:
        return jsonify(error="Escribe un nombre y un email válidos."), 400
    if len(clave) < 8:
        return jsonify(error="La contraseña debe tener al menos 8 caracteres."), 400
    try:
        with db.conectar() as con:
            crear_usuario(con, nombre, email, clave, rol)
    except db.sqlite3.IntegrityError:
        return jsonify(error="Ya existe un usuario con ese email."), 400
    return jsonify(ok=True), 201


@app.delete("/api/usuarios/<int:uid>")
@requiere_login
@requiere_admin
def api_borrar_usuario(uid):
    if uid == usuario_actual()["id"]:
        return jsonify(error="No puedes borrar tu propio usuario."), 400
    with db.conectar() as con:
        con.execute("DELETE FROM usuarios WHERE id=?", (uid,))
    return jsonify(ok=True)


def crear_usuario(con, nombre, email, clave, rol="comercial"):
    con.execute("INSERT INTO usuarios (nombre, email, hash, rol, creado) VALUES (?,?,?,?,?)",
                (nombre, email.lower(), generate_password_hash(clave), rol, db.ahora()))


# ── descargas (reutilizan capa3_salidas) ──────────────────────────────────
@app.get("/descargas/<tipo>")
@requiere_login
def descargar(tipo):
    with db.conectar() as con:
        leads, resumen = db.listar(con), db.resumen_global(con)
    meta = {"fecha_referencia": db.fecha_ref().isoformat()}
    est = capa3_salidas.estadisticas(leads)
    tmp = Path(tempfile.mkdtemp())
    if tipo == "excel":
        ruta = tmp / "Leads_Plan_Comercial.xlsx"
        capa3_salidas.generar_excel(meta, resumen, leads, est, ruta)
    elif tipo == "hubspot":
        ruta = tmp / "hubspot_import.csv"
        capa3_salidas.generar_hubspot(leads, ruta)
    elif tipo == "informe":
        ruta = tmp / "informe_comercial.md"
        capa3_salidas.generar_informe(meta, resumen, leads, est, ruta)
    else:
        abort(404)
    return send_file(ruta, as_attachment=True, download_name=ruta.name)


# ── arranque ──────────────────────────────────────────────────────────────
def preparar():
    db.crear_tablas()
    if db.esta_vacia():
        n = db.cargar_datos_iniciales()
        print(f"Base de datos creada en {db.RUTA_DB} con {n} leads del proyecto.")
    with db.conectar() as con:
        hay_usuarios = con.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0] > 0
        if not hay_usuarios:
            # Primer arranque: se crea el administrador. Admite variables de entorno para no preguntar.
            email = os.environ.get("CRM_ADMIN_EMAIL") or input("\nPrimer arranque. Email del administrador: ").strip()
            clave = os.environ.get("CRM_ADMIN_PASSWORD") or getpass.getpass("Contraseña (mínimo 8 caracteres, no se verá al escribir): ")
            if len(clave) < 8 or "@" not in email:
                sys.exit("Email o contraseña no válidos. Vuelve a ejecutar python app.py.")
            nombre = os.environ.get("CRM_ADMIN_NOMBRE") or "Administrador"
            crear_usuario(con, nombre, email, clave, "admin")
            print(f"Administrador creado: {email}")


def ip_local() -> str:
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except OSError:
        return "TU-IP"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Plataforma web del CRM de leads")
    ap.add_argument("--red", action="store_true", help="Permitir acceso desde otros equipos de la red local")
    ap.add_argument("--puerto", type=int, default=5000)
    args = ap.parse_args()

    preparar()
    host = "0.0.0.0" if args.red else "127.0.0.1"
    print(f"\nCRM en marcha: http://127.0.0.1:{args.puerto}")
    if args.red:
        print(f"Desde otros equipos de tu red: http://{ip_local()}:{args.puerto}")
    print("Para pararlo, pulsa Ctrl+C en esta ventana.\n")
    try:
        from waitress import serve  # servidor estable para la demo
        serve(app, host=host, port=args.puerto, threads=8)
    except ImportError:
        app.run(host=host, port=args.puerto)
