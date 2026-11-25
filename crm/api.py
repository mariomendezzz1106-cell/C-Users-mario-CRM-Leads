"""
API JSON del CRM. Todas las rutas:
  · exigen sesión (requiere_login) y, para escribir, rol comercial o superior;
  · filtran por la empresa del usuario (g.org): nunca se ve ni se toca nada de otra empresa;
  · validan los datos antes de guardarlos.
"""
from __future__ import annotations

import csv
import io
import tempfile
from datetime import date, timedelta
from pathlib import Path

from flask import Blueprint, abort, g, jsonify, request, send_file
from sqlalchemy import case, func, or_, select

import capa1_motor
import capa3_salidas
import reglas
from . import ajustes
from .auth import hash_clave, problema_clave, requiere_login, requiere_rol
from .modelos import (ESTADOS_LEAD, ESTADOS_TAREA, ETAPAS, NIVEL, PRIORIDADES_TAREA, PROBABILIDAD_ETAPA, ROLES,
                      Cliente, Contacto, Historial, Lead, Oportunidad, Tarea, Usuario, ahora, db)
from .servicios import (EMAIL_RE, ESQUEMA_CLIENTE, ESQUEMA_CONTACTO, ESQUEMA_OPORTUNIDAD, ESQUEMA_TAREA, ORIGENES,
                        PLAZOS, SECTORES, TIPOS_CLIENTE, ErrorValidacion, cambiar_estado_lead, cargar_demo,
                        comprobar_referencias, convertir_lead, crear_lead, editar_lead, fecha_ref, lead_dict, marca,
                        registrar, rellenar, validar)

bp = Blueprint("api", __name__)
ABIERTAS = [e for e in ETAPAS if e not in ("Ganado", "Perdido")]


@bp.app_errorhandler(ErrorValidacion)
def error_validacion(e: ErrorValidacion):
    db.session.rollback()
    return jsonify(error=str(e), errores=e.errores), 400


# ── utilidades ────────────────────────────────────────────────────────────
def cuerpo() -> dict:
    d = request.get_json(silent=True)
    return d if isinstance(d, dict) else {}


def obtener(modelo, oid: int):
    """Devuelve el registro solo si es de la empresa del usuario; si no, 404 (no revela que existe)."""
    obj = db.session.get(modelo, oid)
    if obj is None or obj.org_id != g.org.id:
        abort(404)
    return obj


def lead_por_codigo(codigo: str) -> Lead:
    lead = db.session.execute(select(Lead).where(Lead.org_id == g.org.id, Lead.codigo == codigo)).scalar_one_or_none()
    if lead is None:
        abort(404)
    return lead


def nombres_usuarios() -> dict[int, str]:
    return dict(db.session.execute(select(Usuario.id, Usuario.nombre).where(Usuario.org_id == g.org.id)).all())


def nombres_clientes() -> dict[int, str]:
    return dict(db.session.execute(select(Cliente.id, Cliente.nombre).where(Cliente.org_id == g.org.id)).all())


def iso(v):
    return v.isoformat() if v else None


def patron(q: str) -> str:
    return "%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"


def quien() -> str:
    return g.usuario.nombre


# ── serialización ─────────────────────────────────────────────────────────
def cliente_dict(c: Cliente, usuarios=None, extra=None) -> dict:
    usuarios = usuarios if usuarios is not None else nombres_usuarios()
    return {"id": c.id, "nombre": c.nombre, "sector": c.sector, "empleados": c.empleados, "pais": c.pais,
            "ciudad": c.ciudad, "web": c.web, "telefono": c.telefono, "tipo": c.tipo, "notas": c.notas,
            "responsable_id": c.responsable_id, "responsable": usuarios.get(c.responsable_id, ""),
            "creado": iso(c.creado), "actualizado": iso(c.actualizado), **(extra or {})}


def contacto_dict(c: Contacto, clientes=None) -> dict:
    clientes = clientes if clientes is not None else nombres_clientes()
    return {"id": c.id, "nombre": c.nombre, "apellidos": c.apellidos, "email": c.email, "telefono": c.telefono,
            "cargo": c.cargo, "notas": c.notas, "cliente_id": c.cliente_id, "cliente": clientes.get(c.cliente_id, ""),
            "creado": iso(c.creado)}


def oportunidad_dict(o: Oportunidad, usuarios=None, clientes=None) -> dict:
    usuarios = usuarios if usuarios is not None else nombres_usuarios()
    clientes = clientes if clientes is not None else nombres_clientes()
    importe = float(o.importe or 0)
    return {"id": o.id, "titulo": o.titulo, "cliente_id": o.cliente_id, "cliente": clientes.get(o.cliente_id, ""),
            "contacto_id": o.contacto_id, "lead_id": o.lead_id, "importe": importe, "etapa": o.etapa,
            "probabilidad": o.probabilidad, "ponderado": round(importe * o.probabilidad / 100, 2),
            "fecha_cierre": iso(o.fecha_cierre), "responsable_id": o.responsable_id,
            "responsable": usuarios.get(o.responsable_id, ""), "notas": o.notas,
            "creado": iso(o.creado), "actualizado": iso(o.actualizado)}


def tarea_dict(t: Tarea, usuarios=None, clientes=None) -> dict:
    usuarios = usuarios if usuarios is not None else nombres_usuarios()
    clientes = clientes if clientes is not None else nombres_clientes()
    hoy = date.today()
    return {"id": t.id, "titulo": t.titulo, "descripcion": t.descripcion, "vence": iso(t.vence),
            "prioridad": t.prioridad, "estado": t.estado, "asignado_id": t.asignado_id,
            "asignado": usuarios.get(t.asignado_id, ""), "cliente_id": t.cliente_id,
            "cliente": clientes.get(t.cliente_id, ""), "oportunidad_id": t.oportunidad_id, "lead_id": t.lead_id,
            "vencida": bool(t.vence and t.vence < hoy and t.estado != "Hecha"),
            "creado": iso(t.creado), "completada": iso(t.completada)}


def leads_org() -> list[dict]:
    filas = db.session.execute(select(Lead).where(Lead.org_id == g.org.id)).scalars().all()
    return [lead_dict(g.org, l) for l in filas]


# ── datos generales (lo que el panel original cargaba de /api/datos) ──────
@bp.get("/api/datos")
@requiere_login
def api_datos():
    from flask import session
    leads = leads_org()
    usuarios = db.session.execute(select(Usuario.id, Usuario.nombre).where(Usuario.org_id == g.org.id,
                                                                            Usuario.activo.is_(True))).all()
    a = g.org.ajustes or {}
    return jsonify({
        "meta": {"empresa": g.org.nombre, "fecha_referencia": fecha_ref(g.org).isoformat(), "total_leads": len(leads),
                 "umbrales": {"HOT": reglas.UMBRAL_HOT, "WARM": reglas.UMBRAL_WARM}, "demo": bool(a.get("demo"))},
        "usuario": {"id": g.usuario.id, "nombre": g.usuario.nombre, "email": g.usuario.email, "rol": g.usuario.rol},
        "csrf": session.get("csrf"),
        "resumen": rellenar(g.org, g.org.resumen or {}),
        "estadisticas": capa3_salidas.estadisticas(leads),
        "leads": capa3_salidas.orden_plan(leads),
        "ia": {"configurada": bool(ajustes.ANTHROPIC_API_KEY), "modelo": ajustes.MODELO_IA},
        "opciones": {"estados": ESTADOS_LEAD, "sectores": SECTORES, "origenes": ORIGENES, "plazos": PLAZOS,
                     "etapas": ETAPAS, "probabilidad_etapa": PROBABILIDAD_ETAPA, "estados_tarea": ESTADOS_TAREA,
                     "prioridades": PRIORIDADES_TAREA, "tipos_cliente": TIPOS_CLIENTE, "roles": ROLES,
                     "usuarios": [{"id": i, "nombre": n} for i, n in usuarios]},
    })


# ── dashboard ─────────────────────────────────────────────────────────────
@bp.get("/api/dashboard")
@requiere_login
def api_dashboard():
    oid, hoy = g.org.id, date.today()
    clases = dict(db.session.execute(select(Lead.clasificacion, func.count()).where(Lead.org_id == oid)
                                     .group_by(Lead.clasificacion)).all())
    hot_pend = db.session.scalar(select(func.count()).select_from(Lead).where(
        Lead.org_id == oid, Lead.clasificacion == "HOT", Lead.estado == "Pendiente"))
    por_etapa = {e: {"etapa": e, "n": 0, "valor": 0.0, "ponderado": 0.0} for e in ETAPAS}
    for etapa, n, valor, pond in db.session.execute(
            select(Oportunidad.etapa, func.count(), func.coalesce(func.sum(Oportunidad.importe), 0),
                   func.coalesce(func.sum(Oportunidad.importe * Oportunidad.probabilidad / 100.0), 0))
            .where(Oportunidad.org_id == oid).group_by(Oportunidad.etapa)).all():
        if etapa in por_etapa:
            por_etapa[etapa].update(n=n, valor=float(valor), ponderado=round(float(pond), 2))
    abiertas = [por_etapa[e] for e in ABIERTAS]
    ganadas, perdidas = por_etapa["Ganado"], por_etapa["Perdido"]
    cerradas = ganadas["n"] + perdidas["n"]
    t_base = select(func.count()).select_from(Tarea).where(Tarea.org_id == oid, Tarea.estado != "Hecha")
    usuarios, clientes = nombres_usuarios(), nombres_clientes()
    proximas = db.session.execute(select(Tarea).where(Tarea.org_id == oid, Tarea.estado != "Hecha")
                                  .order_by(Tarea.vence.asc().nulls_last(), Tarea.id).limit(6)).scalars().all()
    cierres = db.session.execute(select(Oportunidad).where(Oportunidad.org_id == oid, Oportunidad.etapa.in_(ABIERTAS))
                                 .order_by(Oportunidad.fecha_cierre.asc().nulls_last(), Oportunidad.importe.desc())
                                 .limit(5)).scalars().all()
    actividad = db.session.execute(select(Historial).where(Historial.org_id == oid)
                                   .order_by(Historial.id.desc()).limit(10)).scalars().all()
    return jsonify({
        "leads": {"total": sum(clases.values()), "por_clase": {c: clases.get(c, 0) for c in capa3_salidas.CLASES},
                  "hot_pendientes": hot_pend},
        "oportunidades": {"abiertas": sum(e["n"] for e in abiertas), "valor_abierto": sum(e["valor"] for e in abiertas),
                          "ponderado": round(sum(e["ponderado"] for e in abiertas), 2),
                          "ganadas": ganadas["n"], "valor_ganado": ganadas["valor"], "perdidas": perdidas["n"],
                          "tasa_cierre": round(100 * ganadas["n"] / cerradas, 1) if cerradas else None,
                          "por_etapa": list(por_etapa.values())},
        "tareas": {"pendientes": db.session.scalar(t_base),
                   "vencidas": db.session.scalar(t_base.where(Tarea.vence < hoy)),
                   "hoy": db.session.scalar(t_base.where(Tarea.vence == hoy)),
                   "proximas": [tarea_dict(t, usuarios, clientes) for t in proximas]},
        "proximos_cierres": [oportunidad_dict(o, usuarios, clientes) for o in cierres],
        "actividad": [{"fecha": iso(h.fecha), "usuario": h.usuario, "entidad": h.entidad, "accion": h.accion,
                       "detalle": h.detalle} for h in actividad],
    })


# ── leads ─────────────────────────────────────────────────────────────────
@bp.get("/api/leads")
@requiere_login
def api_leads():
    q, clase = request.args.get("q", "").strip().lower(), request.args.get("clase", "")
    leads = leads_org()
    if clase:
        leads = [l for l in leads if l["clasificacion"] == clase]
    if q:
        leads = [l for l in leads if q in " ".join([l["empresa"], l["nombre_completo"], l["sector"], l["id_lead"]]).lower()]
    return jsonify(capa3_salidas.orden_plan(leads))


@bp.get("/api/leads/<codigo>/historial")
@requiere_login
def api_historial(codigo):
    lead = lead_por_codigo(codigo)
    filas = db.session.execute(select(Historial).where(Historial.org_id == g.org.id, Historial.entidad == "lead",
                                                       Historial.entidad_id == lead.id)
                               .order_by(Historial.id.desc()).limit(20)).scalars().all()
    return jsonify([{"usuario": h.usuario, "accion": h.accion, "detalle": h.detalle,
                     "fecha": h.fecha.isoformat(timespec="seconds")} for h in filas])


@bp.post("/api/leads")
@requiere_rol("comercial")
def api_crear_lead():
    lead = crear_lead(g.org, cuerpo(), quien())
    db.session.commit()
    return jsonify(id_lead=lead.codigo, clasificacion=lead.clasificacion, puntuacion=lead.puntuacion), 201


@bp.put("/api/leads/<codigo>")
@requiere_rol("comercial")
def api_editar_lead(codigo):
    lead = editar_lead(g.org, lead_por_codigo(codigo), cuerpo(), quien())
    db.session.commit()
    return jsonify(ok=True, clasificacion=lead.clasificacion, puntuacion=lead.puntuacion)


@bp.patch("/api/leads/<codigo>/seguimiento")
@requiere_rol("comercial")
def api_seguimiento(codigo):
    d = cuerpo()
    cambiar_estado_lead(g.org, lead_por_codigo(codigo), d.get("estado", ""), d.get("notas", ""), quien())
    db.session.commit()
    return jsonify(ok=True)


@bp.delete("/api/leads/<codigo>")
@requiere_rol("comercial")
def api_borrar_lead(codigo):
    lead = lead_por_codigo(codigo)
    registrar(g.org.id, "lead", lead.id, quien(), "Eliminado", f"{lead.codigo} · {lead.datos.get('empresa', '')}")
    db.session.execute(Oportunidad.__table__.update().where(Oportunidad.lead_id == lead.id).values(lead_id=None))
    db.session.execute(Tarea.__table__.update().where(Tarea.lead_id == lead.id).values(lead_id=None))
    db.session.delete(lead)
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/leads/<codigo>/convertir")
@requiere_rol("comercial")
def api_convertir(codigo):
    op = convertir_lead(g.org, lead_por_codigo(codigo), g.usuario)
    db.session.commit()
    return jsonify(oportunidad=oportunidad_dict(op)), 201


@bp.post("/api/importar")
@requiere_rol("comercial")
def api_importar():
    f = request.files.get("fichero")
    if not f or not f.filename:
        return jsonify(error="Elige un fichero CSV o Excel."), 400
    sufijo = Path(f.filename).suffix.lower()
    if sufijo not in (".csv", ".xlsx"):
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
    if len(filas) > 5000:
        return jsonify(error="Máximo 5.000 filas por importación."), 400
    errores, n = [], 0
    for i, fila in enumerate(filas, start=2):
        try:
            with db.session.begin_nested():
                crear_lead(g.org, fila, quien())
                n += 1
        except ErrorValidacion as e:
            errores.append(f"Fila {i}: {e}")
    db.session.commit()
    return jsonify(importados=n, errores=errores[:50])


# ── clientes ──────────────────────────────────────────────────────────────
@bp.get("/api/clientes")
@requiere_login
def api_clientes():
    consulta = select(Cliente).where(Cliente.org_id == g.org.id)
    q = request.args.get("q", "").strip()
    if q:
        p = patron(q)
        consulta = consulta.where(or_(Cliente.nombre.ilike(p), Cliente.ciudad.ilike(p), Cliente.sector.ilike(p)))
    for campo in ("sector", "tipo"):
        if request.args.get(campo):
            consulta = consulta.where(getattr(Cliente, campo) == request.args[campo])
    clientes = db.session.execute(consulta.order_by(func.lower(Cliente.nombre)).limit(1000)).scalars().all()
    ids = [c.id for c in clientes] or [0]
    n_cont = dict(db.session.execute(select(Contacto.cliente_id, func.count()).where(Contacto.cliente_id.in_(ids))
                                     .group_by(Contacto.cliente_id)).all())
    ops = {cid: (n, float(v)) for cid, n, v in db.session.execute(
        select(Oportunidad.cliente_id, func.count(), func.coalesce(func.sum(Oportunidad.importe), 0))
        .where(Oportunidad.cliente_id.in_(ids), Oportunidad.etapa.in_(ABIERTAS)).group_by(Oportunidad.cliente_id)).all()}
    usuarios = nombres_usuarios()
    return jsonify([cliente_dict(c, usuarios, {"contactos": n_cont.get(c.id, 0),
                                               "oportunidades_abiertas": ops.get(c.id, (0, 0))[0],
                                               "valor_abierto": ops.get(c.id, (0, 0))[1]}) for c in clientes])


@bp.get("/api/clientes/<int:cid>")
@requiere_login
def api_cliente(cid):
    c = obtener(Cliente, cid)
    usuarios, clientes = nombres_usuarios(), {c.id: c.nombre}
    contactos = db.session.execute(select(Contacto).where(Contacto.cliente_id == c.id).order_by(Contacto.nombre)).scalars()
    ops = db.session.execute(select(Oportunidad).where(Oportunidad.cliente_id == c.id).order_by(Oportunidad.id.desc())).scalars()
    tareas = db.session.execute(select(Tarea).where(Tarea.cliente_id == c.id).order_by(Tarea.vence.asc().nulls_last())).scalars()
    leads = db.session.execute(select(Lead.codigo, Lead.clasificacion, Lead.puntuacion).where(Lead.cliente_id == c.id)).all()
    hist = db.session.execute(select(Historial).where(Historial.org_id == g.org.id, Historial.entidad == "cliente",
                                                      Historial.entidad_id == c.id).order_by(Historial.id.desc()).limit(15)).scalars()
    return jsonify({**cliente_dict(c, usuarios),
                    "contactos_lista": [contacto_dict(x, clientes) for x in contactos],
                    "oportunidades": [oportunidad_dict(o, usuarios, clientes) for o in ops],
                    "tareas": [tarea_dict(t, usuarios, clientes) for t in tareas],
                    "leads": [{"id_lead": a, "clasificacion": b, "puntuacion": p} for a, b, p in leads],
                    "historial": [{"fecha": iso(h.fecha), "usuario": h.usuario, "accion": h.accion, "detalle": h.detalle} for h in hist]})


@bp.post("/api/clientes")
@requiere_rol("comercial")
def api_crear_cliente():
    v = validar(cuerpo(), ESQUEMA_CLIENTE)
    comprobar_referencias(g.org.id, v)
    v["tipo"] = v.get("tipo") or "Cliente potencial"
    c = Cliente(org_id=g.org.id, **v)
    db.session.add(c)
    db.session.flush()
    registrar(g.org.id, "cliente", c.id, quien(), "Alta", c.nombre)
    db.session.commit()
    return jsonify(cliente_dict(c)), 201


@bp.put("/api/clientes/<int:cid>")
@requiere_rol("comercial")
def api_editar_cliente(cid):
    c = obtener(Cliente, cid)
    v = validar(cuerpo(), ESQUEMA_CLIENTE)
    comprobar_referencias(g.org.id, v)
    v["tipo"] = v.get("tipo") or c.tipo
    for k, val in v.items():
        setattr(c, k, val)
    registrar(g.org.id, "cliente", c.id, quien(), "Edición", c.nombre)
    db.session.commit()
    return jsonify(cliente_dict(c))


@bp.delete("/api/clientes/<int:cid>")
@requiere_rol("comercial")
def api_borrar_cliente(cid):
    c = obtener(Cliente, cid)
    registrar(g.org.id, "cliente", c.id, quien(), "Eliminado", c.nombre)
    db.session.delete(c)   # contactos, oportunidades y tareas quedan sin cliente (no se borran)
    db.session.commit()
    return jsonify(ok=True)


# ── contactos ─────────────────────────────────────────────────────────────
@bp.get("/api/contactos")
@requiere_login
def api_contactos():
    consulta = select(Contacto).where(Contacto.org_id == g.org.id)
    q = request.args.get("q", "").strip()
    if q:
        p = patron(q)
        consulta = consulta.where(or_(Contacto.nombre.ilike(p), Contacto.apellidos.ilike(p), Contacto.email.ilike(p),
                                      Contacto.cargo.ilike(p)))
    if request.args.get("cliente_id", "").isdigit():
        consulta = consulta.where(Contacto.cliente_id == int(request.args["cliente_id"]))
    filas = db.session.execute(consulta.order_by(func.lower(Contacto.nombre)).limit(2000)).scalars().all()
    clientes = nombres_clientes()
    return jsonify([contacto_dict(c, clientes) for c in filas])


@bp.post("/api/contactos")
@requiere_rol("comercial")
def api_crear_contacto():
    v = validar(cuerpo(), ESQUEMA_CONTACTO)
    comprobar_referencias(g.org.id, v)
    c = Contacto(org_id=g.org.id, **v)
    db.session.add(c)
    db.session.flush()
    registrar(g.org.id, "contacto", c.id, quien(), "Alta", f"{c.nombre} {c.apellidos}".strip())
    db.session.commit()
    return jsonify(contacto_dict(c)), 201


@bp.put("/api/contactos/<int:cid>")
@requiere_rol("comercial")
def api_editar_contacto(cid):
    c = obtener(Contacto, cid)
    v = validar(cuerpo(), ESQUEMA_CONTACTO)
    comprobar_referencias(g.org.id, v)
    for k, val in v.items():
        setattr(c, k, val)
    registrar(g.org.id, "contacto", c.id, quien(), "Edición", f"{c.nombre} {c.apellidos}".strip())
    db.session.commit()
    return jsonify(contacto_dict(c))


@bp.delete("/api/contactos/<int:cid>")
@requiere_rol("comercial")
def api_borrar_contacto(cid):
    c = obtener(Contacto, cid)
    registrar(g.org.id, "contacto", c.id, quien(), "Eliminado", f"{c.nombre} {c.apellidos}".strip())
    db.session.delete(c)
    db.session.commit()
    return jsonify(ok=True)


# ── oportunidades (y embudo) ──────────────────────────────────────────────
@bp.get("/api/oportunidades")
@requiere_login
def api_oportunidades():
    consulta = select(Oportunidad).where(Oportunidad.org_id == g.org.id)
    q = request.args.get("q", "").strip()
    if q:
        p = patron(q)
        consulta = consulta.outerjoin(Cliente, Cliente.id == Oportunidad.cliente_id).where(
            or_(Oportunidad.titulo.ilike(p), Cliente.nombre.ilike(p)))
    if request.args.get("etapa") in ETAPAS:
        consulta = consulta.where(Oportunidad.etapa == request.args["etapa"])
    if request.args.get("abiertas") == "1":
        consulta = consulta.where(Oportunidad.etapa.in_(ABIERTAS))
    if request.args.get("responsable_id", "").isdigit():
        consulta = consulta.where(Oportunidad.responsable_id == int(request.args["responsable_id"]))
    orden = case({e: i for i, e in enumerate(ETAPAS)}, value=Oportunidad.etapa)
    filas = db.session.execute(consulta.order_by(orden, Oportunidad.importe.desc()).limit(2000)).scalars().all()
    usuarios, clientes = nombres_usuarios(), nombres_clientes()
    return jsonify([oportunidad_dict(o, usuarios, clientes) for o in filas])


def _datos_oportunidad(d: dict, actual: Oportunidad | None = None) -> dict:
    v = validar(d, ESQUEMA_OPORTUNIDAD)
    comprobar_referencias(g.org.id, v)
    v["etapa"] = v.get("etapa") or (actual.etapa if actual else "Nuevo")
    if v.get("probabilidad") is None:
        v["probabilidad"] = PROBABILIDAD_ETAPA[v["etapa"]]
    v["importe"] = v.get("importe") or 0
    return v


@bp.post("/api/oportunidades")
@requiere_rol("comercial")
def api_crear_oportunidad():
    v = _datos_oportunidad(cuerpo())
    v["responsable_id"] = v.get("responsable_id") or g.usuario.id
    o = Oportunidad(org_id=g.org.id, **v)
    db.session.add(o)
    db.session.flush()
    registrar(g.org.id, "oportunidad", o.id, quien(), "Alta", f"{o.titulo} · {o.etapa}")
    db.session.commit()
    return jsonify(oportunidad_dict(o)), 201


@bp.put("/api/oportunidades/<int:oid>")
@requiere_rol("comercial")
def api_editar_oportunidad(oid):
    o = obtener(Oportunidad, oid)
    antes = o.etapa
    for k, val in _datos_oportunidad(cuerpo(), o).items():
        setattr(o, k, val)
    registrar(g.org.id, "oportunidad", o.id, quien(), "Edición", f"{antes} → {o.etapa}" if antes != o.etapa else o.titulo)
    db.session.commit()
    return jsonify(oportunidad_dict(o))


@bp.patch("/api/oportunidades/<int:oid>/etapa")
@requiere_rol("comercial")
def api_mover_oportunidad(oid):
    o = obtener(Oportunidad, oid)
    etapa = cuerpo().get("etapa")
    if etapa not in ETAPAS:
        raise ErrorValidacion({"etapa": "Etapa no válida."})
    antes = o.etapa
    o.etapa, o.probabilidad = etapa, PROBABILIDAD_ETAPA[etapa]
    if etapa in ("Ganado", "Perdido") and not o.fecha_cierre:
        o.fecha_cierre = date.today()
    if etapa == "Ganado" and o.cliente_id:
        c = db.session.get(Cliente, o.cliente_id)
        if c and c.tipo == "Cliente potencial":
            c.tipo = "Cliente"
    registrar(g.org.id, "oportunidad", o.id, quien(), "Etapa", f"{antes} → {etapa}")
    db.session.commit()
    return jsonify(oportunidad_dict(o))


@bp.delete("/api/oportunidades/<int:oid>")
@requiere_rol("comercial")
def api_borrar_oportunidad(oid):
    o = obtener(Oportunidad, oid)
    registrar(g.org.id, "oportunidad", o.id, quien(), "Eliminada", o.titulo)
    db.session.execute(Lead.__table__.update().where(Lead.oportunidad_id == o.id).values(oportunidad_id=None))
    db.session.delete(o)
    db.session.commit()
    return jsonify(ok=True)


# ── tareas ────────────────────────────────────────────────────────────────
@bp.get("/api/tareas")
@requiere_login
def api_tareas():
    consulta = select(Tarea).where(Tarea.org_id == g.org.id)
    a = request.args
    if a.get("estado") in ESTADOS_TAREA:
        consulta = consulta.where(Tarea.estado == a["estado"])
    elif a.get("estado") == "abiertas":
        consulta = consulta.where(Tarea.estado != "Hecha")
    if a.get("asignado") == "yo":
        consulta = consulta.where(Tarea.asignado_id == g.usuario.id)
    elif a.get("asignado", "").isdigit():
        consulta = consulta.where(Tarea.asignado_id == int(a["asignado"]))
    if a.get("vencidas") == "1":
        consulta = consulta.where(Tarea.vence < date.today(), Tarea.estado != "Hecha")
    if a.get("q", "").strip():
        p = patron(a["q"].strip())
        consulta = consulta.where(or_(Tarea.titulo.ilike(p), Tarea.descripcion.ilike(p)))
    for campo in ("cliente_id", "oportunidad_id", "lead_id"):
        if a.get(campo, "").isdigit():
            consulta = consulta.where(getattr(Tarea, campo) == int(a[campo]))
    hecha_al_final = case((Tarea.estado == "Hecha", 1), else_=0)
    filas = db.session.execute(consulta.order_by(hecha_al_final, Tarea.vence.asc().nulls_last(), Tarea.id).limit(2000)).scalars().all()
    usuarios, clientes = nombres_usuarios(), nombres_clientes()
    return jsonify([tarea_dict(t, usuarios, clientes) for t in filas])


def _datos_tarea(d: dict) -> dict:
    v = validar(d, ESQUEMA_TAREA)
    comprobar_referencias(g.org.id, v)
    v["prioridad"] = v.get("prioridad") or "Media"
    v["estado"] = v.get("estado") or "Pendiente"
    return v


@bp.post("/api/tareas")
@requiere_rol("comercial")
def api_crear_tarea():
    v = _datos_tarea(cuerpo())
    v["asignado_id"] = v.get("asignado_id") or g.usuario.id
    t = Tarea(org_id=g.org.id, **v, completada=ahora() if v["estado"] == "Hecha" else None)
    db.session.add(t)
    db.session.flush()
    registrar(g.org.id, "tarea", t.id, quien(), "Alta", t.titulo)
    db.session.commit()
    return jsonify(tarea_dict(t)), 201


@bp.put("/api/tareas/<int:tid>")
@requiere_rol("comercial")
def api_editar_tarea(tid):
    t = obtener(Tarea, tid)
    v = _datos_tarea(cuerpo())
    if v["estado"] == "Hecha" and t.estado != "Hecha":
        t.completada = ahora()
    elif v["estado"] != "Hecha":
        t.completada = None
    for k, val in v.items():
        setattr(t, k, val)
    registrar(g.org.id, "tarea", t.id, quien(), "Edición", t.titulo)
    db.session.commit()
    return jsonify(tarea_dict(t))


@bp.patch("/api/tareas/<int:tid>/estado")
@requiere_rol("comercial")
def api_estado_tarea(tid):
    t = obtener(Tarea, tid)
    estado = cuerpo().get("estado")
    if estado not in ESTADOS_TAREA:
        raise ErrorValidacion({"estado": "Estado no válido."})
    t.estado, t.completada = estado, ahora() if estado == "Hecha" else None
    registrar(g.org.id, "tarea", t.id, quien(), "Estado", f"{t.titulo} → {estado}")
    db.session.commit()
    return jsonify(tarea_dict(t))


@bp.delete("/api/tareas/<int:tid>")
@requiere_rol("comercial")
def api_borrar_tarea(tid):
    t = obtener(Tarea, tid)
    registrar(g.org.id, "tarea", t.id, quien(), "Eliminada", t.titulo)
    db.session.delete(t)
    db.session.commit()
    return jsonify(ok=True)


# ── usuarios de la empresa (administradores) ──────────────────────────────
def usuario_dict(u: Usuario) -> dict:
    return {"id": u.id, "nombre": u.nombre, "email": u.email, "rol": u.rol, "activo": u.activo,
            "creado": iso(u.creado), "ultimo_acceso": iso(u.ultimo_acceso)}


@bp.get("/api/usuarios")
@requiere_rol("admin")
def api_usuarios():
    filas = db.session.execute(select(Usuario).where(Usuario.org_id == g.org.id).order_by(Usuario.id)).scalars()
    return jsonify([usuario_dict(u) for u in filas])


@bp.post("/api/usuarios")
@requiere_rol("admin")
def api_crear_usuario():
    d = cuerpo()
    nombre, email, clave = str(d.get("nombre", "")).strip(), str(d.get("email", "")).strip().lower(), str(d.get("clave", ""))
    rol = d.get("rol") if d.get("rol") in ("lectura", "comercial", "admin") else "comercial"
    if not nombre or len(nombre) > 120:
        raise ErrorValidacion({"nombre": "Escribe un nombre."})
    if not EMAIL_RE.match(email):
        raise ErrorValidacion({"email": "El email no tiene un formato válido."})
    if problema_clave(clave, email):
        raise ErrorValidacion({"clave": problema_clave(clave, email)})
    if db.session.execute(select(Usuario.id).where(Usuario.email == email)).first():
        raise ErrorValidacion({"email": "Ya existe un usuario con ese email."})
    u = Usuario(org_id=g.org.id, nombre=nombre, email=email, hash=hash_clave(clave), rol=rol, activo=True, version_sesion=1)
    db.session.add(u)
    db.session.flush()
    registrar(g.org.id, "usuario", u.id, quien(), "Alta", f"{email} · {rol}")
    db.session.commit()
    return jsonify(usuario_dict(u)), 201


@bp.patch("/api/usuarios/<int:uid>")
@requiere_rol("admin")
def api_editar_usuario(uid):
    u = obtener(Usuario, uid)
    d = cuerpo()
    if u.id == g.usuario.id:
        raise ErrorValidacion({"usuario": "No puedes cambiar tu propio rol ni desactivarte."})
    if u.rol == "propietario" and g.usuario.rol != "propietario":
        raise ErrorValidacion({"usuario": "Solo el propietario puede modificar al propietario."})
    if "rol" in d:
        if d["rol"] not in ("lectura", "comercial", "admin"):
            raise ErrorValidacion({"rol": "Rol no válido."})
        u.rol = d["rol"]
    if "activo" in d:
        u.activo = bool(d["activo"])
    u.version_sesion += 1   # el cambio se aplica ya: su sesión abierta se cierra
    registrar(g.org.id, "usuario", u.id, quien(), "Permisos", f"{u.email} · {u.rol} · {'activo' if u.activo else 'sin acceso'}")
    db.session.commit()
    return jsonify(usuario_dict(u))


@bp.delete("/api/usuarios/<int:uid>")
@requiere_rol("admin")
def api_borrar_usuario(uid):
    u = obtener(Usuario, uid)
    if u.id == g.usuario.id:
        raise ErrorValidacion({"usuario": "No puedes borrar tu propio usuario."})
    if u.rol == "propietario":
        raise ErrorValidacion({"usuario": "No se puede borrar al propietario de la empresa."})
    registrar(g.org.id, "usuario", u.id, quien(), "Eliminado", u.email)
    db.session.delete(u)
    db.session.commit()
    return jsonify(ok=True)


# ── ajustes de la empresa ─────────────────────────────────────────────────
@bp.get("/api/organizacion")
@requiere_login
def api_organizacion():
    a = g.org.ajustes or {}
    return jsonify({"nombre": g.org.nombre, **marca(g.org), "fecha_referencia": a.get("fecha_referencia") or "",
                    "demo": bool(a.get("demo")), "leads": db.session.scalar(
                        select(func.count()).select_from(Lead).where(Lead.org_id == g.org.id))})


@bp.put("/api/organizacion")
@requiere_rol("admin")
def api_editar_organizacion():
    v = validar(cuerpo(), {"nombre": {"obligatorio": True, "max": 120, "etiqueta": "Nombre"},
                           "producto": {"max": 120, "etiqueta": "Producto"},
                           "firma": {"max": 200, "etiqueta": "Firma"},
                           "descripcion_negocio": {"tipo": "largo", "max": 2000, "etiqueta": "Descripción"},
                           "fecha_referencia": {"tipo": "fecha", "etiqueta": "Fecha de referencia"}})
    g.org.nombre = v["nombre"]
    a = dict(g.org.ajustes or {})
    a.update(producto=v["producto"], firma=v["firma"], descripcion_negocio=v["descripcion_negocio"],
             fecha_referencia=v["fecha_referencia"].isoformat() if v["fecha_referencia"] else None)
    g.org.ajustes = a
    registrar(g.org.id, "organizacion", g.org.id, quien(), "Ajustes")
    db.session.commit()
    return jsonify(ok=True)


@bp.post("/api/organizacion/demo")
@requiere_rol("admin")
def api_demo():
    if db.session.scalar(select(func.count()).select_from(Lead).where(Lead.org_id == g.org.id)):
        raise ErrorValidacion({"demo": "Los datos de ejemplo solo se pueden cargar en una empresa sin leads."})
    n = cargar_demo(g.org, quien())
    db.session.commit()
    return jsonify(cargados=n)


# ── informes ──────────────────────────────────────────────────────────────
@bp.get("/api/informes")
@requiere_login
def api_informes():
    oid = g.org.id
    usuarios = nombres_usuarios()
    por_resp = {}
    for rid, etapa, n, valor in db.session.execute(
            select(Oportunidad.responsable_id, Oportunidad.etapa, func.count(), func.coalesce(func.sum(Oportunidad.importe), 0))
            .where(Oportunidad.org_id == oid).group_by(Oportunidad.responsable_id, Oportunidad.etapa)).all():
        r = por_resp.setdefault(rid, {"responsable": usuarios.get(rid, "Sin asignar"), "abiertas": 0, "valor_abierto": 0.0,
                                      "ganadas": 0, "valor_ganado": 0.0, "perdidas": 0})
        if etapa == "Ganado":
            r["ganadas"] += n; r["valor_ganado"] += float(valor)
        elif etapa == "Perdido":
            r["perdidas"] += n
        else:
            r["abiertas"] += n; r["valor_abierto"] += float(valor)
    tareas = {}
    for aid, estado, n in db.session.execute(select(Tarea.asignado_id, Tarea.estado, func.count())
                                             .where(Tarea.org_id == oid).group_by(Tarea.asignado_id, Tarea.estado)).all():
        t = tareas.setdefault(aid, {"usuario": usuarios.get(aid, "Sin asignar"), "Pendiente": 0, "En curso": 0, "Hecha": 0})
        t[estado] = n
    leads = leads_org()
    est = capa3_salidas.estadisticas(leads)
    return jsonify({"por_responsable": list(por_resp.values()), "tareas_por_usuario": list(tareas.values()),
                    "leads_por_origen": est["por_origen"], "leads_por_sector": est["por_sector"],
                    "leads_por_clase": est["por_clase"], "hot_ocultos": est["hot_ocultos"]})


# ── descargas (reutilizan capa3_salidas) ──────────────────────────────────
def _csv(nombre: str, cabeceras: list[str], filas: list[list]):
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(cabeceras)
    w.writerows(filas)
    datos = io.BytesIO(("﻿" + buf.getvalue()).encode("utf-8"))
    return send_file(datos, as_attachment=True, download_name=nombre, mimetype="text/csv")


@bp.get("/descargas/<tipo>")
@requiere_login
def descargar(tipo):
    leads = leads_org()
    meta = {"fecha_referencia": fecha_ref(g.org).isoformat()}
    resumen = rellenar(g.org, g.org.resumen or {})
    est = capa3_salidas.estadisticas(leads)
    if tipo == "oportunidades":
        filas = [oportunidad_dict(o) for o in db.session.execute(select(Oportunidad).where(Oportunidad.org_id == g.org.id)).scalars()]
        return _csv("oportunidades.csv", ["ID", "Título", "Cliente", "Etapa", "Importe", "Probabilidad", "Ponderado",
                                          "Cierre", "Responsable"],
                    [[o["id"], o["titulo"], o["cliente"], o["etapa"], o["importe"], o["probabilidad"], o["ponderado"],
                      o["fecha_cierre"] or "", o["responsable"]] for o in filas])
    if tipo == "clientes":
        usuarios = nombres_usuarios()
        filas = db.session.execute(select(Cliente).where(Cliente.org_id == g.org.id).order_by(Cliente.nombre)).scalars()
        return _csv("clientes.csv", ["ID", "Nombre", "Tipo", "Sector", "Empleados", "País", "Ciudad", "Web", "Teléfono", "Responsable"],
                    [[c.id, c.nombre, c.tipo, c.sector, c.empleados or "", c.pais, c.ciudad, c.web, c.telefono,
                      usuarios.get(c.responsable_id, "")] for c in filas])
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
