"""
CAPA 2 · versión automatizada por API (opcional).

Hace lo mismo que el Project (capa2_ia/instrucciones_project.md) pero sin
copiar y pegar: envía los leads en lotes y guarda el resultado.

Requisitos:  pip install anthropic   y   ANTHROPIC_API_KEY en el entorno
Uso:         python capa2_api.py
"""
import json
import re
from pathlib import Path

import anthropic

import config

MODELO = "claude-opus-5-5"
TAM_LOTE = 15
ENTRADA = Path("salidas/capa1_leads_puntuados.json")
SALIDA = Path("salidas/capa2_analisis.json")
INSTRUCCIONES = Path("capa2_ia/instrucciones_project.md").read_text(encoding="utf-8")
CONTEXTO = (INSTRUCCIONES
            + "\n\n## Negocio\n" + config.DESCRIPCION_NEGOCIO
            + "\n\n## reglas.py\n```python\n" + Path("reglas.py").read_text(encoding="utf-8") + "\n```")


def extraer_json(texto: str) -> dict:
    m = re.search(r"\{.*\}", texto, re.S)
    if not m:
        raise ValueError("La respuesta no contiene JSON")
    return json.loads(m.group(0))


def analizar_lote(client, meta, lote):
    with client.beta.messages.stream(
        model=MODELO,
        max_tokens=64000,
        output_config={"effort": "high"},
        # Si el modelo rechaza la petición, la API la reintenta con otro modelo
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=[{"type": "text", "text": CONTEXTO, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content":
                   "Salida de la capa 1:\n```json\n"
                   + json.dumps({"meta": meta, "leads": lote}, ensure_ascii=False)
                   + "\n```\nDevuelve solo el JSON pedido, con una entrada por lead."}],
    ) as stream:
        resp = stream.get_final_message()
    if resp.stop_reason == "refusal":
        raise RuntimeError(f"Petición rechazada: {resp.stop_details}")
    texto = "".join(b.text for b in resp.content if b.type == "text")
    return extraer_json(texto)


def main():
    datos = json.loads(ENTRADA.read_text(encoding="utf-8"))
    client = anthropic.Anthropic()
    leads = datos["leads"]
    resultado = {"resumen_ejecutivo": "", "oportunidades_globales": [], "riesgos_globales": [], "leads": []}
    for i in range(0, len(leads), TAM_LOTE):
        lote = leads[i:i + TAM_LOTE]
        print(f"Analizando leads {i + 1} a {i + len(lote)}...")
        parcial = analizar_lote(client, datos["meta"], lote)
        resultado["leads"] += parcial.get("leads", [])
        resultado["oportunidades_globales"] += parcial.get("oportunidades_globales", [])
        resultado["riesgos_globales"] += parcial.get("riesgos_globales", [])
        resultado["resumen_ejecutivo"] = (resultado["resumen_ejecutivo"] + " "
                                          + parcial.get("resumen_ejecutivo", "")).strip()

    faltan = {l["id_lead"] for l in leads} - {a["id_lead"] for a in resultado["leads"]}
    if faltan:
        print(f"Aviso: faltan análisis para {sorted(faltan)}")
    SALIDA.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Guardado en {SALIDA}")


if __name__ == "__main__":
    main()
