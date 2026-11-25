"""
Modelo de datos (PostgreSQL).

Cada tabla de negocio lleva org_id: los datos de cada empresa están separados
y todas las consultas de la API filtran por la empresa del usuario conectado.
"""
from __future__ import annotations

from datetime import date, datetime

from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import (Boolean, Date, DateTime, ForeignKey, Index, Integer, MetaData, Numeric, String, Text,
                        UniqueConstraint, func)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    # Nombres fijos para índices y restricciones (necesarios para migraciones y borrados limpios)
    metadata = MetaData(naming_convention={
        "ix": "ix_%(column_0_label)s", "uq": "uq_%(table_name)s_%(column_0_name)s",
        "ck": "ck_%(table_name)s_%(constraint_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s", "pk": "pk_%(table_name)s"})


db = SQLAlchemy(model_class=Base)

ROLES = ["lectura", "comercial", "admin", "propietario"]
NIVEL = {r: i for i, r in enumerate(ROLES)}
ESTADOS_LEAD = ["Pendiente", "En curso", "Hecho", "Descartado"]
ETAPAS = ["Nuevo", "Cualificado", "Propuesta", "Negociación", "Ganado", "Perdido"]
PROBABILIDAD_ETAPA = {"Nuevo": 10, "Cualificado": 25, "Propuesta": 50, "Negociación": 75, "Ganado": 100, "Perdido": 0}
ESTADOS_TAREA = ["Pendiente", "En curso", "Hecha"]
PRIORIDADES_TAREA = ["Alta", "Media", "Baja"]


def ahora() -> datetime:
    return datetime.now().astimezone()


class Organizacion(db.Model):
    __tablename__ = "organizaciones"
    id: Mapped[int] = mapped_column(primary_key=True)
    nombre: Mapped[str] = mapped_column(String(120))
    # Textos de marca que la IA y los correos usan: producto, firma, descripción del negocio
    ajustes: Mapped[dict] = mapped_column(JSONB, default=dict)
    # Conclusión global de la cartera (resumen, oportunidades, riesgos)
    resumen: Mapped[dict] = mapped_column(JSONB, default=dict)
    siguiente_lead: Mapped[int] = mapped_column(Integer, default=1)
    creada: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Usuario(db.Model):
    __tablename__ = "usuarios"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True)
    hash: Mapped[str] = mapped_column(String(255))
    rol: Mapped[str] = mapped_column(String(20), default="comercial")
    activo: Mapped[bool] = mapped_column(Boolean, default=True)
    # Al cambiar la contraseña o quitar el acceso se incrementa: invalida las sesiones abiertas
    version_sesion: Mapped[int] = mapped_column(Integer, default=1)
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    ultimo_acceso: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    org: Mapped[Organizacion] = relationship()


class IntentoLogin(db.Model):
    """Registro de intentos fallidos para frenar ataques de fuerza bruta."""
    __tablename__ = "intentos_login"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(254), index=True)
    ip: Mapped[str] = mapped_column(String(64), index=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class Cliente(db.Model):
    __tablename__ = "clientes"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    nombre: Mapped[str] = mapped_column(String(160))
    sector: Mapped[str] = mapped_column(String(80), default="")
    empleados: Mapped[int | None] = mapped_column(Integer)
    pais: Mapped[str] = mapped_column(String(80), default="")
    ciudad: Mapped[str] = mapped_column(String(80), default="")
    web: Mapped[str] = mapped_column(String(200), default="")
    telefono: Mapped[str] = mapped_column(String(40), default="")
    tipo: Mapped[str] = mapped_column(String(20), default="Cliente potencial")  # Cliente potencial · Cliente · Antiguo
    notas: Mapped[str] = mapped_column(Text, default="")
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Contacto(db.Model):
    __tablename__ = "contactos"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id", ondelete="SET NULL"), index=True)
    nombre: Mapped[str] = mapped_column(String(80))
    apellidos: Mapped[str] = mapped_column(String(120), default="")
    email: Mapped[str] = mapped_column(String(254), default="")
    telefono: Mapped[str] = mapped_column(String(40), default="")
    cargo: Mapped[str] = mapped_column(String(120), default="")
    notas: Mapped[str] = mapped_column(Text, default="")
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Lead(db.Model):
    __tablename__ = "leads"
    __table_args__ = (UniqueConstraint("org_id", "codigo"), Index("ix_leads_org_clase", "org_id", "clasificacion"))
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    codigo: Mapped[str] = mapped_column(String(12))                 # L001, L002… (por empresa)
    datos: Mapped[dict] = mapped_column(JSONB)                      # columnas originales del CSV
    resultado: Mapped[dict] = mapped_column(JSONB)                  # salida del motor (capa 1)
    analisis: Mapped[dict] = mapped_column(JSONB)                   # análisis (capa 2: IA o reglas)
    puntuacion: Mapped[int] = mapped_column(Integer, default=0)
    clasificacion: Mapped[str] = mapped_column(String(20), default="COLD")
    estado: Mapped[str] = mapped_column(String(20), default="Pendiente")
    notas: Mapped[str] = mapped_column(Text, default="")
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id", ondelete="SET NULL"))
    contacto_id: Mapped[int | None] = mapped_column(ForeignKey("contactos.id", ondelete="SET NULL"))
    oportunidad_id: Mapped[int | None] = mapped_column(ForeignKey("oportunidades.id", ondelete="SET NULL",
                                                                  use_alter=True))
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado_por: Mapped[str] = mapped_column(String(120), default="")


class Oportunidad(db.Model):
    __tablename__ = "oportunidades"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id", ondelete="SET NULL"), index=True)
    contacto_id: Mapped[int | None] = mapped_column(ForeignKey("contactos.id", ondelete="SET NULL"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    importe: Mapped[float] = mapped_column(Numeric(14, 2), default=0)
    etapa: Mapped[str] = mapped_column(String(20), default="Nuevo")
    probabilidad: Mapped[int] = mapped_column(Integer, default=10)
    fecha_cierre: Mapped[date | None] = mapped_column(Date)
    responsable_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    notas: Mapped[str] = mapped_column(Text, default="")
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    actualizado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Tarea(db.Model):
    __tablename__ = "tareas"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    titulo: Mapped[str] = mapped_column(String(200))
    descripcion: Mapped[str] = mapped_column(Text, default="")
    vence: Mapped[date | None] = mapped_column(Date)
    prioridad: Mapped[str] = mapped_column(String(10), default="Media")
    estado: Mapped[str] = mapped_column(String(20), default="Pendiente")
    asignado_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    cliente_id: Mapped[int | None] = mapped_column(ForeignKey("clientes.id", ondelete="SET NULL"))
    oportunidad_id: Mapped[int | None] = mapped_column(ForeignKey("oportunidades.id", ondelete="SET NULL"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("leads.id", ondelete="SET NULL"))
    creado: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    completada: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Historial(db.Model):
    __tablename__ = "historial"
    __table_args__ = (Index("ix_historial_entidad", "org_id", "entidad", "entidad_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"))
    entidad: Mapped[str] = mapped_column(String(20))        # lead · cliente · contacto · oportunidad · tarea · usuario · ia
    entidad_id: Mapped[int | None] = mapped_column(Integer)
    usuario: Mapped[str] = mapped_column(String(120), default="")
    accion: Mapped[str] = mapped_column(String(40))
    detalle: Mapped[str] = mapped_column(Text, default="")
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class UsoIA(db.Model):
    """Cada llamada real a la IA, para controlar el gasto por empresa."""
    __tablename__ = "uso_ia"
    id: Mapped[int] = mapped_column(primary_key=True)
    org_id: Mapped[int] = mapped_column(ForeignKey("organizaciones.id", ondelete="CASCADE"), index=True)
    usuario_id: Mapped[int | None] = mapped_column(ForeignKey("usuarios.id", ondelete="SET NULL"))
    tipo: Mapped[str] = mapped_column(String(30))
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_salida: Mapped[int] = mapped_column(Integer, default=0)
    ok: Mapped[bool] = mapped_column(Boolean, default=True)
    fecha: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


def crear_tablas():
    """Crea las tablas que falten. Usa un bloqueo de PostgreSQL para que, si arrancan
    varios procesos a la vez (Render, gunicorn), solo uno las cree."""
    from sqlalchemy import text
    with db.engine.begin() as con:
        con.execute(text("SELECT pg_advisory_xact_lock(724150)"))
        Base.metadata.create_all(con)
