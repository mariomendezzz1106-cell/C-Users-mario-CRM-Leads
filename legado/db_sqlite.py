"""
Base de datos de la plataforma (SQLite, un solo fichero: crm.db).

Tablas:
  usuarios   quién puede entrar (contraseña guardada como hash, nunca en claro)
  leads      cada lead: datos originales, resultado del motor y análisis
  historial  quién cambió qué y cuándo
  ajustes    conclusión global del análisis (resumen, oportunidades, riesgos)

La primera vez se carga con datos/leads.csv y salidas/capa2_analisis.json,
así la plataforma arranca con los mismos 30 leads del proyecto.
"""
from __future__ import annotations

import json
import os
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path

import capa1_motor
import config

RUTA_DB = Path(os.environ.get("CRM_DB", Path(__file__).with_name("crm.db")))

# Columnas originales del CSV (las que se pueden editar desde la web)
CAMPOS = ["nombre", "apellidos", "email", "telefono", "empresa", "cargo", "sector", "empleados", "pais",
          "ciudad", "origen", "presupuesto_eur", "plazo_compra", "visitas_web", "descargas",
          "emails_abiertos", "demo_solicitada", "fecha_alta", "ultimo_contacto", "comentarios"]
ESTADOS = ["Pendiente", "En curso", "Hecho", "Descartado"]
QUE_HACER = {"HOT": "Contactar esta semana", "WARM": "Seguimiento con contenido de valor",
             "COLD": "Nurturing automático", "REVISAR DATOS": "Corregir datos antes de contactar"}
# Prioridad y plazo cuando el lead no tiene análisis de la capa 2
AUTO = {"HOT": ("P1", "48 h", 2, "Llamada"), "REVISAR DATOS": ("P2", "48 h", 2, "Revisión interna"),
        "WARM": ("P3", "1 semana", 7, "Email"), "COLD": ("P4", "1 mes", 30, "Nurturing")}

ESQUEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nombre TEXT NOT NULL,
  email TEXT NOT NULL UNIQUE,
  hash TEXT NOT NULL,
  rol TEXT NOT NULL DEFAULT 'comercial',
  creado TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS leads (
  id_lead TEXT PRIMARY KEY,
  datos TEXT NOT NULL,
  resultado TEXT NOT NULL,
  analisis TEXT NOT NULL,
  estado TEXT NOT NULL DEFAULT 'Pendiente',
  notas TEXT NOT NULL DEFAULT '',
  actualizado TEXT NOT NULL,
  actualizado_por TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS historial (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  id_lead TEXT,
  usuario TEXT,
  accion TEXT NOT NULL,
  detalle TEXT NOT NULL DEFAULT '',
  fecha TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS ajustes (
  clave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def fecha_ref() -> date:
    return date.fromisoformat(config.FECHA_REFERENCIA) if config.FECHA_REFERENCIA else date.today()


def conectar() -> sqlite3.Connection:
    con = sqlite3.connect(RUTA_DB)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    return con


def crear_tablas():
    with conectar() as con:
        con.executescript(ESQUEMA)


def registrar(con, id_lead, usuario, accion, detalle=""):
    con.execute("INSERT INTO historial (id_lead, usuario, accion, detalle, fecha) VALUES (?,?,?,?,?)",
                (id_lead, usuario, accion, detalle, ahora()))


# ── análisis automático (cuando no hay análisis de la capa 2) ─────────────
def analisis_automatico(r: dict) -> dict:
    prioridad, plazo, dias, canal = AUTO[r["clasificacion"]]
    return {"justificacion": "; ".join(r["motivos"]) or "Sin factores destacados.",
            "accion": QUE_HACER[r["clasificacion"]], "canal": canal, "prioridad": prioridad,
            "plazo_accion": plazo, "fecha_limite": (fecha_ref() + timedelta(days=dias)).isoformat(),
            "oportunidades": [], "riesgos": [], "correo": None, "automatico": True}


# ── evaluación con el motor de la capa 1 ──────────────────────────────────
def emails_existentes(con, excepto: str | None = None) -> dict:
    """Mapa email -> id de los leads guardados, para detectar duplicados."""
    vistos = {}
    for fila in con.execute("SELECT id_lead, datos FROM leads ORDER BY id_lead"):
        if fila["id_lead"] == excepto:
            continue
        email = json.loads(fila["datos"]).get("email", "").strip().lower()
        if email and email not in vistos:
            vistos[email] = fila["id_lead"]
    return vistos


def evaluar(con, id_lead: str, datos: dict, excepto: str | None = None) -> dict:
    vistos = emails_existentes(con, excepto)
    return capa1_motor.evaluar({"id_lead": id_lead, **datos}, vistos, fecha_ref())


def siguiente_id(con) -> str:
    nums = [int(f["id_lead"][1:]) for f in con.execute("SELECT id_lead FROM leads")
            if f["id_lead"][1:].isdigit()]
    return f"L{(max(nums) + 1) if nums else 1:03d}"


def limpiar(datos: dict) -> dict:
    return {c: str(datos.get(c, "") or "").strip() for c in CAMPOS}


# ── operaciones sobre leads ───────────────────────────────────────────────
def crear_lead(con, datos: dict, usuario: str, analisis: dict | None = None) -> str:
    datos = limpiar(datos)
    id_lead = siguiente_id(con)
    r = evaluar(con, id_lead, datos)
    a = analisis or analisis_automatico(r)
    con.execute("INSERT INTO leads (id_lead, datos, resultado, analisis, actualizado, actualizado_por) "
                "VALUES (?,?,?,?,?,?)", (id_lead, json.dumps(datos, ensure_ascii=False),
                                         json.dumps(r, ensure_ascii=False), json.dumps(a, ensure_ascii=False),
                                         ahora(), usuario))
    registrar(con, id_lead, usuario, "Alta", f"{r['clasificacion']} · {r['puntuacion']} puntos")
    return id_lead


def editar_lead(con, id_lead: str, datos: dict, usuario: str) -> dict:
    fila = con.execute("SELECT * FROM leads WHERE id_lead=?", (id_lead,)).fetchone()
    if not fila:
        raise KeyError(id_lead)
    datos = limpiar(datos)
    antes = json.loads(fila["resultado"])
    r = evaluar(con, id_lead, datos, excepto=id_lead)
    a = json.loads(fila["analisis"])
    # Si cambia la clase, el análisis anterior ya no sirve: se rehace el automático
    if r["clasificacion"] != antes["clasificacion"]:
        a = analisis_automatico(r)
    con.execute("UPDATE leads SET datos=?, resultado=?, analisis=?, actualizado=?, actualizado_por=? WHERE id_lead=?",
                (json.dumps(datos, ensure_ascii=False), json.dumps(r, ensure_ascii=False),
                 json.dumps(a, ensure_ascii=False), ahora(), usuario, id_lead))
    registrar(con, id_lead, usuario, "Edición",
              f"{antes['clasificacion']} {antes['puntuacion']} → {r['clasificacion']} {r['puntuacion']}")
    return r


def cambiar_estado(con, id_lead: str, estado: str, notas: str, usuario: str):
    if estado not in ESTADOS:
        raise ValueError(f"Estado no válido: {estado}")
    fila = con.execute("SELECT estado FROM leads WHERE id_lead=?", (id_lead,)).fetchone()
    if not fila:
        raise KeyError(id_lead)
    con.execute("UPDATE leads SET estado=?, notas=?, actualizado=?, actualizado_por=? WHERE id_lead=?",
                (estado, notas.strip(), ahora(), usuario, id_lead))
    registrar(con, id_lead, usuario, "Seguimiento", f"{fila['estado']} → {estado}")


def borrar_lead(con, id_lead: str, usuario: str):
    if con.execute("DELETE FROM leads WHERE id_lead=?", (id_lead,)).rowcount == 0:
        raise KeyError(id_lead)
    registrar(con, id_lead, usuario, "Eliminado")


def listar(con) -> list[dict]:
    """Leads con la misma forma que usa capa3_salidas (resultado + analisis + seguimiento)."""
    out = []
    for f in con.execute("SELECT * FROM leads"):
        out.append({**json.loads(f["resultado"]), "analisis": config_rellenar(json.loads(f["analisis"])),
                    "estado": f["estado"], "notas": f["notas"], "actualizado": f["actualizado"],
                    "actualizado_por": f["actualizado_por"]})
    return out


def config_rellenar(valor):
    if isinstance(valor, str):
        return config.rellenar(valor)
    if isinstance(valor, list):
        return [config_rellenar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: config_rellenar(v) for k, v in valor.items()}
    return valor


def resumen_global(con) -> dict:
    fila = con.execute("SELECT valor FROM ajustes WHERE clave='resumen'").fetchone()
    return config_rellenar(json.loads(fila["valor"])) if fila else {}


def historial(con, id_lead: str) -> list[dict]:
    return [dict(f) for f in con.execute(
        "SELECT usuario, accion, detalle, fecha FROM historial WHERE id_lead=? ORDER BY id DESC LIMIT 20", (id_lead,))]


# ── carga inicial ─────────────────────────────────────────────────────────
def esta_vacia() -> bool:
    with conectar() as con:
        return con.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0


def cargar_datos_iniciales(csv=Path("datos/leads.csv"), analisis=Path("salidas/capa2_analisis.json")) -> int:
    """Carga los leads del proyecto con su análisis, conservando sus ID originales."""
    c2 = json.loads(analisis.read_text(encoding="utf-8")) if analisis.exists() else {}
    por_id = {a["id_lead"]: a for a in c2.get("leads", [])}
    filas = capa1_motor.leer_leads(csv)
    vistos: dict = {}
    with conectar() as con:
        for lead in filas:
            r = capa1_motor.evaluar(lead, vistos, fecha_ref())
            a = por_id.get(r["id_lead"]) or analisis_automatico(r)
            a.pop("id_lead", None)
            con.execute("INSERT INTO leads (id_lead, datos, resultado, analisis, actualizado, actualizado_por) "
                        "VALUES (?,?,?,?,?,?)",
                        (r["id_lead"], json.dumps(limpiar(lead), ensure_ascii=False),
                         json.dumps(r, ensure_ascii=False), json.dumps(a, ensure_ascii=False), ahora(), "carga inicial"))
            registrar(con, r["id_lead"], "carga inicial", "Alta", f"{r['clasificacion']} · {r['puntuacion']} puntos")
        resumen = {k: c2.get(k) for k in ["resumen_ejecutivo", "oportunidades_globales", "riesgos_globales"]}
        con.execute("INSERT OR REPLACE INTO ajustes (clave, valor) VALUES ('resumen', ?)",
                    (json.dumps(resumen, ensure_ascii=False),))
    return len(filas)
