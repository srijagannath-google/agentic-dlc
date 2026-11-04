/*
 * dom_driver.js — in-page step engine for agentic-dlc v4 Stage 6 (chrome-headless adapter).
 *
 * Vanilla JS, zero dependencies. run_closed_loop_eval.py inlines this file into a harness HTML
 * (app HTML + this script) and reads back a JSON results script element (id __dlc_results)
 * from `chrome --headless --dump-dom`.
 *
 * Two entry points, selected by the harness:
 *   window.__dlcInstallPrelude()  — MUST run before any app script: records addEventListener calls
 *                                   so the control audit can tell wired from dead controls.
 *   window.__dlcRun(steps, opts)  — runs the test-case steps after `load`, returns a Promise<result>.
 *
 * Step vocabulary (docs/ARCHITECTURE.md §4.6): goto, setRole, fill, click, select, check, uncheck,
 * pressKey, expectText, expectVisible, expectHidden, expectDisabled, expectEnabled, expectCount,
 * expectNoVisibleTextMatching, expectAttribute, wait.
 * Selectors are CSS; `text=Some words` matches the innermost element whose trimmed text includes the words.
 */
(function () {
  'use strict';
  var HANDLER_EVENTS = ['click', 'mousedown', 'mouseup', 'pointerdown', 'pointerup', 'touchstart', 'touchend',
    'keydown', 'keyup', 'keypress', 'change', 'input', 'submit', 'toggle', 'dblclick'];

  // ------------------------------------------------------------------ prelude (listener recorder)
  function installPrelude() {
    if (window.__dlcListeners) return;
    var registry = new WeakMap();
    window.__dlcListeners = registry;
    window.__dlcDelegation = {}; // event type -> count of listeners on window/document/body
    var orig = EventTarget.prototype.addEventListener;
    EventTarget.prototype.addEventListener = function (type, listener, options) {
      try {
        var set = registry.get(this);
        if (!set) { set = {}; registry.set(this, set); }
        set[type] = (set[type] || 0) + 1;
        if (this === window || this === document || (document.body && this === document.body) ||
            this === document.documentElement) {
          window.__dlcDelegation[type] = (window.__dlcDelegation[type] || 0) + 1;
        }
      } catch (e) { /* ignore */ }
      return orig.call(this, type, listener, options);
    };
    // Also catch property-assigned handlers on window/document (onclick = ...) as delegation.
    window.__dlcErrors = [];
    window.addEventListener('error', function (ev) {
      try { window.__dlcErrors.push(String(ev.message || ev.error || 'script error')); } catch (e) { /* ignore */ }
    });
    window.addEventListener('unhandledrejection', function (ev) {
      // async apps fail here, not in 'error': surface it so a silent fetch().then() crash is visible in eval_results.json
      try { var r = ev.reason; window.__dlcErrors.push('unhandled rejection: ' + (r && (r.stack || r.message) || String(r))); } catch (e) { /* ignore */ }
    });
  }

  function listenersOf(el) {
    var set = window.__dlcListeners && window.__dlcListeners.get(el);
    return set || {};
  }

  // ------------------------------------------------------------------ helpers
  function sleep(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }

  function isVisible(el) {
    if (!el || !el.isConnected) return false;
    if (el.hidden) return false;
    if (el.getAttribute && el.getAttribute('aria-hidden') === 'true') return false;
    var cur = el;
    while (cur && cur.nodeType === 1) {
      var cs = window.getComputedStyle(cur);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
      if (cur.hidden) return false;
      cur = cur.parentElement;
    }
    var style = window.getComputedStyle(el);
    if (el.offsetParent === null && style.position !== 'fixed' && el.tagName !== 'BODY' && el.tagName !== 'HTML') {
      // Elements inside closed <details> and display:none ancestors land here.
      return false;
    }
    if (el.tagName !== 'BODY' && el.tagName !== 'HTML') {
      var rect = el.getBoundingClientRect();
      if (rect.width <= 0 || rect.height <= 0) return false;
    }
    return true;
  }

  function textOf(el) {
    if (!el) return '';
    var tag = el.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') {
      if (tag === 'SELECT' && el.selectedIndex >= 0) return (el.options[el.selectedIndex].text || el.value || '').trim();
      return String(el.value == null ? '' : el.value).trim();
    }
    return (el.innerText != null ? el.innerText : el.textContent || '').replace(/\s+/g, ' ').trim();
  }

  function queryAll(selector) {
    selector = String(selector || '').trim();
    if (selector.indexOf('text=') === 0) {
      var needle = selector.slice(5).trim().replace(/^["']|["']$/g, '').toLowerCase();
      var all = Array.prototype.slice.call(document.querySelectorAll('body *'));
      var cands = all.filter(function (e) {
        if (e.tagName === 'SCRIPT' || e.tagName === 'STYLE') return false;
        return (e.textContent || '').replace(/\s+/g, ' ').trim().toLowerCase().indexOf(needle) !== -1;
      });
      // innermost: drop candidates that contain another candidate
      return cands.filter(function (c) { return !cands.some(function (o) { return o !== c && c.contains(o); }); });
    }
    try { return Array.prototype.slice.call(document.querySelectorAll(selector)); }
    catch (e) { throw new Error('Invalid selector: ' + selector); }
  }

  function queryOne(selector, preferVisible) {
    var els = queryAll(selector);
    if (!els.length) return null;
    if (preferVisible) { var v = els.filter(isVisible); if (v.length) return v[0]; }
    return els[0];
  }

  function describe(el) {
    if (!el) return 'null';
    var t = el.getAttribute('data-testid');
    if (t) return '[data-testid=' + t + ']';
    if (el.id) return '#' + el.id;
    var txt = textOf(el);
    return el.tagName.toLowerCase() + (txt ? ' "' + txt.slice(0, 40) + '"' : '');
  }

  function setNativeValue(el, value) {
    var proto = el.tagName === 'TEXTAREA' ? HTMLTextAreaElement.prototype
      : el.tagName === 'SELECT' ? HTMLSelectElement.prototype : HTMLInputElement.prototype;
    var desc = Object.getOwnPropertyDescriptor(proto, 'value');
    if (desc && desc.set) desc.set.call(el, value); else el.value = value;
  }

  function fire(el, type, init) {
    var ev;
    if (/^key/.test(type)) ev = new KeyboardEvent(type, Object.assign({ bubbles: true, cancelable: true }, init || {}));
    else if (type === 'input') ev = new InputEvent('input', { bubbles: true, cancelable: true });
    else if (/^(click|mouse|pointer|dbl)/.test(type)) ev = new MouseEvent(type, { bubbles: true, cancelable: true, view: window });
    else ev = new Event(type, { bubbles: true, cancelable: true });
    return el.dispatchEvent(ev);
  }

  function selectOption(el, value) {
    var want = String(value).trim().toLowerCase();
    var opts = Array.prototype.slice.call(el.options);
    var hit = opts.find(function (o) { return o.value === String(value); }) ||
      opts.find(function (o) { return (o.text || '').trim().toLowerCase() === want; }) ||
      opts.find(function (o) { return (o.text || '').trim().toLowerCase().indexOf(want) !== -1; });
    if (!hit) throw new Error('No option matching "' + value + '" in ' + describe(el) + ' (options: ' +
      opts.map(function (o) { return o.text; }).join(', ') + ')');
    setNativeValue(el, hit.value);
    fire(el, 'input'); fire(el, 'change');
  }

  function slug(s) { return String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, ''); }

  // ------------------------------------------------------------------ visible text
  function visibleText() {
    var out = [];
    var seen = {};
    function push(s) {
      s = String(s || '').replace(/\s+/g, ' ').trim();
      if (s && !seen[s]) { seen[s] = 1; out.push(s); }
    }
    function walk(node) {
      if (node.nodeType === 3) { push(node.nodeValue); return; }
      if (node.nodeType !== 1) return;
      var tag = node.tagName;
      if (tag === 'SCRIPT' || tag === 'STYLE' || tag === 'TEMPLATE' || tag === 'NOSCRIPT') return;
      if (!isVisible(node) && tag !== 'BODY' && tag !== 'HTML') return;
      ['alt', 'title', 'aria-label', 'placeholder'].forEach(function (a) { if (node.hasAttribute(a)) push(node.getAttribute(a)); });
      if (tag === 'INPUT' && node.type !== 'password' && node.type !== 'hidden') push(node.value);
      for (var c = node.firstChild; c; c = c.nextSibling) walk(c);
    }
    walk(document.body || document.documentElement);
    push(document.title);
    return out.join('\n');
  }

  // ------------------------------------------------------------------ control audit
  var CONTROL_SELECTOR = 'button, a[href], [role=button], [role=tab], input[type=submit], input[type=button], ' +
    '.nav-item, .step-item, [data-action], summary';

  function hasAncestorListener(el, types) {
    var cur = el.parentElement;
    while (cur) {
      var l = listenersOf(cur);
      for (var i = 0; i < types.length; i++) if (l[types[i]]) return true;
      cur = cur.parentElement;
    }
    var d = window.__dlcDelegation || {};
    for (var j = 0; j < types.length; j++) if (d[types[j]]) return true;
    var dl = listenersOf(document), wl = listenersOf(window);
    for (var k = 0; k < types.length; k++) if (dl[types[k]] || wl[types[k]]) return true;
    return false;
  }

  function controlAudit() {
    var els = Array.prototype.slice.call(document.querySelectorAll(CONTROL_SELECTOR));
    var controls = [];
    els.forEach(function (el) {
      var tag = el.tagName.toLowerCase();
      var reason = '';
      var wired = false;
      var own = listenersOf(el);
      var inlineAttr = Array.prototype.slice.call(el.attributes).some(function (a) { return /^on\w+$/i.test(a.name); });
      var propHandler = HANDLER_EVENTS.some(function (t) { return typeof el['on' + t] === 'function'; });
      if (inlineAttr || propHandler) { wired = true; reason = 'inline handler'; }
      else if (HANDLER_EVENTS.some(function (t) { return own[t]; })) { wired = true; reason = 'addEventListener'; }
      else if (tag === 'a') {
        var href = (el.getAttribute('href') || '').trim();
        if (href && href !== '#' && !/^javascript:\s*(void\(0\)|;)?\s*$/i.test(href)) { wired = true; reason = 'navigates'; }
      }
      if (!wired && tag === 'summary' && el.parentElement && el.parentElement.tagName === 'DETAILS') { wired = true; reason = 'native details toggle'; }
      if (!wired && (tag === 'button' || tag === 'input')) {
        var type = (el.getAttribute('type') || (tag === 'button' ? 'submit' : '')).toLowerCase();
        var form = el.form || el.closest('form');
        if (type === 'submit' && form) {
          var fl = listenersOf(form);
          if (fl.submit || typeof form.onsubmit === 'function' || form.hasAttribute('onsubmit') || form.hasAttribute('action') ||
              (window.__dlcDelegation || {}).submit || listenersOf(document).submit) { wired = true; reason = 'form submit'; }
        }
        if (!wired && type === 'reset' && form) { wired = true; reason = 'native reset'; }
      }
      if (!wired && el.getAttribute('role') === 'tab' && el.closest('[role=tablist]')) {
        if (hasAncestorListener(el, ['click', 'keydown', 'pointerdown', 'mousedown'])) { wired = true; reason = 'delegated'; }
      }
      if (!wired && hasAncestorListener(el, ['click', 'pointerdown', 'mousedown', 'keydown', 'change', 'input'])) {
        wired = true; reason = 'delegated';
      }
      // Labels wrapping inputs are not controls; popover/dialog triggers via attributes are native.
      if (!wired && (el.hasAttribute('popovertarget') || el.hasAttribute('commandfor'))) { wired = true; reason = 'native invoker'; }
      if (wired && el.getAttribute('role') === 'tab' && el.hasAttribute('aria-controls')) {
        var ctrlId = el.getAttribute('aria-controls');
        if (ctrlId && !document.getElementById(ctrlId)) {
          wired = false;
          reason = 'tab aria-controls="#' + ctrlId + '" does not match any element in DOM';
        }
      }
      controls.push({
        selector: describe(el), tag: tag, text: textOf(el).slice(0, 60), visible: isVisible(el),
        hasHandler: wired, reason: wired ? reason : 'no click/submit/change handler, no inline handler, no navigation href, no delegated listener on an ancestor'
      });
    });
    return controls;
  }

  // ------------------------------------------------------------------ UX guardrail metrics (_shared/ux_guardrails.md)
  function uxMetrics() {
    var vis = function (sel) { return Array.prototype.slice.call(document.querySelectorAll(sel)).filter(isVisible); };
    var primaries = vis('.btn-primary, [data-emphasis=primary], button.primary, .button-primary, .md-filled-button');
    var tabs = vis('[role=tab], .nav-item');
    var inputs = vis('input:not([type=hidden]), select, textarea').filter(function (e) { return !e.closest('details'); });
    var containerSel = '[data-step], [data-view], [role=tabpanel], fieldset, form, section, main';
    var perContainer = {};
    inputs.forEach(function (inp) {
      var c = inp.closest(containerSel);
      var key = c ? describe(c) : 'document';
      perContainer[key] = (perContainer[key] || 0) + 1;
    });
    var maxInputs = 0, worst = 'document';
    Object.keys(perContainer).forEach(function (k) { if (perContainer[k] > maxInputs) { maxInputs = perContainer[k]; worst = k; } });
    var main = document.querySelector('main, .container, .app, #app, [data-view]');
    var maxWidth = main ? window.getComputedStyle(main).maxWidth : '';
    var rootStyle = window.getComputedStyle(document.documentElement);
    var hasGoogleCloudTokens = !!(rootStyle.getPropertyValue('--g-bg').trim() || rootStyle.getPropertyValue('--g-blue').trim());
    var surfaceMode = (document.body && document.body.getAttribute('data-surface-mode')) || '';
    var hasSemanticMain = !!document.querySelector('main');
    var hasSkipLink = !!document.querySelector('a[href="#main-content"], a[href^="#main"]');
    return {
      primaryVisible: primaries.length, primarySelectors: primaries.map(describe),
      tabsVisible: tabs.length, inputsVisibleMaxPerContainer: maxInputs, inputsWorstContainer: worst,
      mainMaxWidth: maxWidth,
      hasGoogleCloudTokens: hasGoogleCloudTokens,
      surfaceMode: surfaceMode,
      hasSemanticMain: hasSemanticMain,
      hasSkipLink: hasSkipLink
    };
  }

  // ------------------------------------------------------------------ a11y (in-DOM, complements the static lint)
  function a11yAudit() {
    var f = [];
    var html = document.documentElement;
    if (!html.getAttribute('lang')) f.push({ rule: 'html-lang', message: '<html> has no lang attribute' });
    var h1 = document.querySelectorAll('h1').length;
    if (h1 !== 1) f.push({ rule: 'single-h1', message: 'expected exactly one <h1>, found ' + h1 });
    Array.prototype.forEach.call(document.querySelectorAll('img'), function (img) {
      if (!img.hasAttribute('alt')) f.push({ rule: 'img-alt', message: describe(img) + ' missing alt' });
    });
    Array.prototype.forEach.call(document.querySelectorAll('input:not([type=hidden]):not([type=submit]):not([type=button]), select, textarea'), function (el) {
      var labelled = el.getAttribute('aria-label') || el.getAttribute('aria-labelledby') || el.closest('label') ||
        (el.id && document.querySelector('label[for="' + CSS.escape(el.id) + '"]')) || el.getAttribute('title');
      if (!labelled) f.push({ rule: 'form-label', message: describe(el) + ' has no label' });
    });
    Array.prototype.forEach.call(document.querySelectorAll('button, [role=button], a[href]'), function (el) {
      var name = textOf(el) || el.getAttribute('aria-label') || el.getAttribute('title') ||
        (el.querySelector('img[alt]') && el.querySelector('img[alt]').getAttribute('alt'));
      if (!name) f.push({ rule: 'accessible-name', message: describe(el) + ' has no accessible name' });
    });
    Array.prototype.forEach.call(document.querySelectorAll('[tabindex]'), function (el) {
      if (parseInt(el.getAttribute('tabindex'), 10) > 0) f.push({ rule: 'positive-tabindex', message: describe(el) + ' tabindex>0' });
    });
    return f;
  }

  // ------------------------------------------------------------------ step execution
  var EXPECT_TIMEOUT_MS = 1500;
  var POLL_MS = 50;

  function assertUntil(fn, timeoutMs) {
    // fn returns {ok, actual}; retries until ok or timeout; resolves with final probe.
    var deadline = Date.now() + (timeoutMs || EXPECT_TIMEOUT_MS);
    return new Promise(function (resolve) {
      (function loop() {
        var r;
        try { r = fn(); } catch (e) { r = { ok: false, actual: 'error: ' + (e && e.message || e) }; }
        if (r.ok || Date.now() >= deadline) return resolve(r);
        setTimeout(loop, POLL_MS);
      })();
    });
  }

  function need(step, el, selector) {
    if (!el) throw new Error('Element not found: ' + selector);
    return el;
  }

  function matchText(actual, step) {
    if (step.equals != null) return actual === String(step.equals);
    if (step.contains != null) return actual.toLowerCase().indexOf(String(step.contains).toLowerCase()) !== -1;
    if (step.matches != null) return new RegExp(step.matches, step.flags || 'i').test(actual);
    return actual.length > 0;
  }

  async function execStep(step) {
    var a = step.action;
    var sel = step.selector;
    var el, r;
    switch (a) {
      case 'goto':
        return { ok: true, actual: 'harness already loaded ' + location.href };
      case 'wait':
        await sleep(Number(step.ms || 100));
        return { ok: true };
      case 'setRole': {
        var value = String(step.value || step.role || '');
        var sw = document.querySelector('select[data-testid=role-switcher], select#role-switcher, select[name=role]');
        if (sw) { selectOption(sw, value); await sleep(60); return { ok: true, actual: 'role-switcher select -> ' + value }; }
        var btn = document.querySelector('[data-testid="role-' + slug(value) + '"]');
        if (!btn) {
          var cands = Array.prototype.slice.call(document.querySelectorAll('button, [role=tab], [role=button], a, label, input[type=radio]'));
          btn = cands.find(function (b) { return textOf(b).toLowerCase() === value.toLowerCase(); }) ||
            cands.find(function (b) { return textOf(b).toLowerCase().indexOf(value.toLowerCase()) !== -1 && textOf(b).length < value.length + 12; });
        }
        if (!btn) throw new Error('No role switcher found for role "' + value + '" (looked for select[data-testid=role-switcher], [data-testid=role-' + slug(value) + '], or a button/tab labelled "' + value + '")');
        if (btn.tagName === 'INPUT') { btn.checked = true; fire(btn, 'input'); fire(btn, 'change'); } else btn.click();
        await sleep(60);
        return { ok: true, actual: 'clicked ' + describe(btn) };
      }
      case 'fill': {
        el = need(step, queryOne(sel, true), sel);
        if (el.tagName === 'SELECT') { selectOption(el, step.value); return { ok: true }; }
        if (el.type === 'checkbox' || el.type === 'radio') {
          el.checked = !!step.value && step.value !== 'false';
          fire(el, 'input'); fire(el, 'change'); return { ok: true };
        }
        el.focus();
        setNativeValue(el, step.value == null ? '' : String(step.value));
        fire(el, 'input'); fire(el, 'change'); fire(el, 'keyup', { key: 'Unidentified' });
        return { ok: true, actual: 'value=' + el.value };
      }
      case 'select':
        el = need(step, queryOne(sel, true), sel);
        if (el.tagName !== 'SELECT') throw new Error(describe(el) + ' is not a <select>');
        selectOption(el, step.value);
        return { ok: true };
      case 'check':
      case 'uncheck':
        el = need(step, queryOne(sel, true), sel);
        el.checked = (a === 'check');
        fire(el, 'input'); fire(el, 'change');
        return { ok: true };
      case 'click': {
        el = need(step, queryOne(sel, true), sel);
        if (!isVisible(el)) {
          return { ok: false, actual: 'target element is not visible or has zero bounding box: ' + describe(el) };
        }
        if (el.scrollIntoView) el.scrollIntoView({ block: 'center', inline: 'center' });
        var before = document.body.innerHTML.length;
        el.click();
        await sleep(60);
        // Tab & navigation layout-shift verification: if clicking a [role="tab"] or [aria-controls] tab,
        // verify target panel has a non-zero bounding box and sibling tabpanels are hidden.
        var isTab = el.getAttribute('role') === 'tab';
        var panelId = el.getAttribute('aria-controls');
        if (isTab && panelId) {
          var targetPanel = document.getElementById(panelId);
          if (!targetPanel || !isVisible(targetPanel)) {
            return { ok: false, actual: 'tab click on ' + describe(el) + ' did not render controlled panel #' + panelId + ' with a non-zero bounding box' };
          }
          var tablist = el.closest('[role="tablist"]') || document;
          var sibTabs = Array.prototype.slice.call(tablist.querySelectorAll('[role="tab"][aria-controls]'));
          var stillVis = [];
          sibTabs.forEach(function (st) {
            var sid = st.getAttribute('aria-controls');
            if (sid && sid !== panelId) {
              var sp = document.getElementById(sid);
              if (sp && isVisible(sp)) stillVis.push('#' + sid);
            }
          });
          if (stillVis.length) {
            return { ok: false, actual: 'tab mutual exclusivity failed after clicking ' + describe(el) + ' — sibling panel(s) still visible: ' + stillVis.join(', ') };
          }
        }
        var box = el.getBoundingClientRect();
        return { ok: true, actual: (el.disabled ? 'target was disabled; ' : '') + 'bbox=' + Math.round(box.width) + 'x' + Math.round(box.height) + ' dom delta=' + (document.body.innerHTML.length - before) };
      }
      case 'pressKey': {
        el = sel ? need(step, queryOne(sel, true), sel) : (document.activeElement || document.body);
        var key = step.key || 'Enter';
        var init = { key: key, code: key.length === 1 ? 'Key' + key.toUpperCase() : key, keyCode: key === 'Enter' ? 13 : key === 'Escape' ? 27 : 0 };
        el.focus();
        var notPrevented = fire(el, 'keydown', init);
        fire(el, 'keypress', init);
        fire(el, 'keyup', init);
        if (notPrevented && key === 'Enter' && el.form && el.tagName === 'INPUT' && typeof el.form.requestSubmit === 'function') {
          var submitter = el.form.querySelector('button[type=submit], input[type=submit], button:not([type])');
          if (submitter) el.form.requestSubmit(submitter); else el.form.requestSubmit();
        }
        await sleep(60);
        return { ok: true };
      }
      case 'expectText':
        return assertUntil(function () {
          var e = queryOne(sel, true);
          if (!e) return { ok: false, actual: 'element not found: ' + sel };
          var t = textOf(e);
          return { ok: matchText(t, step), actual: t };
        });
      case 'expectVisible':
        return assertUntil(function () {
          var els = queryAll(sel);
          var v = els.some(isVisible);
          return { ok: v, actual: v ? 'visible' : els.length ? 'present but hidden (' + els.length + ')' : 'not in DOM' };
        });
      case 'expectHidden':
        return assertUntil(function () {
          var els = queryAll(sel);
          var vis = els.filter(isVisible);
          return { ok: vis.length === 0, actual: vis.length ? 'visible: ' + vis.map(describe).join(', ') + ' text="' + textOf(vis[0]) + '"' : 'hidden' };
        });
      case 'expectDisabled':
        return assertUntil(function () {
          var e = queryOne(sel, true);
          if (!e) return { ok: false, actual: 'element not found: ' + sel };
          var dis = !!e.disabled || e.getAttribute('aria-disabled') === 'true';
          return { ok: dis, actual: dis ? 'disabled' : 'enabled' };
        });
      case 'expectEnabled':
        return assertUntil(function () {
          var e = queryOne(sel, true);
          if (!e) return { ok: false, actual: 'element not found: ' + sel };
          var dis = !!e.disabled || e.getAttribute('aria-disabled') === 'true';
          return { ok: !dis, actual: dis ? 'disabled' : 'enabled' };
        });
      case 'expectCount':
        return assertUntil(function () {
          var n = queryAll(sel).filter(function (e) { return step.includeHidden ? true : isVisible(e); }).length;
          var ok = true;
          if (step.equals != null) ok = ok && n === Number(step.equals);
          if (step.min != null) ok = ok && n >= Number(step.min);
          if (step.max != null) ok = ok && n <= Number(step.max);
          return { ok: ok, actual: 'count=' + n };
        });
      case 'expectAttribute':
        return assertUntil(function () {
          var e = queryOne(sel, false);
          if (!e) return { ok: false, actual: 'element not found: ' + sel };
          var attrName = step.attribute || step.name;
          var v = e.getAttribute(attrName);
          var ok = step.equals != null ? v === String(step.equals) : step.contains != null ? (v || '').indexOf(step.contains) !== -1 : v != null;
          return { ok: ok, actual: attrName + '=' + JSON.stringify(v) };
        });
      case 'expectNoVisibleTextMatching': {
        var re = new RegExp(step.pattern, step.flags || '');
        var txt = visibleText();
        var m = re.exec(txt);
        return { ok: !m, actual: m ? 'matched "' + m[0] + '" near: ' + txt.slice(Math.max(0, m.index - 40), m.index + 60).replace(/\n/g, ' | ') : 'no match' };
      }
      default:
        throw new Error('Unknown step action: ' + a);
    }
  }

  function mergeControls(acc, controls) {
    controls.forEach(function (c) {
      var k = c.selector + '|' + c.text;
      if (!acc[k]) acc[k] = c; else if (!c.hasHandler) acc[k] = c;
    });
  }

  async function run(steps, opts) {
    opts = opts || {};
    var result = { status: 'PASS', failedStep: null, message: '', actual: '', steps: [], scriptErrors: [] };
    var textLines = {}; var controlsAcc = {}; var ux = null; var a11y = {};
    function snapshotState() {
      visibleText().split('\n').forEach(function (l) { textLines[l] = 1; });
      mergeControls(controlsAcc, controlAudit());
      var m = uxMetrics();
      if (!ux || m.primaryVisible > ux.primaryVisible || m.tabsVisible > ux.tabsVisible || m.inputsVisibleMaxPerContainer > ux.inputsVisibleMaxPerContainer) {
        ux = ux || m;
        ux = { primaryVisible: Math.max(ux.primaryVisible, m.primaryVisible), primarySelectors: m.primaryVisible >= ux.primaryVisible ? m.primarySelectors : ux.primarySelectors,
          tabsVisible: Math.max(ux.tabsVisible, m.tabsVisible), inputsVisibleMaxPerContainer: Math.max(ux.inputsVisibleMaxPerContainer, m.inputsVisibleMaxPerContainer),
          inputsWorstContainer: m.inputsVisibleMaxPerContainer >= ux.inputsVisibleMaxPerContainer ? m.inputsWorstContainer : ux.inputsWorstContainer, mainMaxWidth: m.mainMaxWidth };
      }
      a11yAudit().forEach(function (f) { a11y[f.rule + '|' + f.message] = f; });
    }
    await sleep(Number(opts.settleMs || 150));
    snapshotState();
    for (var i = 0; i < steps.length; i++) {
      var step = steps[i];
      var t0 = Date.now();
      var r;
      try { r = await execStep(step); }
      catch (e) { r = { ok: false, actual: (e && e.message) || String(e) }; }
      result.steps.push({ index: i, action: step.action, selector: step.selector || step.value || step.pattern || '', ok: !!r.ok, actual: r.actual || '', ms: Date.now() - t0 });
      if (/^(setRole|click|fill|select|check|uncheck|pressKey)$/.test(step.action)) { await sleep(40); snapshotState(); }
      if (!r.ok) {
        result.status = 'FAIL';
        result.failedStep = i;
        result.message = 'Step ' + i + ' (' + step.action + (step.selector ? ' ' + step.selector : '') + ') failed';
        result.actual = r.actual || '';
        break;
      }
    }
    snapshotState();
    result.visibleText = visibleText();
    result.visibleTextAllStates = Object.keys(textLines).join('\n');
    result.controls = Object.keys(controlsAcc).map(function (k) { return controlsAcc[k]; });
    result.ux = ux;
    result.a11y = Object.keys(a11y).map(function (k) { return a11y[k]; });
    result.scriptErrors = (window.__dlcErrors || []).slice(0, 10);
    result.finalUrl = location.href;
    return result;
  }

  window.__dlcInstallPrelude = installPrelude;
  window.__dlcRun = run;
  window.__dlcVisibleText = visibleText;
  window.__dlcControlAudit = controlAudit;
  window.__dlcA11y = a11yAudit;
  window.__dlcUx = uxMetrics;
})();
