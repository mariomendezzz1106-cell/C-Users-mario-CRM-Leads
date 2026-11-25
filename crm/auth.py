"""
Autenticación: registro de empresas, inicio y cierre de sesión, permisos.

- Contraseñas con Argon2id (argon2-cffi), nunca en claro.
- Sesión en cookie firmada, HttpOnly, SameSite=Lax y Secure en producción,
  con caducidad y "versión" para poder invalidarla desde el servidor.
- Límite de intentos fallidos por email e IP.
- Token CSRF en formularios y en las llamadas de la API.
"""
from __future__ import annotations

import hmac
import secrets
from datetime import timedelta
from functools import wraps

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from flask import Blueprint, abort, g, jsonify, redirect, render_template, request, session, url_for
from sqlalchemy import func, select

from . import ajustes
from .modelos import NIVEL, IntentoLogin, Organizacion, Usuario, ahora, db
from .servicios import EMAIL_RE, cargar_demo, registrar

bp = Blueprint("auth", __name__)
hasher = PasswordHasher()  # Argon2id con parámetros recomendados
MAX_FALLOS_EMAIL, MAX_FALLOS_IP, VENTANA = 5, 30, timedelta(minutes=15)
MIN_CLAVE = 10
# Hash fijo para gastar el mismo tiempo cuando el email no existe (no revela qué emails hay)
_HASH_FALSO = hasher.hash(secrets.token_hex(16))


def hash_clave(clave: str) -> str:
    return hasher.hash(clave)


def comprobar_clave(usuario: Usuario | None, clave: str) -> bool:
    try:
        hasher.verify(usuario.hash if usuario else _HASH_FALSO, clave)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False
    if usuario is None:
        return False
    if hasher.check_needs_rehash(usuario.hash):
        usuario.hash = hasher.hash(clave)
    return True


def problema_clave(clave: str, email: str = "") -> str | None:
    if len(clave) < MIN_CLAVE:
        return f"La contraseña debe tener al menos {MIN_CLAVE} caracteres."
    if len(clave) > 200:
        return "La contraseña es demasiado larga."
    if email and clave.lower() == email.lower():
        return "La contraseña no puede ser tu email."
    return None


# ── CSRF ──────────────────────────────────────────────────────────────────
def token_csrf() -> str:
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return session["csrf"]


def csrf_valido(token: str | None) -> bool:
    return bool(token) and "csrf" in session and hmac.compare_digest(token, session["csrf"])


# ── sesión ────────────────────────────────────────────────────────────────
def iniciar_sesion(u: Usuario):
    session.clear()  # evita la fijación de sesión
    session.permanent = True
    session.update(uid=u.id, org=u.org_id, ver=u.version_sesion, csrf=secrets.token_urlsafe(32))
    u.ultimo_acceso = ahora()


def cargar_usuario():
    """Se ejecuta en cada petición: comprueba que la sesión sigue siendo válida."""
    g.usuario = g.org = None
    uid = session.get("uid")
    if not uid:
        return
    u = db.session.get(Usuario, uid)
    if not u or not u.activo or u.version_sesion != session.get("ver") or u.org_id != session.get("org"):
        session.clear()
        return
    g.usuario, g.org = u, u.org


def es_api() -> bool:
    return request.path.startswith(("/api/", "/descargas/"))


def requiere_login(f):
    @wraps(f)
    def envoltura(*a, **k):
        if g.get("usuario") is None:
            if es_api():
                return jsonify(error="Tu sesión ha caducado. Vuelve a entrar."), 401
            return redirect(url_for("auth.login"))
        return f(*a, **k)
    return envoltura


def requiere_rol(minimo: str):
    def deco(f):
        @wraps(f)
        def envoltura(*a, **k):
            if g.get("usuario") is None:
                return jsonify(error="Tu sesión ha caducado. Vuelve a entrar."), 401
            if NIVEL[g.usuario.rol] < NIVEL[minimo]:
                return jsonify(error="Tu usuario no tiene permiso para hacer esto."), 403
            return f(*a, **k)
        return envoltura
    return deco


def ip_cliente() -> str:
    return (request.remote_addr or "desconocida")[:64]  # ProxyFix ya resuelve la IP real tras el proxy


def bloqueado(email: str, ip: str) -> bool:
    desde = ahora() - VENTANA
    por_email = db.session.scalar(select(func.count()).select_from(IntentoLogin)
                                  .where(IntentoLogin.email == email, IntentoLogin.fecha > desde))
    por_ip = db.session.scalar(select(func.count()).select_from(IntentoLogin)
                               .where(IntentoLogin.ip == ip, IntentoLogin.fecha > desde))
    return por_email >= MAX_FALLOS_EMAIL or por_ip >= MAX_FALLOS_IP


# ── páginas ───────────────────────────────────────────────────────────────
def pagina(plantilla: str, estado: int = 200, **ctx):
    return render_template(plantilla, csrf=token_csrf(), permitir_registro=ajustes.PERMITIR_REGISTRO, **ctx), estado


@bp.get("/login")
def login():
    if g.get("usuario"):
        return redirect(url_for("web.app_shell"))
    return pagina("login.html", error=None, email="", aviso=request.args.get("aviso"))


@bp.post("/login")
def login_post():
    if not csrf_valido(request.form.get("csrf")):
        return pagina("login.html", 400, error="La página ha caducado. Vuelve a intentarlo.", email="")
    email = request.form.get("email", "").strip().lower()[:254]
    clave = request.form.get("clave", "")
    ip = ip_cliente()
    if bloqueado(email, ip):
        return pagina("login.html", 429, email=email,
                      error="Demasiados intentos fallidos. Espera 15 minutos y vuelve a probar.")
    u = db.session.execute(select(Usuario).where(Usuario.email == email)).scalar_one_or_none()
    if not comprobar_clave(u, clave) or not u.activo:
        db.session.add(IntentoLogin(email=email, ip=ip))
        db.session.commit()
        return pagina("login.html", 401, email=email, error="El email o la contraseña no son correctos.")
    # Al entrar bien se limpian los fallos de ese email
    db.session.query(IntentoLogin).filter(IntentoLogin.email == email).delete()
    iniciar_sesion(u)
    db.session.commit()
    return redirect(url_for("web.app_shell"))


@bp.get("/registro")
def registro():
    if not ajustes.PERMITIR_REGISTRO:
        abort(404)
    return pagina("registro.html", error=None, valores={})


@bp.post("/registro")
def registro_post():
    if not ajustes.PERMITIR_REGISTRO:
        abort(404)
    f = request.form
    valores = {k: f.get(k, "").strip() for k in ("empresa", "nombre", "email")}
    valores["email"] = valores["email"].lower()
    if not csrf_valido(f.get("csrf")):
        return pagina("registro.html", 400, error="La página ha caducado. Vuelve a intentarlo.", valores=valores)
    clave, clave2 = f.get("clave", ""), f.get("clave2", "")
    error = None
    if not valores["empresa"] or len(valores["empresa"]) > 120:
        error = "Escribe el nombre de tu empresa (máximo 120 caracteres)."
    elif not valores["nombre"] or len(valores["nombre"]) > 120:
        error = "Escribe tu nombre."
    elif not EMAIL_RE.match(valores["email"]):
        error = "El email no tiene un formato válido."
    elif clave != clave2:
        error = "Las dos contraseñas no coinciden."
    else:
        error = problema_clave(clave, valores["email"])
    if not error and db.session.execute(select(Usuario.id).where(Usuario.email == valores["email"])).first():
        error = "Ya existe una cuenta con ese email. Inicia sesión."
    if error:
        return pagina("registro.html", 400, error=error, valores=valores)

    org = Organizacion(nombre=valores["empresa"], ajustes={}, resumen={}, siguiente_lead=1)
    db.session.add(org)
    db.session.flush()
    u = Usuario(org_id=org.id, nombre=valores["nombre"], email=valores["email"], hash=hash_clave(clave),
                rol="propietario", activo=True, version_sesion=1)
    db.session.add(u)
    db.session.flush()
    registrar(org.id, "usuario", u.id, u.nombre, "Registro", f"Empresa {org.nombre} creada")
    if f.get("demo") == "1":
        cargar_demo(org, u.nombre)  # datos ficticios, visibles solo para esta empresa
    iniciar_sesion(u)
    db.session.commit()
    return redirect(url_for("web.app_shell"))


@bp.post("/logout")
def logout():
    if g.get("usuario") and not csrf_valido(request.form.get("csrf")):
        abort(400)
    session.clear()
    return redirect(url_for("auth.login", aviso="Has cerrado la sesión."))


@bp.post("/api/cuenta/clave")
@requiere_login
def cambiar_clave():
    d = request.get_json(silent=True) or {}
    u = g.usuario
    if not comprobar_clave(u, d.get("actual", "")):
        return jsonify(error="La contraseña actual no es correcta."), 400
    error = problema_clave(d.get("nueva", ""), u.email)
    if error:
        return jsonify(error=error), 400
    u.hash = hash_clave(d["nueva"])
    u.version_sesion += 1          # cierra las demás sesiones abiertas
    iniciar_sesion(u)              # y mantiene esta
    registrar(u.org_id, "usuario", u.id, u.nombre, "Cambio de contraseña")
    db.session.commit()
    return jsonify(ok=True, csrf=session["csrf"])


@bp.post("/api/cuenta/cerrar-sesiones")
@requiere_login
def cerrar_sesiones():
    u = g.usuario
    u.version_sesion += 1
    iniciar_sesion(u)
    db.session.commit()
    return jsonify(ok=True, csrf=session["csrf"])
