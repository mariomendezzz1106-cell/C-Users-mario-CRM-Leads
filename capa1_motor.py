"""
CAPA 1 · MOTOR DETERMINISTA
  1. Lectura de datos (CSV o Excel)
  2. Validación: huecos, formatos e incoherencias
  3. Lead scoring con reglas ponderadas (ver reglas.py)
  4. Clasificación HOT / WARM / COLD / REVISAR DATOS

Uso:
    python capa1_motor.py --entrada datos/leads.csv --fecha-ref 2026-11-23

Salida: salidas/capa1_leads_puntuados.json  (entrada de la capa 2)
        salidas/capa1_leads_puntuados.csv   (vista rápida)
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
from datetime import date, datetime
from pathlib import Path

import pandas as pd

import reglas as R

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")


# ── utilidades ────────────────────────────────────────────────────────────
def norm(texto: str) -> str:
    """minúsculas y sin tildes, para comparar con las reglas"""
    texto = unicodedata.normalize("NFD", str(texto or "").strip().lower())
    return "".join(c for c in texto if unicodedata.category(c) != "Mn")


def a_numero(valor: str):
    valor = str(valor or "").strip().replace(" ", "")
    if not valor:
        return None
    try:
        return float(valor.replace(",", "."))
    except ValueError:
        return "invalido"


def a_fecha(valor: str):
    valor = str(valor or "").strip()
    if not valor:
        return None
    for fmt in ("%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(valor, fmt).date()
        except ValueError:
            pass
    return "invalida"


def contiene_clave(texto: str, claves: list[str]) -> bool:
    """Siglas cortas (CEO, COO...) como palabra completa; el resto como inicio de
    palabra, para que 'coordinadora' no cuente como 'COO'."""
    for k in claves:
        patron = rf"\b{re.escape(k)}\b" if len(k) <= 3 else rf"\b{re.escape(k)}"
        if re.search(patron, texto):
            return True
    return False


def por_tramos(valor, tramos):
    if not isinstance(valor, (int, float)):
        return 0
    for minimo, puntos in tramos:
        if valor >= minimo:
            return puntos
    return 0


# ── 1. lectura ────────────────────────────────────────────────────────────
def leer_leads(ruta: Path) -> list[dict]:
    if ruta.suffix.lower() in (".xlsx", ".xls"):
        df = pd.read_excel(ruta, dtype=str, keep_default_na=False)
    else:
        df = pd.read_csv(ruta, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    df.columns = [c.strip() for c in df.columns]
    return df.to_dict(orient="records")


# ── 2. validación ─────────────────────────────────────────────────────────
def validar(lead: dict, emails_vistos: dict, fecha_ref: date) -> tuple[list, list, dict]:
    errores, avisos, limpio = [], [], {}

    # Campos críticos vacíos
    for campo in R.CAMPOS_CRITICOS:
        if not str(lead.get(campo, "")).strip():
            errores.append(f"Campo crítico vacío: {campo}")

    # Email
    email = str(lead.get("email", "")).strip().lower()
    if email:
        if not EMAIL_RE.match(email):
            errores.append(f"Email con formato inválido ({email})")
        elif email in emails_vistos:
            errores.append(f"Lead duplicado (mismo email que {emails_vistos[email]})")
        else:
            emails_vistos[email] = lead["id_lead"]
            if email.split("@")[1] in R.DOMINIOS_GENERICOS:
                avisos.append("Email de dominio genérico (no corporativo)")

    # Números
    for campo in ["empleados", "presupuesto_eur", "visitas_web", "descargas", "emails_abiertos"]:
        v = a_numero(lead.get(campo))
        if v == "invalido":
            errores.append(f"Valor no numérico en {campo}")
            v = None
        limpio[campo] = v
    if isinstance(limpio["empleados"], float) and limpio["empleados"] <= 0:
        errores.append(f"Nº de empleados incoherente ({limpio['empleados']:.0f})")
    if isinstance(limpio["presupuesto_eur"], float) and limpio["presupuesto_eur"] < 0:
        errores.append(f"Presupuesto negativo ({limpio['presupuesto_eur']:.0f} €)")
    for campo in ["visitas_web", "descargas", "emails_abiertos"]:
        if isinstance(limpio[campo], float) and limpio[campo] < 0:
            errores.append(f"Valor negativo en {campo}")

    # Fechas
    alta, ultimo = a_fecha(lead.get("fecha_alta")), a_fecha(lead.get("ultimo_contacto"))
    for nombre, f in [("fecha_alta", alta), ("ultimo_contacto", ultimo)]:
        if f == "invalida":
            errores.append(f"Fecha con formato inválido en {nombre}")
        elif isinstance(f, date) and f > fecha_ref:
            errores.append(f"Fecha futura en {nombre} ({f.isoformat()})")
    if isinstance(alta, date) and isinstance(ultimo, date) and ultimo < alta:
        errores.append("Último contacto anterior a la fecha de alta")
    limpio["fecha_alta"] = alta if isinstance(alta, date) else None
    limpio["ultimo_contacto"] = ultimo if isinstance(ultimo, date) else None

    # Avisos (no bloquean por sí solos)
    tel = re.sub(r"\D", "", str(lead.get("telefono", "")))
    if not tel:
        avisos.append("Teléfono vacío")
    elif len(tel) < 9:
        avisos.append(f"Teléfono sospechoso ({lead.get('telefono')})")
    if not str(lead.get("cargo", "")).strip():
        avisos.append("Cargo vacío: no se puede valorar el poder de decisión")
    if not str(lead.get("plazo_compra", "")).strip():
        avisos.append("Plazo de compra vacío (se trata como 'Sin definir')")
    if norm(lead.get("demo_solicitada")) == "si" and limpio["visitas_web"] in (0, None):
        avisos.append("Incoherencia: solicitó demo pero no registra visitas web")
    emp, pres = limpio["empleados"], limpio["presupuesto_eur"]
    if isinstance(emp, float) and emp > 0 and isinstance(pres, float) and pres / emp > R.MAX_PRESUPUESTO_POR_EMPLEADO:
        avisos.append("Presupuesto desproporcionado para el tamaño de la empresa")

    return errores, avisos, limpio


# ── 3. scoring ────────────────────────────────────────────────────────────
def puntuar(lead: dict, limpio: dict, fecha_ref: date) -> dict:
    sector = norm(lead.get("sector"))
    if sector in R.SECTORES_OBJETIVO:
        p_sector = R.PUNTOS_SECTOR["objetivo"]
    elif sector in R.SECTORES_SECUNDARIOS:
        p_sector = R.PUNTOS_SECTOR["secundario"]
    else:
        p_sector = R.PUNTOS_SECTOR["otro"]

    cargo = norm(lead.get("cargo"))
    if cargo and contiene_clave(cargo, R.CARGOS_DECISORES):
        p_cargo, rol = R.PUNTOS_CARGO["decisor"], "decisor"
    elif cargo and contiene_clave(cargo, R.CARGOS_INFLUENCIADORES):
        p_cargo, rol = R.PUNTOS_CARGO["influenciador"], "influenciador"
    else:
        p_cargo, rol = (R.PUNTOS_CARGO["otro"] if cargo else 0), ("otro" if cargo else "desconocido")

    encaje = {
        "tamano": por_tramos(limpio["empleados"], R.TRAMOS_EMPLEADOS),
        "sector": p_sector,
        "cargo": p_cargo,
        "pais": R.PUNTOS_PAIS.get(norm(lead.get("pais")), R.PUNTOS_PAIS_OTRO),
    }
    intencion = {
        "plazo": R.PUNTOS_PLAZO.get(norm(lead.get("plazo_compra")) or "sin definir", 0),
        "presupuesto": por_tramos(limpio["presupuesto_eur"], R.TRAMOS_PRESUPUESTO),
        "demo": R.PUNTOS_DEMO if norm(lead.get("demo_solicitada")) == "si" else 0,
    }
    engagement = {
        "visitas": por_tramos(limpio["visitas_web"], R.TRAMOS_VISITAS),
        "descargas": por_tramos(limpio["descargas"], R.TRAMOS_DESCARGAS),
        "emails": por_tramos(limpio["emails_abiertos"], R.TRAMOS_EMAILS),
        "origen": R.PUNTOS_ORIGEN.get(norm(lead.get("origen")), 2),
    }

    dias = (fecha_ref - limpio["ultimo_contacto"]).days if limpio["ultimo_contacto"] else None
    recencia = 0
    if dias is not None and dias >= 0:
        for limite, pen in R.PENALIZACION_RECENCIA:
            if dias > limite:
                recencia = pen
                break

    total = sum(encaje.values()) + sum(intencion.values()) + sum(engagement.values()) + recencia
    return {
        "puntuacion": max(0, min(100, total)),
        "rol_decision": rol,
        "dias_sin_contacto": dias,
        "desglose": {
            "encaje": {**encaje, "total": sum(encaje.values()), "max": 40},
            "intencion": {**intencion, "total": sum(intencion.values()), "max": 35},
            "engagement": {**engagement, "total": sum(engagement.values()), "max": 25},
            "recencia": recencia,
        },
    }


def motivos_clave(lead: dict, s: dict, limpio: dict) -> list[str]:
    """Factores legibles que más pesan (contexto para la capa 2 y texto de respaldo)."""
    d, m = s["desglose"], []
    emp_ok = isinstance(limpio["empleados"], float) and limpio["empleados"] > 0
    pres_ok = isinstance(limpio["presupuesto_eur"], float) and limpio["presupuesto_eur"] >= 0
    if d["intencion"]["plazo"] >= 12:
        m.append(f"+ Plazo de compra corto ({lead.get('plazo_compra')})")
    if d["intencion"]["presupuesto"] >= 10:
        m.append(f"+ Presupuesto alto ({lead.get('presupuesto_eur')} €)")
    if d["intencion"]["demo"]:
        m.append("+ Ha solicitado demo")
    if s["rol_decision"] == "decisor":
        m.append(f"+ Interlocutor decisor ({lead.get('cargo')})")
    if d["encaje"]["sector"] == 10:
        m.append(f"+ Sector objetivo ({lead.get('sector')})")
    if d["engagement"]["total"] >= 18:
        m.append("+ Engagement digital alto")
    if d["intencion"]["plazo"] <= 3:
        m.append(f"- Sin urgencia de compra ({lead.get('plazo_compra') or 'sin definir'})")
    if pres_ok and d["intencion"]["presupuesto"] <= 1:
        m.append("- Presupuesto muy bajo o inexistente")
    if emp_ok and d["encaje"]["tamano"] <= 3:
        m.append("- Empresa muy pequeña")
    if d["encaje"]["sector"] == 2:
        m.append(f"- Sector fuera de objetivo ({lead.get('sector')})")
    if s["rol_decision"] in ("otro", "desconocido"):
        m.append("- Sin poder de decisión claro")
    if d["recencia"] < 0:
        m.append(f"- {s['dias_sin_contacto']} días sin contacto")
    return m


# ── 4. clasificación ──────────────────────────────────────────────────────
def clasificar(puntuacion: int, errores: list, avisos: list) -> str:
    if errores or len(avisos) >= R.MAX_AVISOS:
        return "REVISAR DATOS"
    if puntuacion >= R.UMBRAL_HOT:
        return "HOT"
    if puntuacion >= R.UMBRAL_WARM:
        return "WARM"
    return "COLD"


def categoria_teorica(puntuacion: int) -> str:
    return "HOT" if puntuacion >= R.UMBRAL_HOT else "WARM" if puntuacion >= R.UMBRAL_WARM else "COLD"


# ── pipeline ──────────────────────────────────────────────────────────────
def evaluar(lead: dict, emails_vistos: dict, fecha_ref: date) -> dict:
    """Valida, puntúa y clasifica UN lead. La usa el pipeline y también la plataforma web."""
    lead = {k: ("" if v is None else str(v)) for k, v in lead.items()}
    errores, avisos, limpio = validar(lead, emails_vistos, fecha_ref)
    s = puntuar(lead, limpio, fecha_ref)
    clase = clasificar(s["puntuacion"], errores, avisos)
    return {
        **{k: v.strip() for k, v in lead.items()},
        "nombre_completo": f"{lead.get('nombre', '').strip()} {lead.get('apellidos', '').strip()}".strip(),
        "puntuacion": s["puntuacion"],
        "clasificacion": clase,
        # Si está en revisión, ¿qué sería con datos corregidos? (score provisional)
        "potencial_si_se_corrige": categoria_teorica(s["puntuacion"]) if clase == "REVISAR DATOS" else None,
        "rol_decision": s["rol_decision"],
        "dias_sin_contacto": s["dias_sin_contacto"],
        "desglose": s["desglose"],
        "motivos": motivos_clave(lead, s, limpio),
        "errores": errores,
        "avisos": avisos,
    }


def ejecutar(entrada: Path, salida: Path, fecha_ref: date) -> list[dict]:
    leads = leer_leads(entrada)
    emails_vistos: dict = {}
    resultado = [evaluar(lead, emails_vistos, fecha_ref) for lead in leads]

    resultado.sort(key=lambda x: (x["clasificacion"] == "REVISAR DATOS", -x["puntuacion"]))
    salida.mkdir(parents=True, exist_ok=True)
    meta = {"fecha_referencia": fecha_ref.isoformat(), "fichero_origen": entrada.name,
            "umbrales": {"HOT": R.UMBRAL_HOT, "WARM": R.UMBRAL_WARM}, "total_leads": len(resultado)}
    (salida / "capa1_leads_puntuados.json").write_text(
        json.dumps({"meta": meta, "leads": resultado}, ensure_ascii=False, indent=2), encoding="utf-8")

    plano = pd.DataFrame([{
        "id_lead": r["id_lead"], "nombre": r["nombre_completo"], "empresa": r["empresa"],
        "puntuacion": r["puntuacion"], "clasificacion": r["clasificacion"],
        "encaje": r["desglose"]["encaje"]["total"], "intencion": r["desglose"]["intencion"]["total"],
        "engagement": r["desglose"]["engagement"]["total"], "recencia": r["desglose"]["recencia"],
        "incidencias": " | ".join(r["errores"] + r["avisos"]),
    } for r in resultado])
    plano.to_csv(salida / "capa1_leads_puntuados.csv", index=False, encoding="utf-8-sig")
    return resultado


def main():
    ap = argparse.ArgumentParser(description="Capa 1 · motor determinista de lead scoring")
    ap.add_argument("--entrada", default="datos/leads.csv")
    ap.add_argument("--salida", default="salidas")
    ap.add_argument("--fecha-ref", default=date.today().isoformat(),
                    help="Fecha 'hoy' para calcular recencia (AAAA-MM-DD)")
    args = ap.parse_args()

    res = ejecutar(Path(args.entrada), Path(args.salida), date.fromisoformat(args.fecha_ref))
    print(f"\nCAPA 1 · {len(res)} leads procesados (fecha ref. {args.fecha_ref})\n")
    for clase in ["HOT", "WARM", "COLD", "REVISAR DATOS"]:
        grupo = [r for r in res if r["clasificacion"] == clase]
        print(f"  {clase:<14} {len(grupo):>3}  " + ", ".join(f"{r['id_lead']}({r['puntuacion']})" for r in grupo))
    print(f"\nGuardado en {Path(args.salida) / 'capa1_leads_puntuados.json'}")


if __name__ == "__main__":
    main()
