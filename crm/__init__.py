"""
Aplicación Flask del CRM (fábrica create_app).

    crm/ajustes.py    configuración desde variables de entorno
    crm/modelos.py    tablas PostgreSQL (multiempresa)
    crm/servicios.py  reglas de negocio y validación (reutiliza capa1_motor)
    crm/auth.py       registro, login, sesiones y permisos
    crm/api.py        API JSON y descargas (reutiliza capa3_salidas)
    crm/ia.py         panel de IA con la API de Claude
"""
from __future__ import annotations

from datetime import timedelta

from flask import Blueprint, Flask, g, jsonify, render_template, request
from sqlalchemy import text
from werkzeug.exceptions import HTTPException
from werkzeug.middleware.proxy_fix import ProxyFix

from . import ajustes
from .modelos import crear_tablas, db

web = Blueprint("web", __name__)


@web.get("/")
def app_shell():
    from .auth import requiere_login

    @requiere_login
    def _vista():
        return render_template("app.html"), 200, {"Cache-Control": "no-store"}
    return _vista()


@web.get("/salud")
def salud():
    """Comprobación de estado para Render: responde si la base de datos contesta."""
    db.session.execute(text("SELECT 1"))
    return jsonify(estado="ok")


def create_app(config_extra: dict | None = None) -> Flask:
    app = Flask(__name__, template_folder="../plantillas", static_folder="../static", static_url_path="/static")
    app.config.update(
        SECRET_KEY=ajustes.clave_secreta(),
        SQLALCHEMY_DATABASE_URI=ajustes.url_base_datos(),
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        SESSION_COOKIE_NAME="crm_sesion",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=ajustes.PRODUCCION,     # solo por HTTPS en producción
        PERMANENT_SESSION_LIFETIME=timedelta(hours=8),
        MAX_CONTENT_LENGTH=5 * 1024 * 1024,            # 5 MB por subida
        JSON_SORT_KEYS=False,
    )
    if config_extra:
        app.config.update(config_extra)
    app.json.ensure_ascii = False
    # Render (y cualquier proxy con HTTPS) informa de la IP y el protocolo reales en cabeceras X-Forwarded-*
    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    from . import api, auth, ia
    app.register_blueprint(web)
    app.register_blueprint(auth.bp)
    app.register_blueprint(api.bp)
    app.register_blueprint(ia.bp)

    @app.before_request
    def antes():
        auth.cargar_usuario()
        # Toda petición de la API que cambia datos debe traer el token CSRF de la sesión
        if request.method in ("POST", "PUT", "PATCH", "DELETE") and request.path.startswith("/api/"):
            if request.headers.get("X-CRM") != "1" or not auth.csrf_valido(request.headers.get("X-CSRF-Token")):
                return jsonify(error="La sesión ha caducado o la petición no es válida. Recarga la página."), 403

    @app.after_request
    def cabeceras(resp):
        resp.headers.setdefault("Content-Security-Policy",
                                "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' "
                                "https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
                                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                                "base-uri 'self'; form-action 'self'")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "same-origin")
        resp.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        if ajustes.PRODUCCION:
            resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        if request.path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.errorhandler(HTTPException)
    def error_http(e):
        if request.path.startswith(("/api/", "/descargas/")):
            mensajes = {404: "No encontrado.", 405: "Método no permitido.", 413: "El fichero supera 5 MB."}
            return jsonify(error=mensajes.get(e.code, e.description)), e.code
        return e

    @app.errorhandler(Exception)
    def error_interno(e):
        db.session.rollback()
        app.logger.exception("Error no controlado")
        if request.path.startswith(("/api/", "/descargas/")):
            return jsonify(error="Error interno. Inténtalo de nuevo en unos segundos."), 500
        return "Error interno del servidor.", 500

    @app.teardown_request
    def limpiar(_exc):
        g.pop("usuario", None)

    with app.app_context():
        crear_tablas()
    return app
