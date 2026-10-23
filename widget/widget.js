/* SABIO widget: se instala con
 *   <script src="https://TU-SERVIDOR/widget.js" data-site="ID_DEL_SITIO" defer></script>
 * Opcionales: data-color="#2f5bea" data-title="Asistente" data-position="right|left"
 */
(function () {
  var script = document.currentScript || document.querySelector('script[data-site]');
  if (!script) return;
  var SITE = script.getAttribute('data-site');
  var API = new URL(script.src).origin;
  var COLOR = script.getAttribute('data-color') || '#2f5bea';
  var TITLE = script.getAttribute('data-title') || 'Asistente';
  var POS = script.getAttribute('data-position') === 'left' ? 'left' : 'right';
  var KEY = 'sabio_' + SITE;

  function load() { try { return JSON.parse(sessionStorage.getItem(KEY)) || null; } catch (e) { return null; } }
  function save(s) { try { sessionStorage.setItem(KEY, JSON.stringify(s)); } catch (e) {} }
  var state = load() || { session: Math.random().toString(36).slice(2), history: [], open: false };

  var host = document.createElement('div');
  host.id = 'sabio-widget';
  document.body.appendChild(host);
  var root = host.attachShadow ? host.attachShadow({ mode: 'open' }) : host;

  root.innerHTML =
    '<style>' +
    ':host{all:initial}' +
    '*{box-sizing:border-box;font-family:system-ui,-apple-system,"Segoe UI",Roboto,Arial,sans-serif}' +
    '.btn{position:fixed;bottom:20px;' + POS + ':20px;width:58px;height:58px;border-radius:50%;border:0;cursor:pointer;' +
    'background:' + COLOR + ';color:#fff;box-shadow:0 6px 20px rgba(0,0,0,.25);display:flex;align-items:center;justify-content:center;z-index:2147483000}' +
    '.btn svg{width:28px;height:28px}' +
    '.panel{position:fixed;bottom:90px;' + POS + ':20px;width:360px;max-width:calc(100vw - 32px);height:520px;max-height:calc(100vh - 120px);' +
    'background:#fff;border-radius:14px;box-shadow:0 12px 40px rgba(0,0,0,.22);display:none;flex-direction:column;overflow:hidden;z-index:2147483000}' +
    '.panel.open{display:flex}' +
    '.head{background:' + COLOR + ';color:#fff;padding:14px 16px;font-size:15px;font-weight:600;display:flex;justify-content:space-between;align-items:center}' +
    '.head small{display:block;font-weight:400;opacity:.85;font-size:12px}' +
    '.x{background:none;border:0;color:#fff;font-size:22px;cursor:pointer;line-height:1}' +
    '.msgs{flex:1;overflow-y:auto;padding:14px;background:#f6f7fb;display:flex;flex-direction:column;gap:8px}' +
    '.m{max-width:85%;padding:9px 12px;border-radius:12px;font-size:14px;line-height:1.4;white-space:pre-wrap;word-wrap:break-word}' +
    '.u{align-self:flex-end;background:' + COLOR + ';color:#fff;border-bottom-right-radius:4px}' +
    '.b{align-self:flex-start;background:#fff;color:#1d2433;border:1px solid #e3e6ee;border-bottom-left-radius:4px}' +
    '.src{display:block;margin-top:6px;font-size:12px}' +
    '.src a{color:' + COLOR + ';text-decoration:none}' +
    '.typing{opacity:.6;font-style:italic}' +
    'form{display:flex;border-top:1px solid #e3e6ee;padding:8px;gap:6px;background:#fff}' +
    'input{flex:1;border:1px solid #d5d9e3;border-radius:20px;padding:9px 14px;font-size:14px;outline:none}' +
    'input:focus{border-color:' + COLOR + '}' +
    'button.send{border:0;background:' + COLOR + ';color:#fff;border-radius:20px;padding:0 14px;cursor:pointer;font-size:14px}' +
    '.foot{font-size:10px;color:#8a90a0;text-align:center;padding:0 0 6px;background:#fff}' +
    '</style>' +
    '<div class="panel" part="panel"><div class="head"><div>' + TITLE + '<small>Respondo con la información de este sitio</small></div>' +
    '<button class="x" aria-label="Cerrar">×</button></div>' +
    '<div class="msgs" aria-live="polite"></div>' +
    '<form><input placeholder="Escribí tu consulta…" aria-label="Consulta" maxlength="500"/><button class="send" type="submit">Enviar</button></form>' +
    '<div class="foot">Funciona con SABIO</div></div>' +
    '<button class="btn" aria-label="Abrir asistente"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg></button>';

  var panel = root.querySelector('.panel');
  var msgs = root.querySelector('.msgs');
  var form = root.querySelector('form');
  var input = root.querySelector('input');

  function bubble(role, text, sources) {
    var d = document.createElement('div');
    d.className = 'm ' + (role === 'user' ? 'u' : 'b');
    d.textContent = text;
    (sources || []).forEach(function (s) {
      var a = document.createElement('a');
      a.href = s.url; a.target = '_top'; a.textContent = '↗ ' + (s.titulo || s.url);
      var w = document.createElement('span'); w.className = 'src'; w.appendChild(a); d.appendChild(w);
    });
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function render() {
    msgs.innerHTML = '';
    if (!state.history.length) bubble('assistant', '¡Hola! ¿En qué te puedo ayudar? Podés preguntarme por productos, precios, stock o envíos.');
    state.history.forEach(function (h) { bubble(h.role, h.content, h.sources); });
  }

  function toggle(open) {
    state.open = open; save(state);
    panel.classList.toggle('open', open);
    if (open) { render(); setTimeout(function () { input.focus(); }, 50); }
  }

  root.querySelector('.btn').onclick = function () { toggle(!state.open); };
  root.querySelector('.x').onclick = function () { toggle(false); };

  form.onsubmit = function (e) {
    e.preventDefault();
    var q = input.value.trim();
    if (!q) return;
    input.value = '';
    var past = state.history.map(function (h) { return { role: h.role, content: h.content }; });
    state.history.push({ role: 'user', content: q });
    bubble('user', q);
    var t = bubble('assistant', 'Escribiendo…'); t.classList.add('typing');
    fetch(API + '/api/chat', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ site_id: SITE, message: q, session: state.session, history: past })
    }).then(function (r) { return r.json(); }).then(function (d) {
      t.remove();
      var msg = { role: 'assistant', content: d.respuesta || 'No pude responder ahora.', sources: d.fuentes || [] };
      state.history.push(msg); save(state);
      bubble('assistant', msg.content, msg.sources);
    }).catch(function () {
      t.remove(); bubble('assistant', 'Hubo un problema de conexión. Probá de nuevo en un momento.');
    });
  };

  if (state.open) toggle(true);
})();
