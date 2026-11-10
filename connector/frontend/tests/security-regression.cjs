/* FIX 01: execute actual compiled TS modules in a deterministic hook/browser harness.
 * No network, DOM server, service listener, or new dependency is used.
 * Run: node frontend/tests/security-regression.cjs
 */
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const ts = require('../node_modules/typescript');
const { test } = require('node:test');
const root = path.resolve(__dirname, '..');

function storage() {
  const values = new Map();
  return { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}

function loadModule(relative, dependencies, globals = {}) {
  const source = fs.readFileSync(path.join(root, relative), 'utf8');
  const result = ts.transpileModule(source, { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.React, esModuleInterop: true,
  } });
  const exports = {};
  vm.runInNewContext(result.outputText, {
    exports, require: name => {
      if (!(name in dependencies)) throw new Error(`Unmocked dependency: ${name}`);
      return dependencies[name];
    }, ...globals,
  }, { filename: relative });
  return exports;
}

function browserApi() {
  const localStorage = storage(), sessionStorage = storage(), window = new EventTarget();
  let fetchImpl = async () => { throw new Error('Network is disabled in this harness'); };
  const module = loadModule('src/services/api.ts', {}, {
    localStorage, sessionStorage, window, Headers, Event, FormData, URLSearchParams,
    fetch: (...args) => fetchImpl(...args),
  });
  return { ...module, localStorage, sessionStorage, window, setFetch: impl => { fetchImpl = impl; } };
}

function authHarness(verify, initialToken = '') {
  const api = browserApi();
  if (initialToken) api.setAdminToken(initialToken);
  api.api.verifyToken = verify;
  const states = [], effects = [], cleanups = [];
  let cursor = 0, current;
  const react = {
    createContext: () => ({ Provider: 'Provider' }),
    useContext: () => current,
    useState: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = typeof initial === 'function' ? initial() : initial;
      return [states[index], value => { states[index] = typeof value === 'function' ? value(states[index]) : value; }];
    },
    useRef: initial => {
      const index = cursor++;
      if (!(index in states)) states[index] = { current: initial };
      return states[index];
    },
    useEffect: callback => {
      const index = cursor++;
      if (!(index in states)) { states[index] = true; effects.push(callback); }
    },
    createElement: (component, props) => { if (component === 'Provider') current = props.value; return null; },
  };
  const module = loadModule('src/context/AuthContext.tsx', { react, '../services/api': api }, { window: api.window });
  const render = () => { cursor = 0; module.AuthProvider({ children: null }); return current; };
  render();
  return {
    api, render,
    get value() { return render(); },
    start() { for (const effect of effects.splice(0)) cleanups.push(effect()); },
    close() { for (const cleanup of cleanups) if (typeof cleanup === 'function') cleanup(); },
  };
}
const flush = () => new Promise(resolve => setImmediate(resolve));

test('no default token; old localStorage credentials are discarded', () => {
  const b = browserApi();
  b.localStorage.setItem(b.TOKEN_STORAGE_KEY, 'old-browser-credential');
  assert.equal(b.getAdminToken(), '');
  assert.equal(b.localStorage.getItem(b.TOKEN_STORAGE_KEY), null);
  b.setAdminToken('session-only-credential');
  assert.equal(b.getAdminToken(), 'session-only-credential');
  assert.equal(b.localStorage.getItem(b.TOKEN_STORAGE_KEY), null);
  b.clearAdminToken();
  assert.equal(b.getAdminToken(), '');
});

test('initial and empty-credential state never authorizes an action', async () => {
  let calls = 0, actions = 0;
  const h = authHarness(async () => { calls++; return { valid: true, role: 'admin' }; });
  assert.equal(h.value.isAuthenticated, false);
  h.value.requireAdmin(() => actions++);
  h.start(); await flush();
  assert.equal(h.value.isAuthenticated, false);
  assert.equal(calls, 0);
  assert.equal(actions, 0);
  h.close();
});

test('startup network failure clears credential and denies authentication', async () => {
  const h = authHarness(async () => { throw new Error('offline'); }, 'fixture-credential');
  h.start(); await flush();
  assert.equal(h.value.isAuthenticated, false);
  assert.equal(h.value.isValidating, false);
  assert.equal(h.api.getAdminToken(), '');
  h.close();
});

test('startup rejects invalid credentials and non-admin role', async () => {
  for (const response of [{ valid: false, role: 'guest' }, { valid: true, role: 'guest' }, { valid: 'true', role: 'admin' }]) {
    const h = authHarness(async () => response, 'fixture-credential');
    h.start(); await flush();
    assert.equal(h.value.isAuthenticated, false);
    assert.equal(h.api.getAdminToken(), '');
    h.close();
  }
});

test('saveToken fails closed on rejected, malformed or offline verification', async () => {
  for (const verify of [async () => ({ valid: false, role: 'guest' }), async () => ({ valid: true, role: 'guest' }), async () => { throw new Error('offline'); }]) {
    const h = authHarness(verify);
    h.start(); await flush();
    assert.equal(await h.value.saveToken('candidate-fixture'), false);
    assert.equal(h.value.isAuthenticated, false);
    assert.equal(h.api.getAdminToken(), '');
    h.close();
  }
});

test('valid admin verification permits action and logout removes permission', async () => {
  const h = authHarness(async () => ({ valid: true, role: 'admin' }));
  h.start(); await flush();
  assert.equal(await h.value.saveToken('verified-fixture'), true);
  assert.equal(h.value.isAuthenticated, true);
  let actions = 0;
  h.value.requireAdmin(() => actions++);
  assert.equal(actions, 1);
  h.value.logout();
  assert.equal(h.value.isAuthenticated, false);
  assert.equal(h.api.getAdminToken(), '');
  h.value.requireAdmin(() => actions++);
  assert.equal(actions, 1);
  h.close();
});

test('late verification cannot log back in after logout', async () => {
  let resolve;
  const h = authHarness(() => new Promise(done => { resolve = done; }));
  h.start(); await flush();
  const pending = h.value.saveToken('pending-fixture');
  h.value.logout();
  resolve({ valid: true, role: 'admin' });
  assert.equal(await pending, false);
  assert.equal(h.value.isAuthenticated, false);
  assert.equal(h.api.getAdminToken(), '');
  h.close();
});

test('admin requests attach header; public search and auth do not', async () => {
  const b = browserApi(); b.setAdminToken('fixture-credential');
  const calls = [];
  b.setFetch(async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => ({}) }; });
  await b.api.getDashboardStats(); await b.api.getKnowledgePages({}); await b.api.getSystemLogs();
  await b.api.searchKnowledge('IELTS'); await b.api.verifyToken('fixture-credential');
  for (const call of calls.slice(0, 3)) assert.equal(call.options.headers.get('Authorization'), 'Bearer fixture-credential');
  for (const call of calls.slice(3)) assert.equal(call.options.headers.get('Authorization'), null);
});

test('HTTP 401 invalidates frontend session', async () => {
  const h = authHarness(async () => ({ valid: true, role: 'admin' }));
  h.start(); await flush(); await h.value.saveToken('verified-fixture');
  h.api.setFetch(async () => ({ ok: false, status: 401, statusText: 'Unauthorized', json: async () => ({ detail: 'Unauthorized' }) }));
  await assert.rejects(h.api.api.getDashboardStats());
  assert.equal(h.value.isAuthenticated, false);
  assert.equal(h.api.getAdminToken(), '');
  h.close();
});

test('settings/modal contain no development-token fallback or credential preview', () => {
  const service = fs.readFileSync(path.join(root, 'src/services/api.ts'), 'utf8');
  const settings = fs.readFileSync(path.join(root, 'src/pages/SettingsPage.tsx'), 'utf8');
  const modal = fs.readFileSync(path.join(root, 'src/components/common/AuthModal.tsx'), 'utf8');
  assert.equal(/DEFAULT_DEV_TOKEN|handleResetDefaultToken/.test(service + settings + modal), false);
  assert.equal(/eyJhbGci/.test(settings), false);
  assert.equal(settings.includes('await saveToken('), true);
});
