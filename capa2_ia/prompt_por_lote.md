# Mensaje para el chat del Project

Adjunta `salidas/capa1_leads_puntuados.json` y escribe:

---

Aquí tienes la salida de la capa 1. La fecha de referencia está en `meta.fecha_referencia`.
Analiza todos los leads siguiendo las instrucciones del Project y devuélveme solo el JSON.

Antes de terminar, comprueba que:
- hay una entrada por cada `id_lead` del fichero;
- no has cambiado ninguna puntuación ni clasificación;
- cada `fecha_limite` es la fecha de referencia más el `plazo_accion`;
- los leads sin email válido o duplicados tienen `"correo": null`;
- los correos terminan con `{firma}`.

---

Si hay más de unos 40 leads, envíalos en lotes de 20 y une los arrays `leads`.
Para automatizarlo está `capa2_api.py`, que necesita una API key.
