"""
CAPA 3 · SALIDAS
  · Excel con 3 hojas: Resumen, Leads y Plan de acción
  · Informe comercial con estadísticas (Markdown)
  · CSV listo para importar en HubSpot CRM
  · Panel web accesible (HTML de un solo archivo)

Une la salida de la capa 1 con el análisis de la capa 2. Si todavía no
existe capa2_analisis.json, usa los motivos del motor como texto de
respaldo para que el proceso no se detenga.

Uso:  python capa3_salidas.py
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

from openpyxl import Workbook
from openpyxl.chart import BarChart, Reference
from openpyxl.formatting.rule import CellIsRule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.datavalidation import DataValidation

import config

SAL = Path("salidas")
CLASES = ["HOT", "WARM", "COLD", "REVISAR DATOS"]
# Colores con contraste AA (texto oscuro sobre fondo claro)
COLOR = {"HOT": "FBD9CF", "WARM": "FBE8BF", "COLD": "D3E5F5", "REVISAR DATOS": "E6E0F5"}
COLOR_TXT = {"HOT": "8A2A0A", "WARM": "6B4500", "COLD": "123F66", "REVISAR DATOS": "3D2C80"}
CABECERA = PatternFill("solid", fgColor="1F2937")
BORDE = Border(bottom=Side(style="thin", color="D1D5DB"))
QUE_HACER = {"HOT": "Contactar esta semana", "WARM": "Seguimiento con contenido de valor",
             "COLD": "Nurturing automático", "REVISAR DATOS": "Corregir datos antes de contactar"}


# ── carga y fusión ────────────────────────────────────────────────────────
def rellenar(valor):
    """Sustituye {empresa}, {producto} y {firma} en cualquier texto anidado."""
    if isinstance(valor, str):
        return config.rellenar(valor)
    if isinstance(valor, list):
        return [rellenar(v) for v in valor]
    if isinstance(valor, dict):
        return {k: rellenar(v) for k, v in valor.items()}
    return valor


def cargar():
    c1 = json.loads((SAL / "capa1_leads_puntuados.json").read_text(encoding="utf-8"))
    ruta2 = SAL / "capa2_analisis.json"
    c2 = rellenar(json.loads(ruta2.read_text(encoding="utf-8"))) if ruta2.exists() else {}
    analisis = {a["id_lead"]: a for a in c2.get("leads", [])}

    leads = []
    for l in c1["leads"]:
        a = analisis.get(l["id_lead"])
        if a is None:  # respaldo si falta la capa 2
            a = {"justificacion": "; ".join(l["motivos"]) or "Sin factores destacados",
                 "accion": QUE_HACER[l["clasificacion"]], "canal": "", "prioridad": "",
                 "plazo_accion": "", "fecha_limite": "", "oportunidades": [], "riesgos": [],
                 "correo": None, "_sin_analisis": True}
        leads.append({**l, "analisis": a})
    return c1["meta"], c2, leads


def num(v):
    try:
        return float(str(v).replace(",", "."))
    except (TypeError, ValueError):
        return None


def orden_plan(leads):
    return sorted(leads, key=lambda l: (l["analisis"].get("prioridad") or "P9",
                                        l["analisis"].get("fecha_limite") or "9999", -l["puntuacion"]))


# ── estadísticas ──────────────────────────────────────────────────────────
def estadisticas(leads):
    por_clase = {}
    for c in CLASES:
        g = [l for l in leads if l["clasificacion"] == c]
        pres = [p for p in (num(l["presupuesto_eur"]) for l in g) if p and p > 0]
        por_clase[c] = {
            "n": len(g),
            "pct": round(100 * len(g) / len(leads), 1) if leads else 0,
            "score_medio": round(sum(l["puntuacion"] for l in g) / len(g), 1) if g else 0,
            "presupuesto_total": sum(pres),
        }

    def agrupar(campo):
        res = {}
        for l in leads:
            r = res.setdefault(l.get(campo) or "Sin dato", {"n": 0, "hot": 0, "suma": 0})
            r["n"] += 1
            r["hot"] += l["clasificacion"] == "HOT"
            r["suma"] += l["puntuacion"]
        return {k: {**v, "score_medio": round(v["suma"] / v["n"], 1)} for k, v in
                sorted(res.items(), key=lambda kv: -kv[1]["suma"] / kv[1]["n"])}

    return {"conteo": dict(Counter(l["clasificacion"] for l in leads)), "por_clase": por_clase,
            "por_origen": agrupar("origen"), "por_sector": agrupar("sector"),
            "hot_ocultos": [l["id_lead"] for l in leads if l.get("potencial_si_se_corrige") == "HOT"],
            "score_medio": round(sum(l["puntuacion"] for l in leads) / len(leads), 1) if leads else 0}


# ── Excel (3 hojas) ───────────────────────────────────────────────────────
def hoja_tabla(ws, cabeceras, filas, anchos):
    ws.append(cabeceras)
    for c in ws[1]:
        c.font = Font(bold=True, color="FFFFFF", size=12)
        c.fill = CABECERA
        c.alignment = Alignment(vertical="center", wrap_text=True)
    ws.row_dimensions[1].height = 32
    for f in filas:
        ws.append(f)
    for i, w in enumerate(anchos, 1):
        ws.column_dimensions[get_column_letter(i)].width = w
    for fila in ws.iter_rows(min_row=2):
        for c in fila:
            c.font = Font(size=12)
            c.alignment = Alignment(vertical="top", wrap_text=True)
            c.border = BORDE
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions


def colorear_clase(ws, col, n):
    for c in CLASES:
        ws.conditional_formatting.add(f"{col}2:{col}{n + 1}", CellIsRule(
            operator="equal", formula=[f'"{c}"'],
            fill=PatternFill("solid", fgColor=COLOR[c]), font=Font(bold=True, color=COLOR_TXT[c])))


def generar_excel(meta, c2, leads, est, ruta):
    wb = Workbook()

    # Hoja 1 · Resumen
    ws = wb.active
    ws.title = "Resumen"
    ws["A1"] = "Resumen de leads"
    ws["A1"].font = Font(bold=True, size=18)
    ws["A2"] = f"{len(leads)} leads · fecha de referencia {meta['fecha_referencia']}"
    ws["A2"].font = Font(size=12, color="4B5563")
    ws.append([])
    ws.append(["Clase", "Leads", "% del total", "Presupuesto (€)", "Qué hacer"])
    for c in ws[4]:
        c.font = Font(bold=True, color="FFFFFF", size=12)
        c.fill = CABECERA
    for c in CLASES:
        p = est["por_clase"][c]
        ws.append([c, p["n"], p["pct"] / 100, p["presupuesto_total"], QUE_HACER[c]])
        r = ws.max_row
        for col in range(1, 6):
            ws.cell(r, col).font = Font(size=12)
        ws.cell(r, 1).fill = PatternFill("solid", fgColor=COLOR[c])
        ws.cell(r, 1).font = Font(bold=True, size=12, color=COLOR_TXT[c])
        ws.cell(r, 3).number_format = "0%"
        ws.cell(r, 4).number_format = '#,##0 "€"'
    ws.append(["TOTAL", "=SUM(B5:B8)", "=SUM(C5:C8)", "=SUM(D5:D8)", ""])
    for c in ws[9]:
        c.font = Font(bold=True, size=12)
    ws["C9"].number_format = "0%"
    ws["D9"].number_format = '#,##0 "€"'

    graf = BarChart()
    graf.title = "Leads por clase"
    graf.add_data(Reference(ws, min_col=2, min_row=4, max_row=8), titles_from_data=True)
    graf.set_categories(Reference(ws, min_col=1, min_row=5, max_row=8))
    graf.legend = None
    graf.height, graf.width = 7, 13
    ws.add_chart(graf, "A12")

    fila = 27
    bloques = [("Conclusión", [c2.get("resumen_ejecutivo") or "Pendiente del análisis de la capa 2."]),
               ("Oportunidades", c2.get("oportunidades_globales", [])),
               ("Riesgos", c2.get("riesgos_globales", []))]
    for titulo, contenido in bloques:
        ws.cell(fila, 1, titulo).font = Font(bold=True, size=14)
        fila += 1
        for t in contenido or ["Sin datos"]:
            ws.cell(fila, 1, t if titulo == "Conclusión" else f"- {t}").font = Font(size=12)
            ws.merge_cells(start_row=fila, start_column=1, end_row=fila, end_column=8)
            ws.cell(fila, 1).alignment = Alignment(wrap_text=True, vertical="top")
            ws.row_dimensions[fila].height = 96 if len(t) > 300 else 36
            fila += 1
        fila += 1
    for col, w in zip("ABCDE", [18, 9, 12, 17, 36]):
        ws.column_dimensions[col].width = w

    # Hoja 2 · Leads
    ws = wb.create_sheet("Leads")
    filas = [[l["id_lead"], l["empresa"], l["nombre_completo"], l["cargo"], l["sector"],
              num(l["presupuesto_eur"]), l["plazo_compra"], l["puntuacion"], l["clasificacion"],
              l.get("potencial_si_se_corrige") or "", "; ".join(l["errores"] + l["avisos"]),
              l["analisis"]["justificacion"]] for l in leads]
    hoja_tabla(ws, ["ID", "Empresa", "Contacto", "Cargo", "Sector", "Presupuesto (€)", "Plazo de compra",
                    "Puntuación (0-100)", "Clase", "Clase si se corrigen los datos", "Problemas en los datos",
                    "Por qué"],
               filas, [7, 26, 22, 22, 16, 14, 13, 12, 15, 15, 40, 70])
    colorear_clase(ws, "I", len(filas))
    colorear_clase(ws, "J", len(filas))
    for r in range(2, len(filas) + 2):
        ws.cell(r, 6).number_format = '#,##0 "€"'

    # Hoja 3 · Plan de acción
    ws = wb.create_sheet("Plan de acción")
    filas = []
    for l in orden_plan(leads):
        a, correo = l["analisis"], l["analisis"].get("correo") or {}
        filas.append([a.get("prioridad"), a.get("fecha_limite"), l["id_lead"], l["empresa"], l["clasificacion"],
                      a.get("canal"), a.get("accion"), l["email"], correo.get("asunto", ""),
                      correo.get("cuerpo", ""), l.get("estado") or "Pendiente"])
    hoja_tabla(ws, ["Prioridad", "Fecha límite", "ID", "Empresa", "Clase", "Canal", "Qué hacer",
                    "Email", "Asunto del correo", "Correo", "Estado"],
               filas, [10, 13, 7, 26, 15, 13, 46, 30, 36, 70, 13])
    colorear_clase(ws, "E", len(filas))
    for p, col in [("P1", "FBD9CF"), ("P2", "FBE8BF")]:
        ws.conditional_formatting.add(f"A2:A{len(filas) + 1}", CellIsRule(
            operator="equal", formula=[f'"{p}"'], fill=PatternFill("solid", fgColor=col), font=Font(bold=True)))
    dv = DataValidation(type="list", formula1='"Pendiente,En curso,Hecho,Descartado"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add(f"K2:K{len(filas) + 1}")

    wb.save(ruta)


# ── informe Markdown ──────────────────────────────────────────────────────
def generar_informe(meta, c2, leads, est, ruta):
    fmt = lambda x: f"{x:,.0f}".replace(",", ".")
    L = ["# Informe comercial de leads",
         f"Fecha de referencia: {meta['fecha_referencia']} · {len(leads)} leads · "
         f"puntuación media {str(est['score_medio']).replace('.', ',')}", "",
         "## Conclusión", c2.get("resumen_ejecutivo") or "Pendiente del análisis de la capa 2.", "",
         "## Reparto por clase", "| Clase | Leads | % | Puntuación media | Presupuesto declarado |",
         "|---|---:|---:|---:|---:|"]
    for c in CLASES:
        p = est["por_clase"][c]
        L.append(f"| {c} | {p['n']} | {str(p['pct']).replace('.', ',')} % | "
                 f"{str(p['score_medio']).replace('.', ',')} | {fmt(p['presupuesto_total'])} € |")
    L += ["", "## Prioridad P1", "| ID | Empresa | Puntuación | Qué hacer | Fecha límite |", "|---|---|---:|---|---|"]
    for l in orden_plan(leads):
        a = l["analisis"]
        if a.get("prioridad") == "P1":
            L.append(f"| {l['id_lead']} | {l['empresa']} | {l['puntuacion']} | {a['accion']} | {a['fecha_limite']} |")
    for titulo, campo in [("Rendimiento por origen", "por_origen"), ("Rendimiento por sector", "por_sector")]:
        L += ["", f"## {titulo}", "| Grupo | Leads | HOT | Puntuación media |", "|---|---:|---:|---:|"]
        for k, v in est[campo].items():
            L.append(f"| {k} | {v['n']} | {v['hot']} | {str(v['score_medio']).replace('.', ',')} |")
    errores = sum(len(l["errores"]) for l in leads)
    avisos = sum(len(l["avisos"]) for l in leads)
    L += ["", "## Calidad de datos",
          f"- {est['por_clase']['REVISAR DATOS']['n']} leads pendientes de revisión ({errores} errores y {avisos} avisos).",
          f"- Leads que serían HOT con los datos corregidos: {', '.join(est['hot_ocultos']) or 'ninguno'}."]
    L += ["", "## Oportunidades"] + [f"- {o}" for o in c2.get("oportunidades_globales", [])]
    L += ["", "## Riesgos"] + [f"- {r}" for r in c2.get("riesgos_globales", [])]
    ruta.write_text("\n".join(L) + "\n", encoding="utf-8")


# ── HubSpot ───────────────────────────────────────────────────────────────
LIFECYCLE = {"HOT": "salesqualifiedlead", "WARM": "marketingqualifiedlead", "COLD": "lead", "REVISAR DATOS": "lead"}
LEAD_STATUS = {"HOT": "IN_PROGRESS", "WARM": "OPEN", "COLD": "BAD_TIMING", "REVISAR DATOS": "NEW"}


def generar_hubspot(leads, ruta):
    """CSV con los nombres de columna que HubSpot reconoce al importar contactos.
    Las 4 últimas son propiedades personalizadas: créalas antes en HubSpot
    (Configuración > Propiedades) o asígnalas durante la importación."""
    excluidos = []
    with ruta.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["First Name", "Last Name", "Email", "Phone Number", "Company Name", "Job Title",
                    "Industry", "Country/Region", "City", "Lifecycle Stage", "Lead Status",
                    "lead_score", "clasificacion_lead", "proxima_accion", "fecha_limite_accion"])
        for l in leads:
            # HubSpot identifica los contactos por el email: sin email válido o duplicado no se importa
            if any(("email" in e.lower()) or ("duplicado" in e.lower()) for e in l["errores"]):
                excluidos.append(l["id_lead"])
                continue
            a = l["analisis"]
            w.writerow([l["nombre"], l["apellidos"], l["email"], l["telefono"], l["empresa"], l["cargo"],
                        l["sector"], l["pais"], l["ciudad"], LIFECYCLE[l["clasificacion"]],
                        LEAD_STATUS[l["clasificacion"]], l["puntuacion"], l["clasificacion"],
                        a.get("accion", ""), a.get("fecha_limite", "")])
    return excluidos


# ── panel web ─────────────────────────────────────────────────────────────
def generar_panel(meta, c2, leads, est, ruta_json):
    campos = ["id_lead", "nombre_completo", "email", "telefono", "empresa", "cargo", "sector", "empleados",
              "pais", "ciudad", "origen", "presupuesto_eur", "plazo_compra", "comentarios", "puntuacion",
              "clasificacion", "potencial_si_se_corrige", "dias_sin_contacto", "desglose", "errores",
              "avisos", "analisis"]
    datos = {"meta": {**meta, "empresa": config.EMPRESA},
             "resumen": {k: c2.get(k) for k in ["resumen_ejecutivo", "oportunidades_globales", "riesgos_globales"]},
             "estadisticas": est,
             "leads": [{k: l.get(k) for k in campos} for l in orden_plan(leads)]}
    ruta_json.write_text(json.dumps(datos, ensure_ascii=False), encoding="utf-8")
    plantilla = Path("plantillas/panel.html")
    if plantilla.exists():
        incrustado = json.dumps(datos, ensure_ascii=False).replace("</", "<\\/")
        html = plantilla.read_text(encoding="utf-8").replace("/*__DATOS__*/", incrustado)
        (ruta_json.parent / "panel_leads.html").write_text(html, encoding="utf-8")


def main():
    meta, c2, leads = cargar()
    sin_analisis = [l["id_lead"] for l in leads if l["analisis"].get("_sin_analisis")]
    est = estadisticas(leads)
    generar_excel(meta, c2, leads, est, SAL / "Leads_Plan_Comercial.xlsx")
    generar_informe(meta, c2, leads, est, SAL / "informe_comercial.md")
    excluidos = generar_hubspot(leads, SAL / "hubspot_import.csv")
    generar_panel(meta, c2, leads, est, SAL / "panel_datos.json")

    print("\nCAPA 3 · salidas generadas en", SAL)
    for f in ["Leads_Plan_Comercial.xlsx", "informe_comercial.md", "hubspot_import.csv", "panel_leads.html"]:
        print("   -", f)
    if sin_analisis:
        print(f"Aviso: {len(sin_analisis)} leads sin análisis de la capa 2: {', '.join(sin_analisis)}")
    print(f"No exportados a HubSpot (email inválido o duplicado): {', '.join(excluidos) or 'ninguno'}")


if __name__ == "__main__":
    main()
