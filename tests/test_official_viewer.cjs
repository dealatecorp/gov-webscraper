// Dependency-free unit checks for the reader's DOM contract and async lifecycle.
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

const source = readFileSync(path.join(__dirname, '../web/app.js'), 'utf8');
const reader = source.slice(source.indexOf('function officialNoticeContent('), source.indexOf('async function openDetail('));
const escape = value => String(value).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function element(tag = 'DIV', attrs = {}, children = []) {
  const classes = new Set();
  return {
    nodeType: 1, tagName: tag, attrs: {...attrs}, childNodes: children,
    dataset: {}, hidden: true, innerHTML: '', disabled: false,
    classList: { add: (...names) => names.forEach(n => classes.add(n)), remove: (...names) => names.forEach(n => classes.delete(n)), contains: n => classes.has(n) },
    getAttribute(name) { return this.attrs[name] ?? null; },
    setAttribute(name, value) { this.attrs[name] = value; },
    append(child) { this.childNodes.push(child); },
    focus() { this.focused = true; this.focusCount = (this.focusCount || 0) + 1; },
    contains(node) { return node === this || this.childNodes.some(child => child === node || child.contains?.(node)); },
    scrollIntoView() { this.scrolled = true; },
  };
}
const text = value => ({nodeType: 3, textContent: value});
function harness(api, parsed = [element('P', {}, [text('Public notice')])]) {
  const panel = element(), button = element('BUTTON'), dialog = element('DIALOG'), article = element('ARTICLE'), note = element('P'), documents = element();
  panel.querySelector = selector => selector === '.official-notice-content' ? article : note;
  const nodes = {'#official-notice-panel': panel, '#view-official-notice': button, '#detail-dialog': dialog, '#document-results': documents};
  const context = {
    detailId: 'notice-1', officialLoadSequence: 0, api,
    $: selector => nodes[selector], URL, esc: escape, fmt: value => value, icon: () => '',
    document: {
      createElement: tag => tag === 'template' ? {content: {childNodes: parsed}, innerHTML: ''} : element(tag.toUpperCase()),
      createTextNode: text,
      createDocumentFragment: () => ({nodeType: 11, childNodes: [], append(child) { this.childNodes.push(child); }}),
    },
    renderDocumentResults(result, id) { context.documentResult = {result, id}; },
  };
  vm.createContext(context);
  vm.runInContext(reader, context);
  return {context, panel, button, dialog, article, note, documents};
}
const result = {kind: 'html', html: '<p>Public notice</p>', source_url: 'https://eprocure.gov.in/eprocure/app', fetched: '2026-10-13T12:00:00Z'};
const deferred = () => { let resolve; const promise = new Promise(r => { resolve = r; }); return {promise, resolve}; };

test('primary official action is an in-app button, not an external link', () => {
  assert.match(source, /<button[^>]+id="view-official-notice"[^>]+>.*?View official notice<\/button>/);
  assert.doesNotMatch(source, /<a[^>]+>View official notice/);
  assert.match(source, /closest\('#view-official-notice'\).*viewOfficialNotice\(\)/);
});

test('reconstructs only safe text/table tags and bounded cell spans', () => {
  const td = element('TD', {colspan: '2', rowspan: '999', style: 'color:red', onclick: 'bad()'}, [text('<script>literal</script>')]);
  const h = harness(async () => result, [element('TABLE', {id:'injected'}, [element('TR', {}, [td])]), element('SCRIPT', {}, [text('bad()')]), element('A', {href:'https://evil.example'}, [text('Navigate')])]);
  const fragment = h.context.officialNoticeContent('ignored by DOM stub');
  const table = fragment.childNodes[0], cell = table.childNodes[0].childNodes[0];
  assert.deepEqual(table.attrs, {});
  assert.deepEqual(cell.attrs, {colspan:'2'});
  assert.equal(cell.childNodes[0].textContent, '<script>literal</script>');
  assert.equal(fragment.childNodes[1].childNodes.length, 0);
  assert.equal(fragment.childNodes[2].childNodes.length, 0);
});

test('loads the ID-bound endpoint and opens a read-only panel', async () => {
  const calls = [];
  const h = harness(async url => { calls.push(url); return result; });
  await h.context.viewOfficialNotice();
  assert.deepEqual(calls, ['/api/notices/notice-1/official']);
  assert.equal(h.panel.hidden, false);
  assert.equal(h.panel.dataset.loaded, 'true');
  assert.equal(h.button.attrs['aria-expanded'], 'true');
  assert.equal(h.button.disabled, false);
  assert.ok(h.dialog.classList.contains('official-preview-open'));
  assert.match(h.panel.innerHTML, /Read-only view/);
  assert.match(h.panel.innerHTML, /eprocure.gov.in/);
  assert.equal(h.article.childNodes.length, 1);
});

test('reopening retains content, while explicit refresh fetches again', async () => {
  let calls = 0;
  const h = harness(async () => { calls++; return result; });
  await h.context.viewOfficialNotice();
  h.context.closeOfficialNotice();
  assert.equal(h.panel.hidden, true);
  assert.equal(h.button.focused, true);
  await h.context.viewOfficialNotice();
  assert.equal(calls, 1);
  await h.context.viewOfficialNotice(true);
  assert.equal(calls, 2);
});

test('failed requests show escaped error and retry without leaving the app', async () => {
  const h = harness(async () => { throw Error('<script>blocked</script>'); });
  await h.context.viewOfficialNotice();
  assert.match(h.panel.innerHTML, /Official notice unavailable/);
  assert.match(h.panel.innerHTML, /&lt;script&gt;/);
  assert.match(h.panel.innerHTML, /data-refresh-official/);
  assert.doesNotMatch(h.panel.innerHTML, /href=|<script>/);
  assert.equal(h.button.disabled, false);
  assert.equal(h.panel.dataset.loaded, 'false');
});

test('closing a pending request prevents late content from reappearing', async () => {
  const pending = deferred(), h = harness(() => pending.promise);
  const work = h.context.viewOfficialNotice();
  assert.equal(h.button.disabled, true);
  h.context.closeOfficialNotice();
  const prior = h.panel.innerHTML;
  pending.resolve(result);
  await work;
  assert.equal(h.panel.hidden, true);
  assert.equal(h.panel.innerHTML, prior);
  assert.equal(h.button.disabled, false);
});

test('changing notices ignores responses for the previous notice', async () => {
  const pending = deferred(), h = harness(() => pending.promise);
  const work = h.context.viewOfficialNotice();
  h.context.detailId = 'notice-2';
  pending.resolve(result);
  await work;
  assert.equal(h.article.childNodes.length, 0);
});

test('direct PDF notices use the existing authenticated in-app document flow', async () => {
  const calls = [], docs = {documents:[{id:'pdf-1',name:'Tender.pdf'}], message:'Ready'};
  const h = harness(async (url, body) => { calls.push({url, body}); return calls.length === 1 ? {...result,kind:'pdf'} : docs; });
  await h.context.viewOfficialNotice();
  assert.equal(calls[1].url, '/api/documents');
  assert.equal(calls[1].body.id, 'notice-1');
  assert.equal(h.context.documentResult.result, docs);
  assert.equal(h.documents.scrolled, true);
});

test('an unavailable PDF remains retryable', async () => {
  const h = harness(async url => url.endsWith('/official') ? {...result,kind:'pdf'} : {documents:[],message:'Portal unavailable'});
  await h.context.viewOfficialNotice();
  assert.equal(h.panel.dataset.loaded, 'false');
  assert.match(h.panel.innerHTML, /data-refresh-official/);
});

test('a later refresh wins over an earlier unfinished request', async () => {
  const earlier = deferred(); let count = 0;
  const h = harness(() => ++count === 1 ? earlier.promise : Promise.resolve(result));
  const first = h.context.viewOfficialNotice();
  await h.context.viewOfficialNotice(true);
  const content = h.panel.innerHTML;
  earlier.resolve({...result,source_url:'https://defproc.gov.in/nicgep/app'});
  await first;
  assert.equal(h.panel.innerHTML, content);
});

test('replacing loading controls restores keyboard focus inside the reader', async () => {
  const pending = deferred(), h = harness(() => pending.promise);
  const work = h.context.viewOfficialNotice();
  const closeControl = element('BUTTON');
  h.panel.childNodes.push(closeControl);
  h.context.document.activeElement = closeControl;
  const count = h.panel.focusCount;
  pending.resolve(result);
  await work;
  assert.equal(h.panel.focusCount, count + 1);
});

test('completion does not take focus away from unrelated controls', async () => {
  const pending = deferred(), h = harness(() => pending.promise);
  const work = h.context.viewOfficialNotice();
  h.context.document.activeElement = h.button;
  const count = h.panel.focusCount;
  pending.resolve(result);
  await work;
  assert.equal(h.panel.focusCount, count);
});
