/* CRM de Leads · frontend.
   Reutiliza la lógica del panel original (resumen por clase, tabla de leads, ficha, alta, importación)
   y añade las secciones Dashboard, Clientes, Embudo, Oportunidades, Tareas, IA, Informes y Ajustes.
   Todo se lee y se guarda en la API (/api/...); no hay datos en el navegador. */
'use strict';

/* ── utilidades ──────────────────────────────────────────────────────── */
const $ = s => document.querySelector(s);
const $$ = s => [...document.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const eur = n => (Number(n)||0).toLocaleString('es-ES',{maximumFractionDigits:0}) + ' €';
const fecha = s => s ? new Date(String(s).slice(0,10)+'T12:00').toLocaleDateString('es-ES',{day:'numeric',month:'long'}) : 'Sin fecha';
const fechaHora = s => s ? new Date(s).toLocaleString('es-ES',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit'}) : '';
const CLASES = ['HOT','WARM','COLD','REVISAR DATOS'];
const COLOR = {'HOT':'var(--hot)','WARM':'var(--warm)','COLD':'var(--cold)','REVISAR DATOS':'var(--rev)'};
const NOMBRE = {'HOT':'HOT','WARM':'WARM','COLD':'COLD','REVISAR DATOS':'Revisar datos'};
const QUE = {'HOT':'Contactar esta semana','WARM':'Seguimiento con contenido de valor','COLD':'Nurturing automático','REVISAR DATOS':'Corregir datos antes de contactar'};
const PRIO = {'P1':'P1 · Urgente','P2':'P2 · Alta','P3':'P3 · Media','P4':'P4 · Baja'};
const ROL = {lectura:'Solo lectura', comercial:'Comercial', admin:'Administrador', propietario:'Propietario'};
const COLOR_ETAPA = {'Ganado':'var(--ok)','Perdido':'var(--hot)'};
let D = null;          // datos generales de /api/datos
let CSRF = '';

const puede = () => D && D.usuario.rol !== 'lectura';
const esAdmin = () => D && ['admin','propietario'].includes(D.usuario.rol);

class ErrorApi extends Error { constructor(m, errores){ super(m); this.errores = errores || {}; } }

async function api(metodo, url, cuerpo){
  const opciones = {method: metodo, headers: {'X-CRM':'1', 'X-CSRF-Token': CSRF}, credentials: 'same-origin'};
  if (cuerpo instanceof FormData) opciones.body = cuerpo;
  else if (cuerpo !== undefined) { opciones.headers['Content-Type'] = 'application/json'; opciones.body = JSON.stringify(cuerpo); }
  let r;
  try { r = await fetch(url, opciones); }
  catch(e) { throw new ErrorApi('No hay conexión con el servidor. Comprueba tu conexión e inténtalo de nuevo.'); }
  if (r.status === 401) { location.href = '/login'; throw new ErrorApi('Sesión caducada'); }
  const datos = await r.json().catch(() => ({}));
  if (!r.ok) throw new ErrorApi(datos.error || 'No se ha podido completar la operación.', datos.errores);
  return datos;
}
function avisar(t){ const el = $('#toast'); el.textContent = t; el.hidden = false; clearTimeout(avisar.t); avisar.t = setTimeout(() => el.hidden = true, 3200); }
const vista = () => $('#vista');
function opcionesHTML(lista, valor, vacio='Sin dato'){
  return [['', vacio], ...lista.map(o => Array.isArray(o) ? o : [o, o])]
    .map(([v,t]) => `<option value="${esc(v)}" ${String(v)===String(valor ?? '')?'selected':''}>${esc(t)}</option>`).join('');
}
const usuariosOps = () => D.opciones.usuarios.map(u => [u.id, u.nombre]);
let _clientes = null;
async function clientesOps(forzar){ if (!_clientes || forzar) _clientes = await api('GET','/api/clientes'); return _clientes.map(c => [c.id, c.nombre]); }

/* doble clic para borrar (como en el panel original) */
function confirmarBorrado(boton, accion){
  boton.onclick = async () => {
    if (boton.dataset.confirmar !== '1') { boton.dataset.confirmar = '1'; boton.textContent = 'Pulsa otra vez para eliminar'; return; }
    boton.disabled = true;
    try { await accion(); } catch(e) { avisar(e.message); boton.disabled = false; }
  };
}

/* ── formulario genérico en diálogo ──────────────────────────────────── */
const dlgForm = $('#dlg-form');
function formulario({titulo, campos, valores = {}, enviar, nota = '', borrar = null, textoEnviar = 'Guardar'}){
  const control = c => {
    const [id, , tipo, extra = {}] = c, v = valores[id] ?? '';
    const req = extra.obligatorio ? 'required' : '';
    if (tipo === 'select') return `<select id="f-${id}" name="${id}" ${req}>${opcionesHTML(extra.opciones, v, extra.vacio || 'Sin dato')}</select>`;
    if (tipo === 'area') return `<textarea id="f-${id}" name="${id}">${esc(v)}</textarea>`;
    const t = tipo === 'number' ? 'text' : tipo;
    return `<input id="f-${id}" name="${id}" type="${t}" value="${esc(v)}" ${tipo==='number'?'inputmode="decimal"':''} ${req}>`;
  };
  $('#form').innerHTML = `
    <header><h2 id="f-tit">${esc(titulo)}</h2><button type="button" class="btn" data-cerrar>Cerrar</button></header>
    ${nota ? `<p class="muted">${nota}</p>` : ''}
    <div class="form">${campos.map(c => `<label class="${c[2]==='area'||c[3]?.ancho?'ancho':''}" for="f-${c[0]}">${esc(c[1])}${c[3]?.obligatorio?' (obligatorio)':''}${control(c)}<span class="msg err" id="e-${c[0]}"></span></label>`).join('')}</div>
    <p class="msg" id="f-msg" role="status" aria-live="polite"></p>
    <div class="acciones">${borrar ? '<button type="button" class="btn peligro" id="f-borrar">Eliminar</button>' : ''}<button type="submit" class="btn prim">${esc(textoEnviar)}</button></div>`;
  $('#form').onsubmit = async e => {
    e.preventDefault();
    $$('#form .msg.err').forEach(x => x.textContent = '');
    const datos = Object.fromEntries(new FormData($('#form')).entries());
    const falta = campos.find(c => c[3]?.obligatorio && !String(datos[c[0]] || '').trim());
    const msg = $('#f-msg');
    if (falta) { msg.className = 'msg err'; msg.textContent = `Rellena «${falta[1]}».`; $(`#f-${falta[0]}`).focus(); return; }
    msg.className = 'msg'; msg.textContent = 'Guardando…';
    try { await enviar(datos); dlgForm.close(); }
    catch(err) {
      msg.className = 'msg err'; msg.textContent = err.message;
      Object.entries(err.errores || {}).forEach(([k, t]) => { const el = $(`#e-${k}`); if (el) el.textContent = t; });
    }
  };
  if (borrar) confirmarBorrado($('#f-borrar'), async () => { await borrar(); dlgForm.close(); });
  if (!dlgForm.open) dlgForm.showModal();
  const primero = $('#form input, #form select'); if (primero) primero.focus();
}

/* ── ficha en diálogo ────────────────────────────────────────────────── */
const dlg = $('#dlg');
let origenFoco = null;
function abrirFicha(html, boton){
  if (boton) origenFoco = boton;
  $('#ficha').innerHTML = html;
  const c = $('#ficha [data-cerrar]'); if (c) c.focus();
  if (!dlg.open) { dlg.showModal(); dlg.scrollTop = 0; }
}
dlg.addEventListener('close', () => { if (origenFoco && document.contains(origenFoco)) origenFoco.focus(); });
document.addEventListener('click', e => { const b = e.target.closest('[data-cerrar]'); if (b) b.closest('dialog').close(); });
[dlg, dlgForm].forEach(d => d.addEventListener('click', e => { if (e.target === d) d.close(); }));

/* ── arranque y navegación ───────────────────────────────────────────── */
async function cargarDatos(){
  D = await api('GET', '/api/datos');
  CSRF = D.csrf; $('#csrf-salir').value = CSRF;
  $('#sub').textContent = `${D.meta.empresa} · ${D.meta.total_leads} leads`;
  $('#quien').textContent = `${D.usuario.nombre} (${ROL[D.usuario.rol]})`;
}
const VISTAS = {dashboard: vDashboard, leads: vLeads, clientes: vClientes, embudo: vEmbudo, oportunidades: vOportunidades,
                tareas: vTareas, ia: vIA, informes: vInformes, ajustes: vAjustes};
async function navegar(){
  let nombre = location.hash.slice(1);
  if (!VISTAS[nombre]) nombre = 'dashboard';
  $$('nav.secciones a').forEach(a => { if (a.getAttribute('href') === '#'+nombre) a.setAttribute('aria-current','page'); else a.removeAttribute('aria-current'); });
  if (dlg.open) dlg.close();
  if (dlgForm.open) dlgForm.close();
  vista().innerHTML = '<p class="cargando">Cargando…</p>';
  try { await VISTAS[nombre](); }
  catch(e) { vista().innerHTML = `<p class="msg err">${esc(e.message)}</p>`; }
  document.title = `${$('nav.secciones a[aria-current]')?.textContent || 'CRM'} · CRM de Leads`;
}
window.addEventListener('hashchange', navegar);
const recargarVista = () => navegar();

/* ════════ DASHBOARD ════════ */
async function vDashboard(){
  const d = await api('GET', '/api/dashboard');
  const o = d.oportunidades, t = d.tareas, maxV = Math.max(1, ...o.por_etapa.map(e => e.valor));
  vista().innerHTML = `
    <h2>Dashboard comercial</h2>
    <section class="kpis" aria-label="Indicadores">
      <div class="kpi ${d.leads.hot_pendientes?'alerta':''}"><span class="l">Leads HOT sin atender</span><span class="v num">${d.leads.hot_pendientes}</span><span class="d">de ${d.leads.total} leads en total</span></div>
      <div class="kpi"><span class="l">Embudo abierto</span><span class="v num">${eur(o.valor_abierto)}</span><span class="d">${o.abiertas} oportunidades</span></div>
      <div class="kpi"><span class="l">Previsión ponderada</span><span class="v num">${eur(o.ponderado)}</span><span class="d">importe × probabilidad</span></div>
      <div class="kpi"><span class="l">Ganado</span><span class="v num">${eur(o.valor_ganado)}</span><span class="d">${o.ganadas} ganadas · ${o.perdidas} perdidas${o.tasa_cierre!==null?` · ${o.tasa_cierre.toLocaleString('es-ES')} % de cierre`:''}</span></div>
      <div class="kpi ${t.vencidas?'alerta':''}"><span class="l">Tareas vencidas</span><span class="v num">${t.vencidas}</span><span class="d">${t.hoy} para hoy · ${t.pendientes} abiertas</span></div>
    </section>
    <section aria-labelledby="t-cl">
      <h3 id="t-cl" style="margin-bottom:10px">Leads por clase</h3>
      <div class="resumen">${CLASES.map(c => `<a class="clase" style="--c:${COLOR[c]};text-decoration:none" href="#leads" data-clase="${c}">
        <span class="nombre">${NOMBRE[c]}</span><span class="n num">${d.leads.por_clase[c]}</span><span class="que">${QUE[c]}</span></a>`).join('')}</div>
    </section>
    <div class="dos">
      <section class="caja" aria-labelledby="t-emb"><h3 id="t-emb">Embudo por etapa</h3>
        <div class="embudo-barras">${o.por_etapa.map(e => `<div class="eb ${e.etapa==='Ganado'?'ganado':e.etapa==='Perdido'?'perdido':''}">
          <span>${esc(e.etapa)}</span><span class="b" aria-hidden="true"><span style="width:${100*e.valor/maxV}%"></span></span>
          <span class="num">${e.n} · ${eur(e.valor)}</span></div>`).join('')}</div>
        <a href="#embudo">Abrir el embudo</a></section>
      <section class="caja" aria-labelledby="t-tar"><h3 id="t-tar">Próximas tareas</h3>
        ${t.proximas.length ? `<ul class="lista">${t.proximas.map(x => `<li><span><span class="t">${esc(x.titulo)}</span><span class="s">${esc(x.asignado)}${x.cliente?' · '+esc(x.cliente):''}</span></span>
          <span class="num ${x.vencida?'vencida':'muted'}">${x.vence?fecha(x.vence):'Sin fecha'}</span></li>`).join('')}</ul>` : '<p class="muted">No hay tareas abiertas.</p>'}
        <a href="#tareas">Ver todas las tareas</a></section>
      <section class="caja" aria-labelledby="t-cie"><h3 id="t-cie">Próximos cierres</h3>
        ${d.proximos_cierres.length ? `<ul class="lista">${d.proximos_cierres.map(x => `<li><span><span class="t">${esc(x.titulo)}</span><span class="s">${esc(x.etapa)} · ${x.probabilidad} %</span></span>
          <span class="num">${eur(x.importe)}<br><span class="s">${x.fecha_cierre?fecha(x.fecha_cierre):'Sin fecha'}</span></span></li>`).join('')}</ul>` : '<p class="muted">No hay oportunidades abiertas.</p>'}</section>
      <section class="caja" aria-labelledby="t-act"><h3 id="t-act">Actividad reciente</h3>
        ${d.actividad.length ? `<ul class="lista">${d.actividad.map(x => `<li><span><span class="t">${esc(x.accion)} · ${esc(x.entidad)}</span><span class="s">${esc(x.detalle)}</span></span>
          <span class="s">${esc(x.usuario)}<br>${fechaHora(x.fecha)}</span></li>`).join('')}</ul>` : '<p class="muted">Sin movimientos todavía.</p>'}</section>
    </div>`;
  $$('[data-clase]').forEach(a => a.onclick = () => { estadoLeads.filtro = a.dataset.clase; });
}

/* ════════ LEADS (panel original) ════════ */
const estadoLeads = {filtro: null, texto: ''};
async function vLeads(){
  await cargarDatos();
  vista().innerHTML = `
    <div class="cab"><h2>Leads</h2>
      <div class="acciones">${puede()?`<button type="button" class="btn prim" id="b-nuevo">Añadir lead</button>
        <button type="button" class="btn" id="b-importar">Importar CSV o Excel</button>`:''}</div></div>
    <section aria-labelledby="t-resumen"><h3 id="t-resumen" style="margin-bottom:12px">Resumen por clase</h3><div class="resumen" id="resumen"></div></section>
    <section class="caja" aria-labelledby="t-concl"><h3 id="t-concl">Conclusión</h3><div id="concl-cuerpo" style="display:grid;gap:12px"></div></section>
    <section aria-labelledby="t-leads" style="display:grid;gap:14px">
      <h3 id="t-leads">Leads por prioridad</h3>
      <div class="barra"><div class="campo"><label for="q">Buscar por empresa, contacto o sector</label><input id="q" type="search" autocomplete="off" value="${esc(estadoLeads.texto)}"></div>
        <button class="btn" id="todos" type="button">Ver todos</button></div>
      <p id="estado" class="estado" role="status" aria-live="polite"></p>
      <div class="tabla"><table><caption>Ordenados por prioridad y fecha límite. Pulsa «Ver ficha» para ver el detalle y el correo.</caption>
        <thead><tr><th scope="col">Prioridad</th><th scope="col">Empresa</th><th scope="col">Puntuación</th><th scope="col">Clase</th><th scope="col">Estado</th><th scope="col">Fecha límite</th><th scope="col">Qué hacer</th><th scope="col"><span class="muted">Detalle</span></th></tr></thead>
        <tbody id="tbody"></tbody></table></div>
    </section>`;
  pintarConclusion();
  refrescarLeads();
  $('#q').oninput = e => { estadoLeads.texto = e.target.value.trim().toLowerCase(); pintarTablaLeads(); };
  $('#todos').onclick = () => { estadoLeads.filtro = null; estadoLeads.texto = ''; $('#q').value = ''; refrescarLeads(); };
  if (puede()) { $('#b-nuevo').onclick = () => formularioLead(null); $('#b-importar').onclick = abrirImportar; }
}
function refrescarLeads(){ pintarResumen(); pintarTablaLeads(); }
function pintarResumen(){
  const E = D.estadisticas.por_clase, f = estadoLeads.filtro;
  $('#resumen').innerHTML = CLASES.map(c => `
    <button type="button" class="clase" style="--c:${COLOR[c]}" data-c="${c}" aria-pressed="${f===c}"
      aria-label="${NOMBRE[c]}: ${E[c].n} leads. ${QUE[c]}. ${f===c?'Filtro activo, pulsa para quitarlo':'Pulsa para ver solo estos leads'}">
      <span class="nombre">${NOMBRE[c]}</span><span class="n num">${E[c].n}</span><span class="que">${QUE[c]}</span>
      ${f===c?'<span class="sel">Mostrando solo estos</span>':''}</button>`).join('');
  $$('.clase[data-c]').forEach(b => b.onclick = () => { estadoLeads.filtro = estadoLeads.filtro===b.dataset.c ? null : b.dataset.c; refrescarLeads(); });
}
function pintarConclusion(){
  const R = D.resumen || {}, caja = $('#concl-cuerpo');
  if (!R.resumen_ejecutivo) { caja.innerHTML = `<p class="muted">Todavía no hay conclusión de la cartera. ${D.ia.configurada?'Puedes generarla en <a href="#ia">Inteligencia artificial</a>.':'Se genera con la IA cuando esté configurada.'}</p>`; return; }
  caja.innerHTML = `<p>${esc(R.resumen_ejecutivo)}</p>${R.ia?`<p class="ia-sello">Generado con IA · ${fechaHora(R.generado)}</p>`:''}
    <details><summary>Oportunidades y riesgos</summary>
      <h3 style="margin-top:12px">Oportunidades</h3><ul>${(R.oportunidades_globales||[]).map(o=>`<li>${esc(o)}</li>`).join('')}</ul>
      <h3 style="margin-top:12px">Riesgos</h3><ul>${(R.riesgos_globales||[]).map(o=>`<li>${esc(o)}</li>`).join('')}</ul></details>`;
}
function pintarTablaLeads(){
  const L = D.leads, {filtro, texto} = estadoLeads;
  const vis = L.filter(l => (!filtro || l.clasificacion===filtro) &&
    (!texto || [l.empresa,l.nombre_completo,l.sector,l.id_lead].join(' ').toLowerCase().includes(texto)));
  $('#estado').textContent = `Mostrando ${vis.length} de ${L.length} leads` + (filtro ? ` (${NOMBRE[filtro]})` : '') + (texto ? ` que contienen «${texto}»` : '') + '.';
  $('#tbody').innerHTML = vis.length ? vis.map(l => {
    const a = l.analisis, rev = l.clasificacion==='REVISAR DATOS';
    return `<tr>
      <td data-label="Prioridad"><span class="prio">${esc(PRIO[a.prioridad]||'Sin prioridad')}</span></td>
      <td data-label="Empresa"><span><span class="emp">${esc(l.empresa)}</span><span class="sub">${esc(l.nombre_completo)} · ${esc(l.sector)}</span></span></td>
      <td data-label="Puntuación"><span class="num"><b>${l.puntuacion}</b> <span class="sub">de 100</span></span></td>
      <td data-label="Clase"><span><span class="etq" style="--c:${COLOR[l.clasificacion]}">${NOMBRE[l.clasificacion]}</span>${rev&&l.potencial_si_se_corrige?`<span class="sub" style="display:block">Sería ${l.potencial_si_se_corrige} con datos corregidos</span>`:''}</span></td>
      <td data-label="Estado">${esc(l.estado||'Pendiente')}${l.oportunidad_id?'<span class="sub" style="display:block">Con oportunidad</span>':''}</td>
      <td data-label="Fecha límite" class="num">${fecha(a.fecha_limite)}</td>
      <td data-label="Qué hacer">${esc(a.accion)}</td>
      <td data-label="Detalle"><button type="button" class="btn" data-id="${esc(l.id_lead)}" aria-label="Ver ficha de ${esc(l.empresa)}">Ver ficha</button></td></tr>`;
  }).join('') : '<tr><td colspan="8" class="vacio">Ningún lead coincide. Pulsa «Ver todos» o cambia la búsqueda.</td></tr>';
  $$('#tbody button[data-id]').forEach(b => b.onclick = () => abrirLead(b.dataset.id, b));
}
function abrirLead(id, boton){
  const l = D.leads.find(x => x.id_lead===id); if (!l) return;
  const a = l.analisis, d = l.desglose, rev = l.clasificacion==='REVISAR DATOS';
  const fila = (nom, b) => `<div class="fila"><span>${nom}</span><span class="b" aria-hidden="true"><span style="width:${100*b.total/b.max}%"></span></span><span class="num">${b.total} de ${b.max}</span></div>`;
  abrirFicha(`
    <header><div><h2 id="d-tit">${esc(l.empresa)}</h2><p class="muted">${esc(l.nombre_completo)} · ${esc(l.cargo||'Cargo desconocido')} · ${esc(l.id_lead)}</p></div>
      <button type="button" class="btn" data-cerrar>Cerrar</button></header>
    <div class="nota"><span class="grande num">${l.puntuacion}</span><span class="muted">de 100</span>
      <span class="etq" style="--c:${COLOR[l.clasificacion]}">${NOMBRE[l.clasificacion]}</span>
      ${rev&&l.potencial_si_se_corrige?`<span>Sería <b>${l.potencial_si_se_corrige}</b> con los datos corregidos</span>`:''}</div>
    ${puede()?`<div class="acciones" style="justify-content:flex-start">
      ${D.ia.configurada?'<button type="button" class="btn prim" id="b-ia">Analizar con IA</button>':''}
      ${l.oportunidad_id?'<a class="btn" href="#oportunidades">Ver oportunidad</a>':'<button type="button" class="btn" id="b-convertir">Convertir en oportunidad</button>'}
      <button type="button" class="btn" id="b-tarea">Crear tarea</button></div><p class="msg" id="l-msg" role="status" aria-live="polite"></p>`:''}
    ${puede()?`<section class="seguimiento" aria-labelledby="s-tit"><h3 id="s-tit">Seguimiento</h3>
      <label>Estado<select id="s-estado">${D.opciones.estados.map(e=>`<option ${e===(l.estado||'Pendiente')?'selected':''}>${esc(e)}</option>`).join('')}</select></label>
      <label>Notas<textarea id="s-notas">${esc(l.notas||'')}</textarea></label>
      <div class="acciones"><span class="msg" id="s-msg" role="status" aria-live="polite"></span><button type="button" class="btn prim" id="s-guardar">Guardar seguimiento</button></div>
      ${l.actualizado?`<p class="historial">Última modificación: ${fechaHora(l.actualizado)} por ${esc(l.actualizado_por||'')}</p>`:''}</section>`
      :`<p><b>Estado:</b> ${esc(l.estado)}${l.notas?` · ${esc(l.notas)}`:''}</p>`}
    ${(l.errores.length||l.avisos.length)?`<div class="aviso"><h3>Problemas en los datos</h3><ul>${l.errores.map(e=>`<li><b>Error:</b> ${esc(e)}</li>`).join('')}${l.avisos.map(e=>`<li>Aviso: ${esc(e)}</li>`).join('')}</ul></div>`:''}
    <section><h3>Qué hacer</h3><p>${esc(a.accion)}</p>
      <p class="muted">${esc(PRIO[a.prioridad]||'')}${a.canal?' · '+esc(a.canal):''}${a.fecha_limite?' · antes del '+fecha(a.fecha_limite):''}</p></section>
    <section><h3>Por qué</h3><p>${esc(a.justificacion)}</p>
      ${a.automatico?'<p class="muted" style="margin-top:4px">Texto generado por el motor de reglas. Este lead aún no tiene análisis detallado.</p>':''}
      ${a.ia?`<p class="ia-sello" style="margin-top:4px">Análisis generado con IA · ${fechaHora(a.generado)}</p>`:''}</section>
    <section class="desglose" aria-label="Desglose de la puntuación"><h3>De dónde sale la puntuación</h3>
      ${fila('Encaje',d.encaje)}${fila('Intención de compra',d.intencion)}${fila('Interacción',d.engagement)}
      <div class="fila"><span>Contacto reciente</span><span class="muted" style="font-size:.9rem">${l.dias_sin_contacto ?? 'Sin dato'} días sin contacto</span><span class="num">${d.recencia}</span></div></section>
    ${a.oportunidades?.length?`<section><h3>Oportunidades</h3><ul>${a.oportunidades.map(o=>`<li>${esc(o)}</li>`).join('')}</ul></section>`:''}
    ${a.riesgos?.length?`<section><h3>Riesgos</h3><ul>${a.riesgos.map(o=>`<li>${esc(o)}</li>`).join('')}</ul></section>`:''}
    ${a.correo?`<section><h3>Correo propuesto</h3><div class="correo"><div class="asunto">${esc(a.correo.asunto)}</div><pre id="cuerpo">${esc(a.correo.cuerpo)}</pre>
      <div class="pie"><span class="muted" style="overflow-wrap:anywhere">Para: ${esc(l.email)}</span>
      <span><span id="copiado" role="status" aria-live="polite" class="muted"></span> <button type="button" class="btn prim" id="copiar">Copiar correo</button></span></div></div></section>`
      :`<section><h3>Correo</h3><p class="muted">${a.automatico?'Sin correo propuesto para este lead.':'No hay correo: primero hay que corregir los datos de contacto.'}</p></section>`}
    <dl class="datos">
      <div><dt>Presupuesto</dt><dd class="num">${l.presupuesto_eur?eur(l.presupuesto_eur):'Sin dato'}</dd></div>
      <div><dt>Plazo de compra</dt><dd>${esc(l.plazo_compra||'Sin dato')}</dd></div>
      <div><dt>Empleados</dt><dd class="num">${esc(l.empleados||'Sin dato')}</dd></div>
      <div><dt>Origen</dt><dd>${esc(l.origen||'Sin dato')}</dd></div>
      <div><dt>Teléfono</dt><dd class="num">${esc(l.telefono||'Sin dato')}</dd></div>
      <div><dt>Ubicación</dt><dd>${esc([l.ciudad,l.pais].filter(Boolean).join(', ')||'Sin dato')}</dd></div>
      ${l.comentarios?`<div style="grid-column:1/-1"><dt>Comentarios</dt><dd>${esc(l.comentarios)}</dd></div>`:''}</dl>
    <section><h3>Historial</h3><ul class="historial" id="hist"><li>Cargando…</li></ul></section>
    ${puede()?'<div class="acciones"><button type="button" class="btn peligro" id="b-borrar">Eliminar lead</button><button type="button" class="btn" id="b-editar">Editar datos</button></div>':''}`, boton);

  const cp = $('#copiar');
  if (cp) cp.onclick = () => {
    const txt = `Asunto: ${a.correo.asunto}\n\n${a.correo.cuerpo}`;
    const manual = () => { const r = document.createRange(); r.selectNodeContents($('#cuerpo')); const s = getSelection(); s.removeAllRanges(); s.addRange(r); $('#copiado').textContent = 'Texto seleccionado: pulsa Ctrl+C para copiarlo.'; };
    try { navigator.clipboard.writeText(txt).then(() => $('#copiado').textContent = 'Correo copiado.', manual); } catch(e) { manual(); }
  };
  api('GET', `/api/leads/${encodeURIComponent(l.id_lead)}/historial`).then(h => {
    $('#hist').innerHTML = h.length ? h.map(x => `<li>${fechaHora(x.fecha)} · ${esc(x.usuario)} · ${esc(x.accion)}${x.detalle?': '+esc(x.detalle):''}</li>`).join('') : '<li>Sin movimientos.</li>';
  }).catch(() => { $('#hist').innerHTML = '<li>No se ha podido cargar el historial.</li>'; });
  if (!puede()) return;
  const msg = (t, tipo='') => { const m = $('#l-msg'); m.className = 'msg ' + tipo; m.textContent = t; };
  $('#s-guardar').onclick = async () => {
    const m = $('#s-msg'); m.className = 'msg'; m.textContent = 'Guardando…';
    try { await api('PATCH', `/api/leads/${encodeURIComponent(l.id_lead)}/seguimiento`, {estado: $('#s-estado').value, notas: $('#s-notas').value});
      await cargarDatos(); refrescarLeads(); abrirLead(l.id_lead); avisar('Seguimiento guardado'); }
    catch(e) { m.className = 'msg err'; m.textContent = e.message; }
  };
  const bia = $('#b-ia');
  if (bia) bia.onclick = async () => {
    bia.disabled = true; msg('Analizando con IA… puede tardar unos segundos.');
    try { await api('POST', `/api/ia/leads/${encodeURIComponent(l.id_lead)}/analizar`); await cargarDatos(); refrescarLeads(); abrirLead(l.id_lead); avisar('Análisis de IA guardado'); }
    catch(e) { msg(e.message, 'err'); bia.disabled = false; }
  };
  const bconv = $('#b-convertir');
  if (bconv) bconv.onclick = async () => {
    bconv.disabled = true;
    try { await api('POST', `/api/leads/${encodeURIComponent(l.id_lead)}/convertir`); _clientes = null; await cargarDatos(); refrescarLeads(); abrirLead(l.id_lead); avisar('Oportunidad creada en el embudo'); }
    catch(e) { msg(e.message, 'err'); bconv.disabled = false; }
  };
  $('#b-tarea').onclick = () => formularioTarea({lead_id: l.id, cliente_id: l.cliente_id || '', titulo: `${a.accion} · ${l.empresa}`.slice(0,200), vence: a.fecha_limite || ''}, () => avisar('Tarea creada'));
  $('#b-editar').onclick = () => formularioLead(l);
  confirmarBorrado($('#b-borrar'), async () => { await api('DELETE', `/api/leads/${encodeURIComponent(l.id_lead)}`); dlg.close(); await cargarDatos(); refrescarLeads(); avisar(`${l.empresa} eliminado`); });
}
const CAMPOS_LEAD = () => [
  ['empresa','Empresa','text',{obligatorio:true}],['sector','Sector','select',{opciones:D.opciones.sectores}],['nombre','Nombre','text'],['apellidos','Apellidos','text'],
  ['email','Email','email'],['telefono','Teléfono','tel'],['cargo','Cargo','text'],['empleados','Empleados','number'],
  ['pais','País','text'],['ciudad','Ciudad','text'],['origen','Origen','select',{opciones:D.opciones.origenes}],['presupuesto_eur','Presupuesto (€)','number'],
  ['plazo_compra','Plazo de compra','select',{opciones:D.opciones.plazos}],['demo_solicitada','¿Ha pedido demo?','select',{opciones:['Sí','No']}],['visitas_web','Visitas web','number'],
  ['descargas','Descargas','number'],['emails_abiertos','Emails abiertos','number'],['fecha_alta','Fecha de alta','date'],
  ['ultimo_contacto','Último contacto','date'],['comentarios','Comentarios','area']];
function formularioLead(l){
  const editar = !!l, hoy = D.meta.fecha_referencia;
  formulario({titulo: editar ? `Editar ${l.empresa}` : 'Añadir lead', campos: CAMPOS_LEAD(), textoEnviar: editar ? 'Guardar cambios' : 'Añadir lead',
    valores: l || {pais:'España', demo_solicitada:'No', plazo_compra:'Sin definir', fecha_alta: hoy, ultimo_contacto: hoy},
    nota: 'Al guardar, el motor valida los datos y vuelve a calcular la puntuación y la clase.',
    enviar: async datos => {
      const r = editar ? await api('PUT', `/api/leads/${encodeURIComponent(l.id_lead)}`, datos) : await api('POST', '/api/leads', datos);
      await cargarDatos(); refrescarLeads();
      avisar(editar ? 'Cambios guardados' : `Lead añadido: ${r.clasificacion}, ${r.puntuacion} puntos`);
      setTimeout(() => abrirLead(editar ? l.id_lead : r.id_lead), 0);
    }});
}
function abrirImportar(){
  abrirFicha(`<header><h2 id="d-tit">Importar leads</h2><button type="button" class="btn" data-cerrar>Cerrar</button></header>
    <form id="form-imp" style="display:grid;gap:12px">
      <p>Sube un CSV o Excel con las mismas columnas que <b>datos/leads.csv</b>. Cada fila se valida y se puntúa con las reglas del motor y se añade a los leads actuales.</p>
      <label for="fichero" style="font-weight:700">Fichero</label>
      <input id="fichero" name="fichero" type="file" accept=".csv,.xlsx" required>
      <p class="msg" id="imp-msg" role="status" aria-live="polite"></p>
      <div class="acciones"><button type="submit" class="btn prim">Importar</button></div></form>`);
  $('#form-imp').onsubmit = async e => {
    e.preventDefault();
    const msg = $('#imp-msg');
    if (!$('#fichero').files.length) { msg.className = 'msg err'; msg.textContent = 'Elige un fichero.'; return; }
    msg.className = 'msg'; msg.textContent = 'Importando…';
    try { const r = await api('POST', '/api/importar', new FormData($('#form-imp')));
      await cargarDatos(); refrescarLeads();
      msg.className = 'msg ok'; msg.textContent = `${r.importados} leads importados y puntuados.` + (r.errores.length ? ` ${r.errores.length} filas con errores: ${r.errores.slice(0,3).join(' · ')}` : '');
      $('#fichero').value = ''; }
    catch(err) { msg.className = 'msg err'; msg.textContent = err.message; }
  };
}

/* ════════ CLIENTES Y CONTACTOS ════════ */
const estadoCli = {pestana: 'clientes', q: '', sector: '', tipo: ''};
async function vClientes(){
  vista().innerHTML = `
    <div class="cab"><h2>Clientes y contactos</h2>
      <div class="acciones">${puede()?'<button type="button" class="btn prim" id="b-nuevo"></button>':''}</div></div>
    <div class="barra" role="group" aria-label="Ver">
      <button type="button" class="btn" data-p="clientes" aria-pressed="${estadoCli.pestana==='clientes'}">Clientes</button>
      <button type="button" class="btn" data-p="contactos" aria-pressed="${estadoCli.pestana==='contactos'}">Contactos</button></div>
    <div class="barra" id="filtros"></div>
    <p id="estado" class="estado" role="status" aria-live="polite"></p>
    <div class="tabla"><table><thead><tr id="cab"></tr></thead><tbody id="tbody"></tbody></table></div>`;
  $$('[data-p]').forEach(b => { if (b.dataset.p === estadoCli.pestana) b.classList.add('prim'); b.onclick = () => { estadoCli.pestana = b.dataset.p; estadoCli.q = ''; vClientes(); }; });
  if (estadoCli.pestana === 'clientes') await pintarClientes(); else await pintarContactos();
}
async function pintarClientes(){
  if (puede()) { $('#b-nuevo').textContent = 'Nuevo cliente'; $('#b-nuevo').onclick = () => formularioCliente(null); }
  $('#filtros').innerHTML = `<div class="campo"><label for="q">Buscar por nombre, ciudad o sector</label><input id="q" type="search" value="${esc(estadoCli.q)}"></div>
    <div class="campo estrecho"><label for="fs">Sector</label><select id="fs">${opcionesHTML(D.opciones.sectores, estadoCli.sector, 'Todos')}</select></div>
    <div class="campo estrecho"><label for="ft">Tipo</label><select id="ft">${opcionesHTML(D.opciones.tipos_cliente, estadoCli.tipo, 'Todos')}</select></div>`;
  $('#cab').innerHTML = ['Cliente','Tipo','Sector','Ubicación','Contactos','Embudo abierto','Responsable',''].map(t => `<th scope="col">${t}</th>`).join('');
  const cargar = async () => {
    const p = new URLSearchParams({q: estadoCli.q, sector: estadoCli.sector, tipo: estadoCli.tipo});
    const lista = await api('GET', '/api/clientes?' + p);
    _clientes = null;
    $('#estado').textContent = `${lista.length} clientes.`;
    $('#tbody').innerHTML = lista.length ? lista.map(c => `<tr>
      <td data-label="Cliente"><span class="emp">${esc(c.nombre)}</span>${c.web?`<span class="sub">${esc(c.web)}</span>`:''}</td>
      <td data-label="Tipo"><span class="etq" style="--c:${c.tipo==='Cliente'?'var(--ok)':'var(--muted)'}">${esc(c.tipo)}</span></td>
      <td data-label="Sector">${esc(c.sector||'Sin dato')}</td>
      <td data-label="Ubicación">${esc([c.ciudad,c.pais].filter(Boolean).join(', ')||'Sin dato')}</td>
      <td data-label="Contactos" class="num">${c.contactos}</td>
      <td data-label="Embudo abierto" class="num">${c.oportunidades_abiertas ? `${eur(c.valor_abierto)} <span class="sub">(${c.oportunidades_abiertas})</span>` : '—'}</td>
      <td data-label="Responsable">${esc(c.responsable||'Sin asignar')}</td>
      <td data-label="Detalle"><button type="button" class="btn" data-id="${c.id}">Ver ficha</button></td></tr>`).join('')
      : '<tr><td colspan="8" class="vacio">No hay clientes con estos filtros. Crea uno o convierte un lead en oportunidad.</td></tr>';
    $$('#tbody [data-id]').forEach(b => b.onclick = () => abrirCliente(+b.dataset.id, b));
  };
  let t; $('#q').oninput = e => { estadoCli.q = e.target.value; clearTimeout(t); t = setTimeout(cargar, 250); };
  $('#fs').onchange = e => { estadoCli.sector = e.target.value; cargar(); };
  $('#ft').onchange = e => { estadoCli.tipo = e.target.value; cargar(); };
  await cargar();
}
async function pintarContactos(){
  if (puede()) { $('#b-nuevo').textContent = 'Nuevo contacto'; $('#b-nuevo').onclick = () => formularioContacto(null, {}, pintarContactos); }
  $('#filtros').innerHTML = `<div class="campo"><label for="q">Buscar por nombre, email o cargo</label><input id="q" type="search" value="${esc(estadoCli.q)}"></div>`;
  $('#cab').innerHTML = ['Contacto','Cliente','Email','Teléfono',''].map(t => `<th scope="col">${t}</th>`).join('');
  const cargar = async () => {
    const lista = await api('GET', '/api/contactos?' + new URLSearchParams({q: estadoCli.q}));
    $('#estado').textContent = `${lista.length} contactos.`;
    $('#tbody').innerHTML = lista.length ? lista.map(c => `<tr>
      <td data-label="Contacto"><span class="emp">${esc(c.nombre)} ${esc(c.apellidos)}</span><span class="sub">${esc(c.cargo||'')}</span></td>
      <td data-label="Cliente">${esc(c.cliente||'Sin cliente')}</td>
      <td data-label="Email" style="overflow-wrap:anywhere">${esc(c.email||'—')}</td>
      <td data-label="Teléfono" class="num">${esc(c.telefono||'—')}</td>
      <td data-label="Editar">${puede()?`<button type="button" class="btn" data-id="${c.id}">Editar</button>`:''}</td></tr>`).join('')
      : '<tr><td colspan="5" class="vacio">No hay contactos.</td></tr>';
    $$('#tbody [data-id]').forEach(b => b.onclick = () => formularioContacto(lista.find(x => x.id === +b.dataset.id), {}, pintarContactos));
  };
  let t; $('#q').oninput = e => { estadoCli.q = e.target.value; clearTimeout(t); t = setTimeout(cargar, 250); };
  await cargar();
}
async function abrirCliente(id, boton){
  const c = await api('GET', `/api/clientes/${id}`);
  abrirFicha(`
    <header><div><h2 id="d-tit">${esc(c.nombre)}</h2><p class="muted">${esc(c.tipo)}${c.sector?' · '+esc(c.sector):''}${c.ciudad?' · '+esc(c.ciudad):''}</p></div>
      <button type="button" class="btn" data-cerrar>Cerrar</button></header>
    ${puede()?`<div class="acciones" style="justify-content:flex-start"><button type="button" class="btn" id="c-cont">Añadir contacto</button>
      <button type="button" class="btn" id="c-op">Nueva oportunidad</button><button type="button" class="btn" id="c-tar">Nueva tarea</button></div>`:''}
    <dl class="datos">
      <div><dt>Empleados</dt><dd class="num">${c.empleados ?? 'Sin dato'}</dd></div><div><dt>Responsable</dt><dd>${esc(c.responsable||'Sin asignar')}</dd></div>
      <div><dt>Teléfono</dt><dd class="num">${esc(c.telefono||'Sin dato')}</dd></div><div><dt>Web</dt><dd>${esc(c.web||'Sin dato')}</dd></div>
      ${c.notas?`<div style="grid-column:1/-1"><dt>Notas</dt><dd>${esc(c.notas)}</dd></div>`:''}</dl>
    <section><h3>Contactos</h3>${c.contactos_lista.length?`<ul class="lista">${c.contactos_lista.map(x=>`<li><span><span class="t">${esc(x.nombre)} ${esc(x.apellidos)}</span><span class="s">${esc(x.cargo)}${x.email?' · '+esc(x.email):''}${x.telefono?' · '+esc(x.telefono):''}</span></span>
      ${puede()?`<button type="button" class="btn peq" data-cont="${x.id}">Editar</button>`:''}</li>`).join('')}</ul>`:'<p class="muted">Sin contactos.</p>'}</section>
    <section><h3>Oportunidades</h3>${c.oportunidades.length?`<ul class="lista">${c.oportunidades.map(o=>`<li><span><span class="t">${esc(o.titulo)}</span><span class="s">${esc(o.etapa)} · ${o.probabilidad} %</span></span><span class="num">${eur(o.importe)}</span></li>`).join('')}</ul>`:'<p class="muted">Sin oportunidades.</p>'}</section>
    <section><h3>Tareas</h3>${c.tareas.length?`<ul class="lista">${c.tareas.map(t=>`<li class="${t.estado==='Hecha'?'hecha':''}"><span><span class="t">${esc(t.titulo)}</span><span class="s">${esc(t.estado)} · ${esc(t.asignado)}</span></span><span class="num ${t.vencida?'vencida':'muted'}">${t.vence?fecha(t.vence):''}</span></li>`).join('')}</ul>`:'<p class="muted">Sin tareas.</p>'}</section>
    ${c.leads.length?`<section><h3>Leads de origen</h3><p>${c.leads.map(l=>`${esc(l.id_lead)} (${esc(l.clasificacion)}, ${l.puntuacion})`).join(' · ')}</p></section>`:''}
    <section><h3>Historial</h3><ul class="historial">${c.historial.map(h=>`<li>${fechaHora(h.fecha)} · ${esc(h.usuario)} · ${esc(h.accion)}${h.detalle?': '+esc(h.detalle):''}</li>`).join('')||'<li>Sin movimientos.</li>'}</ul></section>
    ${puede()?'<div class="acciones"><button type="button" class="btn peligro" id="c-borrar">Eliminar cliente</button><button type="button" class="btn" id="c-editar">Editar datos</button></div>':''}`, boton);
  if (!puede()) return;
  const volver = () => abrirCliente(id);
  $('#c-editar').onclick = () => formularioCliente(c);
  $('#c-cont').onclick = () => formularioContacto(null, {cliente_id: c.id}, volver);
  $$('[data-cont]').forEach(b => b.onclick = () => formularioContacto(c.contactos_lista.find(x => x.id === +b.dataset.cont), {}, volver));
  $('#c-op').onclick = () => formularioOportunidad(null, {cliente_id: c.id, titulo: c.nombre + ' · '}, volver);
  $('#c-tar').onclick = () => formularioTarea({cliente_id: c.id}, volver);
  confirmarBorrado($('#c-borrar'), async () => { await api('DELETE', `/api/clientes/${c.id}`); dlg.close(); _clientes = null; avisar('Cliente eliminado'); recargarVista(); });
}
function formularioCliente(c){
  formulario({titulo: c ? `Editar ${c.nombre}` : 'Nuevo cliente', valores: c || {tipo: 'Cliente potencial', pais: 'España', responsable_id: D.usuario.id},
    campos: [['nombre','Nombre','text',{obligatorio:true}],['tipo','Tipo','select',{opciones:D.opciones.tipos_cliente}],
      ['sector','Sector','select',{opciones:D.opciones.sectores}],['empleados','Empleados','number'],['pais','País','text'],['ciudad','Ciudad','text'],
      ['web','Web','text'],['telefono','Teléfono','tel'],['responsable_id','Responsable','select',{opciones:usuariosOps(),vacio:'Sin asignar'}],['notas','Notas','area']],
    enviar: async v => { const r = c ? await api('PUT', `/api/clientes/${c.id}`, v) : await api('POST', '/api/clientes', v);
      _clientes = null; avisar(c ? 'Cliente guardado' : 'Cliente creado');
      if (location.hash === '#clientes') { await vClientes(); abrirCliente(r.id); } }});
}
async function formularioContacto(k, valores, despues){
  const ops = await clientesOps();
  formulario({titulo: k ? `Editar ${k.nombre}` : 'Nuevo contacto', valores: k || valores,
    campos: [['nombre','Nombre','text',{obligatorio:true}],['apellidos','Apellidos','text'],['email','Email','email'],['telefono','Teléfono','tel'],
      ['cargo','Cargo','text'],['cliente_id','Cliente','select',{opciones:ops,vacio:'Sin cliente'}],['notas','Notas','area']],
    borrar: k && puede() ? async () => { await api('DELETE', `/api/contactos/${k.id}`); avisar('Contacto eliminado'); if (despues) despues(); } : null,
    enviar: async v => { k ? await api('PUT', `/api/contactos/${k.id}`, v) : await api('POST', '/api/contactos', v); avisar('Contacto guardado'); if (despues) despues(); }});
}

/* ════════ OPORTUNIDADES ════════ */
async function formularioOportunidad(o, valores = {}, despues){
  const [ops, contactos] = await Promise.all([clientesOps(), api('GET', '/api/contactos')]);
  formulario({titulo: o ? `Editar oportunidad` : 'Nueva oportunidad',
    valores: o || {etapa: 'Nuevo', responsable_id: D.usuario.id, ...valores},
    nota: 'Si dejas la probabilidad vacía se usa la de la etapa.',
    campos: [['titulo','Título','text',{obligatorio:true,ancho:true}],['cliente_id','Cliente','select',{opciones:ops,vacio:'Sin cliente'}],
      ['contacto_id','Contacto','select',{opciones:contactos.map(k => [k.id, `${k.nombre} ${k.apellidos}`.trim() + (k.cliente?` · ${k.cliente}`:'')]),vacio:'Sin contacto'}],
      ['importe','Importe (€)','number'],['etapa','Etapa','select',{opciones:D.opciones.etapas}],['probabilidad','Probabilidad (%)','number'],
      ['fecha_cierre','Fecha de cierre prevista','date'],['responsable_id','Responsable','select',{opciones:usuariosOps(),vacio:'Sin asignar'}],['notas','Notas','area']],
    borrar: o && puede() ? async () => { await api('DELETE', `/api/oportunidades/${o.id}`); avisar('Oportunidad eliminada'); despues ? despues() : recargarVista(); } : null,
    enviar: async v => {
      if (o && v.etapa !== o.etapa && String(v.probabilidad) === String(o.probabilidad)) v.probabilidad = '';
      o ? await api('PUT', `/api/oportunidades/${o.id}`, v) : await api('POST', '/api/oportunidades', v);
      avisar('Oportunidad guardada'); despues ? despues() : recargarVista(); }});
}
const estadoOp = {q: '', etapa: '', responsable_id: ''};
async function vOportunidades(){
  vista().innerHTML = `
    <div class="cab"><h2>Oportunidades</h2><div class="acciones">${puede()?'<button type="button" class="btn prim" id="b-nuevo">Nueva oportunidad</button>':''}</div></div>
    <div class="barra"><div class="campo"><label for="q">Buscar por título o cliente</label><input id="q" type="search" value="${esc(estadoOp.q)}"></div>
      <div class="campo estrecho"><label for="fe">Etapa</label><select id="fe">${opcionesHTML(D.opciones.etapas, estadoOp.etapa, 'Todas')}</select></div>
      <div class="campo estrecho"><label for="fr">Responsable</label><select id="fr">${opcionesHTML(usuariosOps(), estadoOp.responsable_id, 'Todos')}</select></div></div>
    <p id="estado" class="estado" role="status" aria-live="polite"></p>
    <div class="tabla"><table><thead><tr>${['Oportunidad','Etapa','Importe','Prob.','Ponderado','Cierre','Responsable',''].map(t=>`<th scope="col">${t}</th>`).join('')}</tr></thead><tbody id="tbody"></tbody></table></div>`;
  if (puede()) $('#b-nuevo').onclick = () => formularioOportunidad(null);
  const cargar = async () => {
    const lista = await api('GET', '/api/oportunidades?' + new URLSearchParams(estadoOp));
    const total = lista.reduce((s,o) => s + o.importe, 0), pond = lista.filter(o => !['Ganado','Perdido'].includes(o.etapa)).reduce((s,o) => s + o.ponderado, 0);
    $('#estado').textContent = `${lista.length} oportunidades · ${eur(total)} en total · ${eur(pond)} ponderado en las abiertas.`;
    $('#tbody').innerHTML = lista.length ? lista.map(o => `<tr>
      <td data-label="Oportunidad"><span class="emp">${esc(o.titulo)}</span><span class="sub">${esc(o.cliente||'Sin cliente')}</span></td>
      <td data-label="Etapa"><span class="etq" style="--c:${COLOR_ETAPA[o.etapa]||'var(--accent)'}">${esc(o.etapa)}</span></td>
      <td data-label="Importe" class="num">${eur(o.importe)}</td><td data-label="Prob." class="num">${o.probabilidad} %</td>
      <td data-label="Ponderado" class="num">${eur(o.ponderado)}</td><td data-label="Cierre" class="num">${o.fecha_cierre?fecha(o.fecha_cierre):'—'}</td>
      <td data-label="Responsable">${esc(o.responsable||'Sin asignar')}</td>
      <td data-label="Editar">${puede()?`<button type="button" class="btn" data-id="${o.id}">Editar</button>`:''}</td></tr>`).join('')
      : '<tr><td colspan="8" class="vacio">No hay oportunidades con estos filtros.</td></tr>';
    $$('#tbody [data-id]').forEach(b => b.onclick = () => formularioOportunidad(lista.find(x => x.id === +b.dataset.id), {}, cargar));
  };
  let t; $('#q').oninput = e => { estadoOp.q = e.target.value; clearTimeout(t); t = setTimeout(cargar, 250); };
  $('#fe').onchange = e => { estadoOp.etapa = e.target.value; cargar(); };
  $('#fr').onchange = e => { estadoOp.responsable_id = e.target.value; cargar(); };
  await cargar();
}

/* ════════ EMBUDO (kanban) ════════ */
async function vEmbudo(){
  const lista = await api('GET', '/api/oportunidades');
  vista().innerHTML = `
    <div class="cab"><h2>Embudo de ventas</h2><div class="acciones">${puede()?'<button type="button" class="btn prim" id="b-nuevo">Nueva oportunidad</button>':''}</div></div>
    <p class="muted">${puede()?'Cambia la etapa con el desplegable de cada tarjeta o arrástrala a otra columna.':'Vista de solo lectura.'}</p>
    <div class="kanban">${D.opciones.etapas.map(e => {
      const g = lista.filter(o => o.etapa === e), total = g.reduce((s,o) => s + o.importe, 0);
      return `<section class="col" data-etapa="${esc(e)}" aria-label="${esc(e)}"><header><h3>${esc(e)}</h3><span class="sub num">${g.length} · ${eur(total)}</span></header>
        ${g.map(o => `<article class="tarjeta" draggable="${puede()}" data-id="${o.id}">
          <span class="t">${esc(o.titulo)}</span><span class="sub">${esc(o.cliente||'Sin cliente')}</span>
          <span class="num"><b>${eur(o.importe)}</b> · ${o.probabilidad} %${o.fecha_cierre?` · ${fecha(o.fecha_cierre)}`:''}</span>
          ${puede()?`<label class="sub">Etapa <select data-mover="${o.id}" aria-label="Etapa de ${esc(o.titulo)}">${D.opciones.etapas.map(x=>`<option ${x===e?'selected':''}>${esc(x)}</option>`).join('')}</select></label>
          <button type="button" class="btn peq" data-editar="${o.id}">Editar</button>`:''}</article>`).join('') || '<p class="sub">Sin oportunidades.</p>'}</section>`;
    }).join('')}</div>`;
  if (!puede()) return;
  $('#b-nuevo').onclick = () => formularioOportunidad(null);
  const mover = async (id, etapa) => {
    try { await api('PATCH', `/api/oportunidades/${id}/etapa`, {etapa}); avisar(`Movida a ${etapa}`); await vEmbudo(); }
    catch(e) { avisar(e.message); }
  };
  $$('[data-mover]').forEach(s => s.onchange = () => mover(s.dataset.mover, s.value));
  $$('[data-editar]').forEach(b => b.onclick = () => formularioOportunidad(lista.find(x => x.id === +b.dataset.editar)));
  $$('.tarjeta').forEach(t => t.addEventListener('dragstart', e => e.dataTransfer.setData('text/plain', t.dataset.id)));
  $$('.col').forEach(c => {
    c.addEventListener('dragover', e => { e.preventDefault(); c.classList.add('sobre'); });
    c.addEventListener('dragleave', () => c.classList.remove('sobre'));
    c.addEventListener('drop', e => { e.preventDefault(); c.classList.remove('sobre'); const id = e.dataTransfer.getData('text/plain');
      const o = lista.find(x => x.id === +id); if (o && o.etapa !== c.dataset.etapa) mover(id, c.dataset.etapa); });
  });
}

/* ════════ TAREAS ════════ */
async function formularioTarea(valores = {}, despues, t = null){
  const ops = await clientesOps();
  formulario({titulo: t ? 'Editar tarea' : 'Nueva tarea', valores: t || {prioridad: 'Media', estado: 'Pendiente', asignado_id: D.usuario.id, ...valores},
    campos: [['titulo','Título','text',{obligatorio:true,ancho:true}],['vence','Vence','date'],['prioridad','Prioridad','select',{opciones:D.opciones.prioridades}],
      ['estado','Estado','select',{opciones:D.opciones.estados_tarea}],['asignado_id','Asignada a','select',{opciones:usuariosOps(),vacio:'Sin asignar'}],
      ['cliente_id','Cliente','select',{opciones:ops,vacio:'Sin cliente'}],['descripcion','Descripción','area']],
    borrar: t && puede() ? async () => { await api('DELETE', `/api/tareas/${t.id}`); avisar('Tarea eliminada'); despues ? despues() : recargarVista(); } : null,
    enviar: async v => {
      for (const k of ['lead_id','oportunidad_id']) if ((t || valores)[k]) v[k] = (t || valores)[k];
      t ? await api('PUT', `/api/tareas/${t.id}`, v) : await api('POST', '/api/tareas', v);
      avisar('Tarea guardada'); despues ? despues() : recargarVista(); }});
}
const estadoTar = {estado: 'abiertas', asignado: '', vencidas: false, q: ''};
async function vTareas(){
  vista().innerHTML = `
    <div class="cab"><h2>Tareas y seguimiento</h2><div class="acciones">${puede()?'<button type="button" class="btn prim" id="b-nuevo">Nueva tarea</button>':''}</div></div>
    <div class="barra"><div class="campo"><label for="q">Buscar</label><input id="q" type="search" value="${esc(estadoTar.q)}"></div>
      <div class="campo estrecho"><label for="fe">Estado</label><select id="fe">${opcionesHTML([['abiertas','Abiertas'],...D.opciones.estados_tarea], estadoTar.estado, 'Todas')}</select></div>
      <div class="campo estrecho"><label for="fa">Asignadas a</label><select id="fa">${opcionesHTML([['yo','Mí'],...usuariosOps()], estadoTar.asignado, 'Cualquiera')}</select></div>
      <label style="display:flex;gap:8px;align-items:center;font-weight:700;padding-bottom:10px"><input type="checkbox" id="fv" style="width:auto" ${estadoTar.vencidas?'checked':''}> Solo vencidas</label></div>
    <p id="estado" class="estado" role="status" aria-live="polite"></p>
    <ul class="lista caja" id="lista" style="padding-block:4px"></ul>`;
  if (puede()) $('#b-nuevo').onclick = () => formularioTarea({}, cargar);
  async function cargar(){
    const p = new URLSearchParams({estado: estadoTar.estado, asignado: estadoTar.asignado, q: estadoTar.q, vencidas: estadoTar.vencidas ? '1' : ''});
    const lista = await api('GET', '/api/tareas?' + p);
    $('#estado').textContent = `${lista.length} tareas.`;
    $('#lista').innerHTML = lista.length ? lista.map(t => `<li class="${t.estado==='Hecha'?'hecha':''}">
      <span style="display:flex;gap:12px;align-items:start">
        ${puede()?`<input type="checkbox" data-hecha="${t.id}" ${t.estado==='Hecha'?'checked':''} style="width:22px;height:22px;margin-top:3px" aria-label="Marcar «${esc(t.titulo)}» como hecha">`:''}
        <span><span class="t">${esc(t.titulo)}</span><span class="s">${esc(t.prioridad)} · ${esc(t.estado)} · ${esc(t.asignado||'Sin asignar')}${t.cliente?' · '+esc(t.cliente):''}</span>
        ${t.descripcion?`<span class="s" style="display:block">${esc(t.descripcion)}</span>`:''}</span></span>
      <span style="display:grid;gap:6px;justify-items:end"><span class="num ${t.vencida?'vencida':'muted'}">${t.vence?(t.vencida?'Vencida: ':'')+fecha(t.vence):'Sin fecha'}</span>
        ${puede()?`<button type="button" class="btn peq" data-id="${t.id}">Editar</button>`:''}</span></li>`).join('')
      : '<li class="vacio" style="justify-content:center">No hay tareas con estos filtros.</li>';
    $$('[data-hecha]').forEach(c => c.onchange = async () => {
      try { await api('PATCH', `/api/tareas/${c.dataset.hecha}/estado`, {estado: c.checked ? 'Hecha' : 'Pendiente'}); avisar(c.checked ? 'Tarea completada' : 'Tarea reabierta'); cargar(); }
      catch(e) { avisar(e.message); c.checked = !c.checked; }
    });
    $$('#lista [data-id]').forEach(b => b.onclick = () => formularioTarea({}, cargar, lista.find(x => x.id === +b.dataset.id)));
  }
  let tm; $('#q').oninput = e => { estadoTar.q = e.target.value; clearTimeout(tm); tm = setTimeout(cargar, 250); };
  $('#fe').onchange = e => { estadoTar.estado = e.target.value; cargar(); };
  $('#fa').onchange = e => { estadoTar.asignado = e.target.value; cargar(); };
  $('#fv').onchange = e => { estadoTar.vencidas = e.target.checked; cargar(); };
  await cargar();
}

/* ════════ INTELIGENCIA ARTIFICIAL ════════ */
async function vIA(){
  await cargarDatos();
  const e = await api('GET', '/api/ia/estado'), R = D.resumen || {}, off = !e.configurada || !puede();
  vista().innerHTML = `
    <h2>Inteligencia artificial</h2>
    <section class="caja" aria-labelledby="t-est"><h3 id="t-est">Estado</h3>
      ${e.configurada ? `<p>Conectada a la API de Claude (modelo <b>${esc(e.modelo)}</b>). Consultas hoy: <b class="num">${e.usadas_hoy}</b> de ${e.limite_diario}.</p>`
        : `<p class="msg err">La IA no está configurada en el servidor.</p><p>Para activarla, define la variable de entorno <b>ANTHROPIC_API_KEY</b> con tu clave de la API de Claude (en el fichero <b>.env</b> en local o en las variables del servicio en Render) y reinicia la aplicación. Mientras tanto, los leads usan el análisis del motor de reglas.</p>`}
      <p class="muted">Cada consulta envía a la API de Claude los datos necesarios de tu empresa (leads, oportunidades o tareas). No se envían contraseñas.</p></section>
    <section class="caja" aria-labelledby="t-res"><h3 id="t-res">Conclusión de la cartera</h3>
      ${R.resumen_ejecutivo ? `<p>${esc(R.resumen_ejecutivo)}</p>${R.ia?`<p class="ia-sello">Generado con IA · ${fechaHora(R.generado)}</p>`:'<p class="muted">Conclusión cargada con los datos de ejemplo.</p>'}` : '<p class="muted">Todavía no hay conclusión.</p>'}
      <div class="acciones" style="justify-content:flex-start"><button type="button" class="btn prim" id="b-res" ${off?'disabled':''}>Generar conclusión con IA</button><span class="msg" id="m-res" role="status" aria-live="polite"></span></div></section>
    <section class="caja" aria-labelledby="t-an"><h3 id="t-an">Analizar un lead</h3>
      <p class="muted">La IA explica la clasificación, propone el siguiente paso con su plazo y redacta el correo. La puntuación no cambia: la calcula el motor.</p>
      <div class="barra"><div class="campo"><label for="s-lead">Lead</label><select id="s-lead">${opcionesHTML(D.leads.map(l => [l.id_lead, `${l.id_lead} · ${l.empresa} · ${NOMBRE[l.clasificacion]} ${l.puntuacion}`]), '', 'Elige un lead')}</select></div>
        <button type="button" class="btn prim" id="b-an" ${off?'disabled':''}>Analizar</button></div>
      <p class="msg" id="m-an" role="status" aria-live="polite"></p><div id="r-an"></div></section>
    <section class="caja" aria-labelledby="t-pr"><h3 id="t-pr">Preguntar sobre tus datos</h3>
      <label for="pregunta" style="font-weight:700">Pregunta</label>
      <textarea id="pregunta" maxlength="1000" placeholder="Por ejemplo: ¿a qué tres leads debería llamar hoy y por qué?"></textarea>
      <div class="acciones" style="justify-content:flex-start"><button type="button" class="btn prim" id="b-pr" ${!e.configurada?'disabled':''}>Preguntar</button><span class="msg" id="m-pr" role="status" aria-live="polite"></span></div>
      <div id="r-pr"></div></section>`;
  if (!e.configurada) return;
  const ocupado = (boton, m, t) => { boton.disabled = true; m.className = 'msg'; m.textContent = t; };
  if (puede()) {
    $('#b-res').onclick = async () => { const b = $('#b-res'), m = $('#m-res'); ocupado(b, m, 'Analizando la cartera…');
      try { await api('POST', '/api/ia/resumen'); avisar('Conclusión generada'); await vIA(); } catch(err) { m.className = 'msg err'; m.textContent = err.message; b.disabled = false; } };
    $('#b-an').onclick = async () => { const id = $('#s-lead').value, b = $('#b-an'), m = $('#m-an');
      if (!id) { m.className = 'msg err'; m.textContent = 'Elige un lead.'; return; }
      ocupado(b, m, 'Analizando…');
      try { const r = await api('POST', `/api/ia/leads/${encodeURIComponent(id)}/analizar`), a = r.analisis;
        m.className = 'msg ok'; m.textContent = 'Análisis guardado en la ficha del lead.';
        $('#r-an').innerHTML = `<div class="respuesta"><b>${esc(PRIO[a.prioridad]||a.prioridad)} · ${esc(a.canal)} · ${esc(a.plazo_accion)}</b>\n${esc(a.accion)}\n\n${esc(a.justificacion)}${a.correo?`\n\nCorreo: ${esc(a.correo.asunto)}\n${esc(a.correo.cuerpo)}`:''}</div>`;
        await cargarDatos(); }
      catch(err) { m.className = 'msg err'; m.textContent = err.message; }
      b.disabled = false; };
  }
  $('#b-pr').onclick = async () => { const q = $('#pregunta').value.trim(), b = $('#b-pr'), m = $('#m-pr');
    if (!q) { m.className = 'msg err'; m.textContent = 'Escribe una pregunta.'; return; }
    ocupado(b, m, 'Pensando…');
    try { const r = await api('POST', '/api/ia/preguntar', {pregunta: q}); m.textContent = ''; $('#r-pr').innerHTML = `<div class="respuesta">${esc(r.respuesta)}</div>`; }
    catch(err) { m.className = 'msg err'; m.textContent = err.message; }
    b.disabled = false; };
}

/* ════════ INFORMES ════════ */
async function vInformes(){
  const i = await api('GET', '/api/informes');
  const tabla = (titulo, cab, filas, vacio) => `<section class="caja"><h3>${titulo}</h3>${filas.length?`<div class="tabla"><table><thead><tr>${cab.map(c=>`<th scope="col">${c}</th>`).join('')}</tr></thead>
    <tbody>${filas.map(f => `<tr>${f.map((v,k) => `<td data-label="${cab[k]}" class="${k?'num':''}">${v}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`:`<p class="muted">${vacio}</p>`}</section>`;
  vista().innerHTML = `
    <h2>Informes</h2>
    <section class="caja" aria-labelledby="t-desc"><h3 id="t-desc">Descargas</h3>
      <p class="muted">Se generan en el momento con los datos actuales de tu empresa.</p>
      <div class="acciones" style="justify-content:flex-start">
        <a class="btn prim" href="/descargas/excel">Excel del plan comercial</a><a class="btn" href="/descargas/informe">Informe comercial (Markdown)</a>
        <a class="btn" href="/descargas/hubspot">CSV para HubSpot</a><a class="btn" href="/descargas/oportunidades">Oportunidades (CSV)</a>
        <a class="btn" href="/descargas/clientes">Clientes (CSV)</a></div></section>
    ${tabla('Leads por clase', ['Clase','Leads','%','Puntuación media','Presupuesto declarado'],
      CLASES.map(c => [NOMBRE[c], i.leads_por_clase[c].n, i.leads_por_clase[c].pct.toLocaleString('es-ES')+' %', i.leads_por_clase[c].score_medio.toLocaleString('es-ES'), eur(i.leads_por_clase[c].presupuesto_total)]), 'Sin leads.')}
    <div class="dos">
      ${tabla('Leads por origen', ['Origen','Leads','HOT','Media'], Object.entries(i.leads_por_origen).map(([k,v]) => [esc(k), v.n, v.hot, v.score_medio.toLocaleString('es-ES')]), 'Sin leads.')}
      ${tabla('Leads por sector', ['Sector','Leads','HOT','Media'], Object.entries(i.leads_por_sector).map(([k,v]) => [esc(k), v.n, v.hot, v.score_medio.toLocaleString('es-ES')]), 'Sin leads.')}
    </div>
    ${tabla('Oportunidades por responsable', ['Responsable','Abiertas','Valor abierto','Ganadas','Valor ganado','Perdidas'],
      i.por_responsable.map(r => [esc(r.responsable), r.abiertas, eur(r.valor_abierto), r.ganadas, eur(r.valor_ganado), r.perdidas]), 'Sin oportunidades.')}
    ${tabla('Tareas por usuario', ['Usuario','Pendientes','En curso','Hechas'], i.tareas_por_usuario.map(t => [esc(t.usuario), t['Pendiente'], t['En curso'], t['Hecha']]), 'Sin tareas.')}
    ${i.hot_ocultos.length?`<section class="caja"><h3>HOT ocultos</h3><p>Leads que serían HOT si se corrigen sus datos: <b>${i.hot_ocultos.map(esc).join(', ')}</b>.</p></section>`:''}`;
}

/* ════════ AJUSTES ════════ */
async function vAjustes(){
  await cargarDatos();
  const org = await api('GET', '/api/organizacion');
  vista().innerHTML = `
    <h2>Ajustes</h2>
    <section class="caja" aria-labelledby="t-cta"><h3 id="t-cta">Mi cuenta</h3>
      <p>${esc(D.usuario.nombre)} · ${esc(D.usuario.email)} · ${ROL[D.usuario.rol]}</p>
      <form id="f-clave" class="form" novalidate>
        <label for="c-act">Contraseña actual<input id="c-act" type="password" autocomplete="current-password"></label>
        <label for="c-nue">Nueva contraseña (mínimo 10)<input id="c-nue" type="password" autocomplete="new-password"></label>
        <p class="msg ancho" id="c-msg" role="status" aria-live="polite"></p>
        <div class="acciones ancho"><button type="button" class="btn" id="b-sesiones">Cerrar mis otras sesiones</button><button type="submit" class="btn prim">Cambiar contraseña</button></div></form></section>
    ${esAdmin()?`<section class="caja" aria-labelledby="t-emp"><h3 id="t-emp">Empresa</h3>
      <p class="muted">Estos datos aparecen en los correos y los usa la IA para redactar con sentido.</p>
      <form id="f-org" class="form" novalidate>
        <label for="o-nombre">Nombre<input id="o-nombre" name="nombre" value="${esc(org.nombre)}" required></label>
        <label for="o-producto">Producto o servicio que vendéis<input id="o-producto" name="producto" value="${esc(org.producto)}"></label>
        <label class="ancho" for="o-firma">Firma de los correos<input id="o-firma" name="firma" value="${esc(org.firma)}"></label>
        <label class="ancho" for="o-desc">Descripción del negocio (clientes objetivo, ticket medio…)<textarea id="o-desc" name="descripcion_negocio">${esc(org.descripcion_negocio)}</textarea></label>
        <label for="o-fecha">Fecha de referencia del motor<input id="o-fecha" name="fecha_referencia" type="date" value="${esc(org.fecha_referencia)}"><span class="sub">Vacía = fecha de hoy. Fíjala solo para demos.</span></label>
        <p class="msg ancho" id="o-msg" role="status" aria-live="polite"></p>
        <div class="acciones ancho"><button type="submit" class="btn prim">Guardar empresa</button></div></form>
      ${org.leads===0?`<div class="seguimiento"><h3>Datos de ejemplo</h3><p>Carga 30 leads ficticios con su análisis para probar el CRM. Solo los verá tu empresa.</p>
        <div class="acciones" style="justify-content:flex-start"><button type="button" class="btn" id="b-demo">Cargar datos de ejemplo</button></div></div>`:''}</section>
    <section class="caja" aria-labelledby="t-usr"><h3 id="t-usr">Usuarios y permisos</h3>
      <p class="muted">Solo lectura: consulta. Comercial: crea y edita. Administrador: además gestiona usuarios y la empresa.</p>
      <ul class="lista" id="usuarios"><li>Cargando…</li></ul>
      <form id="f-usr" class="form" novalidate><h3 class="ancho">Nuevo usuario</h3>
        <label for="u-nombre">Nombre<input id="u-nombre" name="nombre" autocomplete="off"></label>
        <label for="u-email">Email<input id="u-email" name="email" type="email" autocomplete="off"></label>
        <label for="u-clave">Contraseña inicial (mínimo 10)<input id="u-clave" name="clave" type="password" autocomplete="new-password"></label>
        <label for="u-rol">Rol<select id="u-rol" name="rol"><option value="comercial">Comercial</option><option value="lectura">Solo lectura</option><option value="admin">Administrador</option></select></label>
        <p class="msg ancho" id="u-msg" role="status" aria-live="polite"></p>
        <div class="acciones ancho"><button type="submit" class="btn prim">Crear usuario</button></div></form></section>`:''}`;

  $('#f-clave').onsubmit = async e => { e.preventDefault(); const m = $('#c-msg');
    try { const r = await api('POST', '/api/cuenta/clave', {actual: $('#c-act').value, nueva: $('#c-nue').value});
      CSRF = r.csrf; $('#csrf-salir').value = CSRF; m.className = 'msg ok'; m.textContent = 'Contraseña cambiada. Las demás sesiones se han cerrado.'; $('#f-clave').reset(); }
    catch(err) { m.className = 'msg err'; m.textContent = err.message; } };
  $('#b-sesiones').onclick = async () => { const m = $('#c-msg');
    try { const r = await api('POST', '/api/cuenta/cerrar-sesiones'); CSRF = r.csrf; $('#csrf-salir').value = CSRF; m.className = 'msg ok'; m.textContent = 'Se han cerrado tus otras sesiones.'; }
    catch(err) { m.className = 'msg err'; m.textContent = err.message; } };
  if (!esAdmin()) return;
  $('#f-org').onsubmit = async e => { e.preventDefault(); const m = $('#o-msg');
    try { await api('PUT', '/api/organizacion', Object.fromEntries(new FormData($('#f-org')).entries())); await cargarDatos(); m.className = 'msg ok'; m.textContent = 'Empresa guardada.'; }
    catch(err) { m.className = 'msg err'; m.textContent = err.message; } };
  const demo = $('#b-demo');
  if (demo) demo.onclick = async () => { demo.disabled = true;
    try { const r = await api('POST', '/api/organizacion/demo'); avisar(`${r.cargados} leads de ejemplo cargados`); location.hash = '#leads'; }
    catch(err) { avisar(err.message); demo.disabled = false; } };
  async function pintarUsuarios(){
    const lista = await api('GET', '/api/usuarios');
    $('#usuarios').innerHTML = lista.map(u => `<li><span><span class="t">${esc(u.nombre)}${u.activo?'':' (sin acceso)'}</span><span class="s">${esc(u.email)} · último acceso: ${u.ultimo_acceso?fechaHora(u.ultimo_acceso):'nunca'}</span></span>
      ${u.id===D.usuario.id||u.rol==='propietario' ? `<span class="muted">${ROL[u.rol]}${u.id===D.usuario.id?' · Tú':''}</span>` :
      `<span class="acciones"><select data-rol="${u.id}" aria-label="Rol de ${esc(u.nombre)}" style="width:auto">${['lectura','comercial','admin'].map(r=>`<option value="${r}" ${r===u.rol?'selected':''}>${ROL[r]}</option>`).join('')}</select>
        <button type="button" class="btn peq" data-activo="${u.id}" data-v="${u.activo?0:1}">${u.activo?'Quitar acceso':'Devolver acceso'}</button>
        <button type="button" class="btn peq peligro" data-borrar="${u.id}">Eliminar</button></span>`}</li>`).join('');
    $$('[data-rol]').forEach(s => s.onchange = async () => { try { await api('PATCH', `/api/usuarios/${s.dataset.rol}`, {rol: s.value}); avisar('Rol cambiado'); } catch(e) { avisar(e.message); } pintarUsuarios(); });
    $$('[data-activo]').forEach(b => b.onclick = async () => { try { await api('PATCH', `/api/usuarios/${b.dataset.activo}`, {activo: b.dataset.v === '1'}); avisar('Acceso actualizado'); } catch(e) { avisar(e.message); } pintarUsuarios(); });
    $$('[data-borrar]').forEach(b => confirmarBorrado(b, async () => { await api('DELETE', `/api/usuarios/${b.dataset.borrar}`); avisar('Usuario eliminado'); await cargarDatos(); pintarUsuarios(); }));
  }
  $('#f-usr').onsubmit = async e => { e.preventDefault(); const m = $('#u-msg');
    try { await api('POST', '/api/usuarios', Object.fromEntries(new FormData($('#f-usr')).entries())); m.className = 'msg ok'; m.textContent = 'Usuario creado. Comunícale su contraseña por un canal seguro.'; $('#f-usr').reset(); await cargarDatos(); pintarUsuarios(); }
    catch(err) { m.className = 'msg err'; m.textContent = err.message; } };
  await pintarUsuarios();
}

/* ── inicio ─────────────────────────────────────────────────────────── */
cargarDatos().then(navegar).catch(e => { vista().innerHTML = `<p class="msg err">${esc(e.message)}</p>`; });
