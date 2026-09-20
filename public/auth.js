'use strict';

/* ── Session helpers ─────────────────────────────────────────────────────── */

function authSave(token, role, username) {
  sessionStorage.setItem('ehc_token', token);
  sessionStorage.setItem('ehc_role', role);
  sessionStorage.setItem('ehc_username', username);
}

function authToken()    { return sessionStorage.getItem('ehc_token'); }
function authRole()     { return sessionStorage.getItem('ehc_role'); }
function authUsername()  { return sessionStorage.getItem('ehc_username'); }

function authLogout() {
  sessionStorage.clear();
  window.location.href = '/';
}

async function authRequire(expectedRole) {
  const token = authToken();
  if (!token) { authLogout(); return null; }
  try {
    const res = await fetch('/api/verify', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Authorization: 'Bearer ' + token }
    });
    const data = await res.json();
    if (!data.ok || data.role !== expectedRole) { authLogout(); return null; }
    sessionStorage.setItem('ehc_role', data.role);
    sessionStorage.setItem('ehc_username', data.username);
    return data;
  } catch { authLogout(); return null; }
}

async function getConfig() {
  try {
    const res = await fetch('/api/config');
    return await res.json();
  } catch { return {}; }
}

async function apiLogin(role, username, password) {
  try {
    const res = await fetch('/api/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ role, username, password })
    });
    const data = await res.json();
    if (data.ok) authSave(data.token, data.role, data.username);
    return data;
  } catch { return { ok: false, error: 'Network error.' }; }
}

async function apiFetch(url, opts = {}) {
  const token = authToken();
  const headers = { Authorization: 'Bearer ' + token };
  const init = { headers };
  if (opts.method) init.method = opts.method;
  if (opts.body && !(opts.body instanceof FormData)) {
    headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(opts.body);
  } else if (opts.body instanceof FormData) {
    init.body = opts.body;
  }
  try {
    const res = await fetch(url, init);
    if (res.status === 401) { authLogout(); return null; }
    const ct = res.headers.get('content-type') || '';
    if (ct.includes('spreadsheet') || ct.includes('octet-stream')) return res;
    return await res.json();
  } catch { return { error: 'Network error.' }; }
}

/* ── XSS-safe HTML escaping ──────────────────────────────────────────────── */

function h(str) {
  if (str == null) return '';
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;')
    .replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

/* ── Date formatting ─────────────────────────────────────────────────────── */

function fmtDate(s) {
  if (!s) return '—';
  const d = new Date(s);
  if (isNaN(d)) return s;
  return d.toLocaleDateString('en-GB', { day:'2-digit', month:'short', year:'numeric' });
}

function today() {
  const d = new Date();
  const yr = d.getFullYear();
  const mo = String(d.getMonth()+1).padStart(2,'0');
  const dy = String(d.getDate()).padStart(2,'0');
  return `${yr}-${mo}-${dy}`;
}

/* ── Toast notifications ─────────────────────────────────────────────────── */

function showToast(msg, type = 'info') {
  const el = document.createElement('div');
  el.className = 'toast' + (type === 'success' ? ' toast-success' : type === 'error' ? ' toast-error' : '');
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => { el.style.opacity = '0'; setTimeout(() => el.remove(), 300); }, 3000);
}

/* ── Risk badge helper ───────────────────────────────────────────────────── */

function riskBadge(level) {
  if (!level) return '';
  const l = String(level).toLowerCase();
  if (l.includes('high'))   return `<span class="risk-badge rb-high">${h(level)}</span>`;
  if (l.includes('medium')) return `<span class="risk-badge rb-medium">${h(level)}</span>`;
  if (l.includes('low'))    return `<span class="risk-badge rb-low">${h(level)}</span>`;
  if (l.includes('normal')) return `<span class="risk-badge rb-normal">${h(level)}</span>`;
  return `<span class="risk-badge rb-0">${h(level)}</span>`;
}
