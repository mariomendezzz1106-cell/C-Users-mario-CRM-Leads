"""
Lógica de negocio: reutiliza el motor de la capa 1 para validar y puntuar
cada lead, y valida los datos de clientes, contactos, oportunidades y tareas.
"""
from __future__ import annotations

import json
import re
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import func, select

import capa1_motor
from .ajustes import RAIZ
from .modelos import (ESTADOS_LEAD, ESTADOS_TAREA, ETAPAS, PRIORIDADES_TAREA, PROBABILIDAD_ETAPA, Cliente,
                      Contacto, Historial, Lead, Oportunidad, Organizacion, Tarea, Usuario, ahora, db)

# Columnas originales del CSV de leads (las que se editan desde la web)
CAMPOS_LEAD = ["nombre", "apellidos", "email", "telefono", "empresa", "cargo", "sector", "empleados", "pais",
               "ciudad", "origen", "presupuesto_eur", "plazo_compra", "visitas_web", "descargas",
               "emails_abiertos", "demo_solicitada", "fecha_alta", "ultimo_contacto", "comentarios"]
QUE_HACER = {"HOT": "Contactar esta semana", "WARM": "Seguimiento con contenido de valor",
             "COLD": "Nurturing automático", "REVISAR DATOS": "Corregir datos antes de contactar"}
AUTO = {"HOT": ("P1", "48 h", 2, "Llamada"), "REVISAR DATOS": ("P2", "48 h", 2, "Revisión interna"),
        "WARM": ("P3", "1 semana", 7, "Email"), "COLD": ("P4", "1 mes", 30, "Nurturing")}
SECTORES = sorted(["Tecnología", "Retail", "Logística", "Salud", "Industria", "Energía", "Servicios profesionales",
                   "Hostelería", "Agroalimentario", "Construcción", "Educación", "Administración pública"])
ORIGENES = ["Referido", "Feria", "Webinar", "Web", "LinkedIn", "Email frío"]
PLAZOS = ["Inmediato", "1-3 meses", "3-6 meses", "+6 meses", "Sin definir"]
TIPOS_CLIENTE = ["Cliente potencial", "Cliente", "Antiguo cliente"]
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


class ErrorValidacion(ValueError):
    def __init__(self, errores: dict[str, str]):
        super().__init__("; ".join(errores.values()))
        self.errores = errores


# ── marca de la empresa ───────────────────────────────────────────────────
def marca(org: Organizacion) -> dict:
    a = org.ajustes or {}
    return {"empresa": org.nombre, "producto": a.get("producto") or "nuestro producto",
            "firma": a.get("firma") or f"Equipo comercial · {org.nombre}",
            "descripcion_negocio": a.get("descripcion_negocio") or ""}


def rellenar(org: Organizacion, valor):
    """Sustituye {empresa}, {producto} y {firma} en textos anidados."""
    m = marca(org)
    if isinstance(valor, str):
        return valor.replace("{empresa}", m["empresa"]).replace("{producto}", m["producto"]).replace("{firma}", m["firma"])
    if isinstance(valor, list):
        return [rellenar(org, v) for v in valor]
    if isinstance(valor, dict):
        return {k: rellenar(org, v) for k, v in valor.items()}
    return valor


def fecha_ref(org: Organizacion) -> date:
    f = (org.ajustes or {}).get("fecha_referencia")
    return date.fromisoformat(f) if f else date.today()


def registrar(org_id: int, entidad: str, entidad_id, usuario: str, accion: str, detalle: str = ""):
    db.session.add(Historial(org_id=org_id, entidad=entidad, entidad_id=entidad_id, usuario=usuario,
                             accion=accion, detalle=detalle[:2000]))


# ── validación genérica ───────────────────────────────────────────────────
def validar(payload: dict, esquema: dict, parcial: bool = False) -> dict:
    """esquema: campo -> dict(tipo, obligatorio, max, opciones, min, etiqueta).
    Devuelve los valores limpios o lanza ErrorValidacion con un mensaje por campo."""
    limpio, errores = {}, {}
    for campo, reglas in esquema.items():
        if parcial and campo not in payload:
            continue
        etiqueta = reglas.get("etiqueta", campo)
        bruto = payload.get(campo)
        texto = "" if bruto is None else str(bruto).strip()
        tipo = reglas.get("tipo", "texto")
        if not texto:
            if reglas.get("obligatorio"):
                errores[campo] = f"{etiqueta}: es obligatorio."
            limpio[campo] = None if tipo in ("entero", "decimal", "fecha", "ref") else ""
            continue
        try:
            if tipo in ("texto", "largo"):
                maximo = reglas.get("max", 5000 if tipo == "largo" else 200)
                if len(texto) > maximo:
                    raise ValueError(f"máximo {maximo} caracteres")
                valor = texto
            elif tipo == "email":
                if not EMAIL_RE.match(texto) or len(texto) > 254:
                    raise ValueError("formato no válido")
                valor = texto.lower()
            elif tipo == "entero" or tipo == "ref":
                valor = int(texto)
                if valor < reglas.get("min", 0):
                    raise ValueError(f"debe ser {reglas.get('min', 0)} o más")
                if "maximo" in reglas and valor > reglas["maximo"]:
                    raise ValueError(f"debe ser {reglas['maximo']} o menos")
            elif tipo == "decimal":
                valor = float(texto.replace(",", "."))
                if valor < reglas.get("min", 0):
                    raise ValueError("no puede ser negativo")
            elif tipo == "fecha":
                valor = date.fromisoformat(texto)
            else:
                valor = texto
            if "opciones" in reglas and valor not in reglas["opciones"]:
                raise ValueError("valor no permitido")
        except ValueError as e:
            msg = str(e) if any(p in str(e) for p in ("máximo", "debe", "formato", "permitido", "negativo")) else "valor no válido"
            errores[campo] = f"{etiqueta}: {msg}."
            continue
        limpio[campo] = valor
    if errores:
        raise ErrorValidacion(errores)
    return limpio


ESQUEMA_CLIENTE = {
    "nombre": {"obligatorio": True, "max": 160, "etiqueta": "Nombre"},
    "sector": {"max": 80, "etiqueta": "Sector"},
    "empleados": {"tipo": "entero", "min": 1, "maximo": 10_000_000, "etiqueta": "Empleados"},
    "pais": {"max": 80, "etiqueta": "País"}, "ciudad": {"max": 80, "etiqueta": "Ciudad"},
    "web": {"max": 200, "etiqueta": "Web"}, "telefono": {"max": 40, "etiqueta": "Teléfono"},
    "tipo": {"opciones": TIPOS_CLIENTE, "etiqueta": "Tipo"},
    "notas": {"tipo": "largo", "etiqueta": "Notas"},
    "responsable_id": {"tipo": "ref", "etiqueta": "Responsable"},
}
ESQUEMA_CONTACTO = {
    "nombre": {"obligatorio": True, "max": 80, "etiqueta": "Nombre"},
    "apellidos": {"max": 120, "etiqueta": "Apellidos"},
    "email": {"tipo": "email", "etiqueta": "Email"},
    "telefono": {"max": 40, "etiqueta": "Teléfono"}, "cargo": {"max": 120, "etiqueta": "Cargo"},
    "cliente_id": {"tipo": "ref", "etiqueta": "Cliente"},
    "notas": {"tipo": "largo", "etiqueta": "Notas"},
}
ESQUEMA_OPORTUNIDAD = {
    "titulo": {"obligatorio": True, "max": 200, "etiqueta": "Título"},
    "cliente_id": {"tipo": "ref", "etiqueta": "Cliente"},
    "contacto_id": {"tipo": "ref", "etiqueta": "Contacto"},
    "importe": {"tipo": "decimal", "min": 0, "etiqueta": "Importe"},
    "etapa": {"opciones": ETAPAS, "etiqueta": "Etapa"},
    "probabilidad": {"tipo": "entero", "min": 0, "maximo": 100, "etiqueta": "Probabilidad"},
    "fecha_cierre": {"tipo": "fecha", "etiqueta": "Fecha de cierre"},
    "responsable_id": {"tipo": "ref", "etiqueta": "Responsable"},
    "notas": {"tipo": "largo", "etiqueta": "Notas"},
}
ESQUEMA_TAREA = {
    "titulo": {"obligatorio": True, "max": 200, "etiqueta": "Título"},
    "descripcion": {"tipo": "largo", "etiqueta": "Descripción"},
    "vence": {"tipo": "fecha", "etiqueta": "Vence"},
    "prioridad": {"opciones": PRIORIDADES_TAREA, "etiqueta": "Prioridad"},
    "estado": {"opciones": ESTADOS_TAREA, "etiqueta": "Estado"},
    "asignado_id": {"tipo": "ref", "etiqueta": "Asignada a"},
    "cliente_id": {"tipo": "ref", "etiqueta": "Cliente"},
    "oportunidad_id": {"tipo": "ref", "etiqueta": "Oportunidad"},
    "lead_id": {"tipo": "ref", "etiqueta": "Lead"},
}
# Campos del lead: se guardan tal cual (el motor marca los errores); solo se limita tamaño y formato básico
ESQUEMA_LEAD = {c: {"max": 2000 if c == "comentarios" else 200, "etiqueta": c} for c in CAMPOS_LEAD}
ESQUEMA_LEAD["empresa"] = {"obligatorio": True, "max": 200, "etiqueta": "Empresa"}


def comprobar_referencias(org_id: int, valores: dict):
    """Las referencias (cliente, contacto, usuario…) deben ser de la MISMA empresa."""
    tablas = {"cliente_id": Cliente, "contacto_id": Contacto, "oportunidad_id": Oportunidad, "lead_id": Lead,
              "responsable_id": Usuario, "asignado_id": Usuario}
    errores = {}
    for campo, modelo in tablas.items():
        rid = valores.get(campo)
        if rid is None:
            continue
        obj = db.session.get(modelo, rid)
        if obj is None or obj.org_id != org_id:
            errores[campo] = "La referencia no existe."
    if errores:
        raise ErrorValidacion(errores)


# ── leads (motor de la capa 1) ────────────────────────────────────────────
def emails_existentes(org_id: int, excepto_id: int | None = None) -> dict:
    vistos = {}
    filas = db.session.execute(select(Lead.id, Lead.codigo, Lead.datos["email"].astext)
                               .where(Lead.org_id == org_id).order_by(Lead.id)).all()
    for lid, codigo, email in filas:
        email = (email or "").strip().lower()
        if lid != excepto_id and email and email not in vistos:
            vistos[email] = codigo
    return vistos


def analisis_automatico(org: Organizacion, r: dict) -> dict:
    prioridad, plazo, dias, canal = AUTO[r["clasificacion"]]
    return {"justificacion": "; ".join(r["motivos"]) or "Sin factores destacados.",
            "accion": QUE_HACER[r["clasificacion"]], "canal": canal, "prioridad": prioridad,
            "plazo_accion": plazo, "fecha_limite": (fecha_ref(org) + timedelta(days=dias)).isoformat(),
            "oportunidades": [], "riesgos": [], "correo": None, "automatico": True}


def limpiar_lead(datos: dict) -> dict:
    validos = validar(datos, ESQUEMA_LEAD)
    return {c: validos.get(c) or "" for c in CAMPOS_LEAD}


def evaluar(org: Organizacion, codigo: str, datos: dict, excepto_id: int | None = None) -> dict:
    return capa1_motor.evaluar({"id_lead": codigo, **datos}, emails_existentes(org.id, excepto_id), fecha_ref(org))


def siguiente_codigo(org: Organizacion) -> str:
    # Bloquea la fila de la empresa para que dos altas simultáneas no repitan código
    org = db.session.execute(select(Organizacion).where(Organizacion.id == org.id).with_for_update()).scalar_one()
    n = org.siguiente_lead or 1
    org.siguiente_lead = n + 1
    return f"L{n:03d}"


def crear_lead(org: Organizacion, datos: dict, usuario: str, analisis: dict | None = None, codigo: str | None = None) -> Lead:
    datos = limpiar_lead(datos)
    codigo = codigo or siguiente_codigo(org)
    r = evaluar(org, codigo, datos)
    lead = Lead(org_id=org.id, codigo=codigo, datos=datos, resultado=r,
                analisis=analisis or analisis_automatico(org, r), puntuacion=r["puntuacion"],
                clasificacion=r["clasificacion"], actualizado=ahora(), actualizado_por=usuario)
    db.session.add(lead)
    db.session.flush()
    registrar(org.id, "lead", lead.id, usuario, "Alta", f"{codigo} · {r['clasificacion']} · {r['puntuacion']} puntos")
    return lead


def editar_lead(org: Organizacion, lead: Lead, datos: dict, usuario: str) -> Lead:
    datos = limpiar_lead(datos)
    antes = lead.resultado
    r = evaluar(org, lead.codigo, datos, excepto_id=lead.id)
    if r["clasificacion"] != antes["clasificacion"]:
        lead.analisis = analisis_automatico(org, r)  # la clase cambió: el análisis anterior ya no vale
    lead.datos, lead.resultado = datos, r
    lead.puntuacion, lead.clasificacion = r["puntuacion"], r["clasificacion"]
    lead.actualizado, lead.actualizado_por = ahora(), usuario
    registrar(org.id, "lead", lead.id, usuario, "Edición",
              f"{antes['clasificacion']} {antes['puntuacion']} → {r['clasificacion']} {r['puntuacion']}")
    return lead


def cambiar_estado_lead(org: Organizacion, lead: Lead, estado: str, notas: str, usuario: str):
    if estado not in ESTADOS_LEAD:
        raise ErrorValidacion({"estado": "Estado no válido."})
    anterior = lead.estado
    lead.estado, lead.notas = estado, (notas or "").strip()[:5000]
    lead.actualizado, lead.actualizado_por = ahora(), usuario
    registrar(org.id, "lead", lead.id, usuario, "Seguimiento", f"{anterior} → {estado}")


def lead_dict(org: Organizacion, lead: Lead) -> dict:
    """Misma forma que usaba el panel original (y capa3_salidas)."""
    return {**lead.resultado, "id_lead": lead.codigo, "id": lead.id,
            "analisis": rellenar(org, lead.analisis), "estado": lead.estado, "notas": lead.notas,
            "actualizado": lead.actualizado.isoformat(timespec="seconds") if lead.actualizado else "",
            "actualizado_por": lead.actualizado_por, "cliente_id": lead.cliente_id,
            "contacto_id": lead.contacto_id, "oportunidad_id": lead.oportunidad_id}


def convertir_lead(org: Organizacion, lead: Lead, usuario: Usuario) -> Oportunidad:
    """Crea (o reutiliza) cliente y contacto y abre una oportunidad a partir del lead."""
    if lead.oportunidad_id:
        raise ErrorValidacion({"lead": "Este lead ya se convirtió en oportunidad."})
    d = lead.datos
    nombre_emp = (d.get("empresa") or "").strip()
    cliente = db.session.execute(select(Cliente).where(Cliente.org_id == org.id,
                                                       func.lower(Cliente.nombre) == nombre_emp.lower())).scalars().first()
    if not cliente:
        empleados = capa1_motor.a_numero(d.get("empleados"))
        cliente = Cliente(org_id=org.id, nombre=nombre_emp, sector=d.get("sector", ""), pais=d.get("pais", ""),
                          ciudad=d.get("ciudad", ""), telefono="", responsable_id=usuario.id,
                          empleados=int(empleados) if isinstance(empleados, float) and empleados > 0 else None)
        db.session.add(cliente)
        db.session.flush()
        registrar(org.id, "cliente", cliente.id, usuario.nombre, "Alta", f"Desde el lead {lead.codigo}")
    email = (d.get("email") or "").strip().lower()
    contacto = None
    if email and EMAIL_RE.match(email):
        contacto = db.session.execute(select(Contacto).where(Contacto.org_id == org.id,
                                                             func.lower(Contacto.email) == email)).scalars().first()
    if not contacto and (d.get("nombre") or "").strip():
        contacto = Contacto(org_id=org.id, cliente_id=cliente.id, nombre=d.get("nombre", "").strip(),
                            apellidos=d.get("apellidos", ""), email=email if EMAIL_RE.match(email or "") else "",
                            telefono=d.get("telefono", ""), cargo=d.get("cargo", ""))
        db.session.add(contacto)
        db.session.flush()
    importe = capa1_motor.a_numero(d.get("presupuesto_eur"))
    op = Oportunidad(org_id=org.id, titulo=f"{nombre_emp} · {marca(org)['producto']}", cliente_id=cliente.id,
                     contacto_id=contacto.id if contacto else None, lead_id=lead.id,
                     importe=importe if isinstance(importe, float) and importe > 0 else 0,
                     etapa="Cualificado", probabilidad=PROBABILIDAD_ETAPA["Cualificado"],
                     responsable_id=usuario.id, notas=lead.analisis.get("accion", ""))
    db.session.add(op)
    db.session.flush()
    lead.cliente_id, lead.contacto_id, lead.oportunidad_id = cliente.id, contacto.id if contacto else None, op.id
    if lead.estado == "Pendiente":
        lead.estado = "En curso"
    registrar(org.id, "lead", lead.id, usuario.nombre, "Conversión", f"Oportunidad #{op.id}")
    registrar(org.id, "oportunidad", op.id, usuario.nombre, "Alta", f"Desde el lead {lead.codigo}")
    return op


# ── carga de datos de ejemplo (privados de la empresa que los pide) ───────
def cargar_demo(org: Organizacion, usuario: str) -> int:
    csv = RAIZ / "datos" / "leads.csv"
    ruta_an = RAIZ / "salidas" / "capa2_analisis.json"
    c2 = json.loads(ruta_an.read_text(encoding="utf-8")) if ruta_an.exists() else {}
    por_id = {a["id_lead"]: a for a in c2.get("leads", [])}
    filas = capa1_motor.leer_leads(csv)
    # Los datos de ejemplo están fechados en noviembre de 2026: se fija esa fecha para que
    # los días sin contacto coincidan con el análisis guardado (se puede quitar en Ajustes)
    org.ajustes = {**(org.ajustes or {}), "fecha_referencia": "2026-11-23", "demo": True}
    for fila in filas:
        a = dict(por_id.get(fila["id_lead"], {})) or None
        if a:
            a.pop("id_lead", None)
        crear_lead(org, fila, usuario, analisis=a)
    if c2:
        org.resumen = {k: c2.get(k) for k in ["resumen_ejecutivo", "oportunidades_globales", "riesgos_globales"]}
    registrar(org.id, "organizacion", org.id, usuario, "Datos de ejemplo", f"{len(filas)} leads ficticios")
    return len(filas)
