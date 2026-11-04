/* Commercial Buyer Licensing — single-page UI (no framework, no build step).
 * Reads only ViewModels from the API (labels, masked identifiers, formatted amounts). The lifecycle table below is
 * the same as spec §3.3 / the backend STATE_TABLE: controls are rendered from (status, role) and the server re-checks. */
(function () {
  'use strict';

  var API_BASE = new URL('.', document.baseURI).href; // page is served by the backend, so the API is relative
  var ROLE_BUYER = 'Commercial Buyer';
  var ROLE_STAFF = 'Licensing Staff';
  var STATE_TABLE = [
    { from: 'DRAFT', trigger: 'SUBMIT', to: 'SUBMITTED', roles: [ROLE_BUYER] },
    { from: 'SUBMITTED', trigger: 'ISSUE', to: 'ISSUED', roles: [ROLE_STAFF] },
    { from: 'SUBMITTED', trigger: 'REJECT', to: 'REJECTED', roles: [ROLE_STAFF] }
  ];
  var MSG = {
    required: 'Enter the legal name, entity type, tax identifier and date of birth to continue.',
    taxFormat: 'Enter the tax identifier as NNN-NN-NNNN (Social-security number) or NN-NNNNNNN (employer identification number).',
    amounts: 'Enter amounts in dollars, for example 25000.00.',
    agentFields: "Enter the agent's first name, last name and date of birth.",
    reason: 'Enter a rejection reason of at least 10 characters so the buyer knows what to correct.',
    docName: 'Enter the document name to attach it.',
    feeTotal: "Enter the quarter's total purchase price in dollars.",
    lookup: 'Enter an application number such as APP-2026-000004.'
  };

  var state = {
    role: ROLE_BUYER, buyerTab: 'new-application', staffTab: 'review-queue', step: 1,
    buyer: {}, dupAcknowledged: false, currentApp: null, myIds: loadIds(), myApp: null,
    queueFilter: 'SUBMITTED', reviewApp: null
  };

  // ------------------------------------------------------------------ helpers
  function $(sel, root) { return (root || document).querySelector(sel); }
  function $$(sel, root) { return Array.prototype.slice.call((root || document).querySelectorAll(sel)); }
  function t(id, root) { return $('[data-testid="' + id + '"]', root); }
  function visibleView() { return state.role === ROLE_STAFF ? $('[data-view="staff"]') : $('[data-view="buyer"]'); }
  function allowed(status, role) {
    return STATE_TABLE.filter(function (r) { return r.from === status && r.roles.indexOf(role) !== -1; }).map(function (r) { return r.trigger; });
  }
  function loadIds() {
    try { return JSON.parse(window.localStorage.getItem('tbl.myApplications') || '[]'); } catch (e) { return []; }
  }
  function saveIds() {
    try { window.localStorage.setItem('tbl.myApplications', JSON.stringify(state.myIds)); } catch (e) { /* in-memory only */ }
  }
  function parseAmount(v) {
    var s = String(v == null ? '' : v).replace(/[$,\s]/g, '');
    if (s === '') return null;
    if (!/^-?\d+(\.\d+)?$/.test(s)) return NaN;
    return Number(s);
  }
  function cents(n) { return Math.round(n * 100); }
  function roundHalfUp(x) { return Math.floor(x + 0.5); }
  function requiredBondCents(prior) { return Math.max(100000, roundHalfUp(cents(prior) / 10)); } // BR-01
  function feeCents(total) { return roundHalfUp(cents(total) * 4 / 100); }                    // BR-03
  function money(c) { return '$' + (c / 100).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }); }
  function shortfallText(prior, bond) {
    var req = requiredBondCents(prior); var short = req - cents(bond);
    if (short <= 0) return 'Bond is sufficient';
    return 'Bond amount is below the required bond of ' + money(req) + '. Increase the bond by ' + money(short) + ' before submitting.';
  }
  function when(iso) { return iso ? String(iso).replace('T', ' ').replace('Z', '') : '—'; }
  function esc(s) { return String(s == null ? '' : s).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); }

  function api(method, path, body) {
    var headers = { 'Accept': 'application/json', 'X-Role': state.role, 'X-Actor': state.role === ROLE_STAFF ? 'Commercial Licensing Desk' : (state.buyer.legalName || 'Commercial Buyer') };
    var init = { method: method, headers: headers };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(API_BASE + path.replace(/^\//, ''), init).then(function (res) {
      return res.text().then(function (txt) {
        var data = null; try { data = txt ? JSON.parse(txt) : null; } catch (e) { data = null; }
        if (!res.ok) { var err = new Error((data && data.message) || 'Something went wrong. Please try again.'); err.status = res.status; throw err; }
        return data;
      });
    });
  }

  function banner(msg, kind) {
    var el = $('.banner', visibleView());
    if (!el) return;
    if (!msg) { el.hidden = true; el.textContent = ''; el.className = 'banner'; return; }
    el.className = 'banner' + (kind ? ' ' + kind : '');
    el.textContent = msg;
    el.hidden = false;
    el.setAttribute('tabindex', '-1');
    el.focus({ preventScroll: true });
  }
  function clearInvalid(root) { $$('[aria-invalid]', root).forEach(function (el) { el.removeAttribute('aria-invalid'); el.removeAttribute('aria-describedby'); }); }
  function markInvalid(el) { if (el) { el.setAttribute('aria-invalid', 'true'); el.setAttribute('aria-describedby', $('.banner', visibleView()).id); } }
  function setBadge(el, status) {
    if (!el) return;
    el.textContent = status.label; el.setAttribute('data-status', status.code);
  }

  // ------------------------------------------------------------------ role & tabs
  function applyRole() {
    var staff = state.role === ROLE_STAFF;
    $('[data-view="buyer"]').hidden = staff;
    $('[data-view="staff"]').hidden = !staff;
    banner('');
    if (staff) { loadQueue(); var h = t('staff-view-title'); if (h) h.focus(); }
    else { var hb = t('buyer-view-title'); if (hb) hb.focus(); }
  }
  function selectTab(view, name) {
    $$('[role="tab"]', view).forEach(function (tab) {
      var on = tab.getAttribute('data-tab') === name;
      tab.setAttribute('aria-selected', on ? 'true' : 'false');
      tab.tabIndex = on ? 0 : -1;
    });
    $$('[data-panel]', view).forEach(function (p) { p.hidden = p.getAttribute('data-panel') !== name; });
    banner('');
    var heading = $('[data-panel="' + name + '"] h3', view);
    if (heading) { heading.setAttribute('tabindex', '-1'); heading.focus({ preventScroll: true }); }
    if (name === 'my-applications') renderMyList();
    if (name === 'review-queue') loadQueue();
  }

  // ------------------------------------------------------------------ buyer: steps
  function showStep(n, keepFocus) {
    state.step = n;
    $$('[data-step]').forEach(function (f) { f.hidden = Number(f.getAttribute('data-step')) !== n; });
    $$('[data-step-chip]').forEach(function (c) {
      var k = Number(c.getAttribute('data-step-chip'));
      c.className = k === n ? 'active' : (k < n ? 'done' : '');
    });
    var h = $('[data-step="' + n + '"] h3'); if (h && !keepFocus) { h.setAttribute('tabindex', '-1'); h.focus({ preventScroll: true }); }
    if (n === 4) renderSummary();
  }
  function taxIdRaw() {
    var el = t('buyer-tax-id');
    return el.dataset.masked === '1' ? (el.dataset.raw || '') : el.value.trim();
  }
  function maskTaxId(el) {
    var raw = el.value.trim();
    var kind = t('buyer-tax-id-kind').value;
    var ok = kind === 'SSN' ? /^\d{3}-\d{2}-\d{4}$/.test(raw) : /^\d{2}-\d{7}$/.test(raw);
    if (!ok) return;
    el.dataset.raw = raw; el.dataset.masked = '1';
    el.value = kind === 'SSN' ? '***-**-' + raw.slice(-4) : '**-***' + raw.slice(-4);
  }
  function step1Continue() {
    var form = $('[data-step="1"]'); clearInvalid(form); banner('');
    var legal = t('buyer-legal-name').value.trim(), entity = t('buyer-entity-type').value, kind = t('buyer-tax-id-kind').value;
    var raw = taxIdRaw(), dob = t('buyer-date-of-birth').value;
    if (!legal || !entity || !raw || !dob) {
      [['buyer-legal-name', legal], ['buyer-entity-type', entity], ['buyer-tax-id', raw], ['buyer-date-of-birth', dob]].forEach(function (p) { if (!p[1]) markInvalid(t(p[0])); });
      banner(MSG.required); return;
    }
    var ok = kind === 'SSN' ? /^\d{3}-\d{2}-\d{4}$/.test(raw) : /^\d{2}-\d{7}$/.test(raw);
    if (!ok) { markInvalid(t('buyer-tax-id')); banner(MSG.taxFormat); return; }
    state.buyer = { legalName: legal, businessName: t('buyer-business-name').value.trim(), entityType: entity, taxIdKind: kind, taxId: raw, dateOfBirth: dob,
      email: t('buyer-email').value.trim(), phone: t('buyer-phone').value.trim(), city: t('buyer-city').value.trim(), stateCode: t('buyer-state').value.trim() };
    var notice = t('duplicate-notice');
    if (state.dupAcknowledged) { notice.hidden = true; showStep(2); return; }
    api('GET', '/api/buyers/duplicate-check?legalName=' + encodeURIComponent(legal) + '&dateOfBirth=' + encodeURIComponent(dob)).then(function (r) {
      if (r && r.possibleDuplicate) {
        notice.textContent = r.notice + '. Check your details, then press Continue again to proceed.';
        notice.hidden = false; state.dupAcknowledged = true;
      } else { notice.hidden = true; showStep(2); }
    }).catch(function (e) { banner(e.message); });
  }
  function liveBond() {
    var prior = parseAmount(t('prior-year-purchases').value), bond = parseAmount(t('bond-amount').value);
    var reqEl = t('required-bond'), chk = t('bond-check');
    var p = (prior === null || isNaN(prior) || prior < 0) ? 0 : prior;
    reqEl.textContent = money(requiredBondCents(p));
    if (bond === null || isNaN(bond) || bond < 0) { chk.textContent = 'Enter the bond amount to check it against the required bond.'; chk.className = 'calc'; return; }
    var txt = shortfallText(p, bond);
    chk.textContent = txt; chk.className = 'calc ' + (txt === 'Bond is sufficient' ? 'ok' : 'short');
  }
  function saveDraft() {
    var form = $('[data-step="2"]'); clearInvalid(form); banner('');
    var prior = parseAmount(t('prior-year-purchases').value), bond = parseAmount(t('bond-amount').value);
    if (prior === null) prior = 0;
    if (bond === null) bond = 0;
    if (isNaN(prior) || isNaN(bond) || prior < 0 || bond < 0) { markInvalid(isNaN(bond) || bond < 0 ? t('bond-amount') : t('prior-year-purchases')); banner(MSG.amounts); return; }
    var body = Object.assign({}, state.buyer, { licenseYear: Number(t('license-year').value), priorYearPurchases: prior, bondAmount: bond,
      bondSuretyName: t('bond-surety-name').value.trim(), bondNumber: t('bond-number').value.trim(), bondExpiry: t('bond-expiry').value || undefined });
    var req = state.currentApp ? api('PUT', '/api/applications/' + state.currentApp.applicationId, body) : api('POST', '/api/applications', body);
    req.then(function (vm) {
      state.currentApp = vm;
      if (state.myIds.indexOf(vm.applicationId) === -1) { state.myIds.push(vm.applicationId); saveIds(); }
      renderCurrent(); showStep(3); renderRoster(t('agent-roster', $('[data-step="3"]')), vm, t('agent-notice', $('[data-step="3"]')));
    }).catch(function (e) { banner(e.message); });
  }
  function renderCurrent() {
    var card = t('current-application-card'); var vm = state.currentApp;
    if (!vm) { card.hidden = true; return; }
    card.hidden = false; t('application-number').textContent = vm.applicationNumber; setBadge(t('application-status'), vm.status);
  }
  function renderSummary() {
    var vm = state.currentApp, dl = t('review-summary');
    if (!vm) { dl.innerHTML = '<dt>Application</dt><dd>Save the draft in step 2 first.</dd>'; return; }
    var rows = [['Buyer', vm.buyer.legalName], ['Entity type', vm.buyer.entityTypeLabel], ['Tax identifier', vm.buyer.maskedTaxId], ['Licence year', vm.licenseYear],
      ['Prior-year purchases', money(cents(vm.priorYearPurchases))], ['Required bond', money(cents(vm.requiredBondAmount))], ['Bond amount', money(cents(vm.bondAmount))],
      ['Bond check', vm.bondCheck], ['Agents', vm.agents.entries.map(function (a) { return a.fullName + ' (' + a.relationshipLabel + ')'; }).join(', ')],
      ['Documents', vm.documents.length ? vm.documents.map(function (d) { return d.fileName; }).join(', ') : 'None attached']];
    dl.innerHTML = rows.map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>'; }).join('');
  }
  function refreshCurrent() {
    if (!state.currentApp) return Promise.resolve(null);
    return api('GET', '/api/applications/' + state.currentApp.applicationId).then(function (vm) { state.currentApp = vm; renderCurrent(); return vm; });
  }
  function submitApplication(vm, onDone) {
    banner('');
    api('POST', '/api/applications/' + vm.applicationId + '/submit').then(function (updated) {
      onDone(updated);
      banner('Application ' + updated.applicationNumber + ' submitted. Licensing staff will review it; follow its progress under My applications.', 'success');
    }).catch(function (e) { banner(e.message); });
  }

  // ------------------------------------------------------------------ roster (shared by buyer step 3, buyer detail and staff review)
  function rosterEditable(vm) {
    if (!vm) return false;
    return state.role === ROLE_BUYER ? vm.status.code === 'DRAFT' : (vm.status.code === 'SUBMITTED' || vm.status.code === 'ISSUED');
  }
  function renderRoster(ul, vm, noticeEl) {
    if (!ul) return;
    var editable = rosterEditable(vm);
    ul.innerHTML = vm.agents.entries.map(function (a) {
      return '<li data-testid="agent-row" data-agent-id="' + a.agentId + '"><span><strong>' + esc(a.fullName) + '</strong>' +
        (a.suspended ? ' <span class="tag suspended">Suspended</span>' : '') + (a.cardPrinted ? ' <span class="tag printed">Card printed</span>' : '') + '</span>' +
        '<span><span class="tag' + (a.isOwner ? ' owner' : '') + '">' + esc(a.relationshipLabel) + '</span>' +
        (!a.isOwner && editable ? ' <button type="button" class="btn-secondary btn-small" data-action="remove-agent" data-agent-id="' + a.agentId + '" data-testid="remove-agent-btn">Remove</button>' : '') +
        '</span></li>';
    }).join('');
    if (noticeEl) {
      if (vm.agents.notice) { noticeEl.textContent = vm.agents.notice; noticeEl.hidden = false; } else { noticeEl.hidden = true; noticeEl.textContent = ''; }
    }
    var form = ul.parentElement && $('fieldset.inline-form', ul.parentElement);
    if (form) form.hidden = !editable;
  }
  function contextApp(container) {
    return container.closest('[data-testid="review-panel"]') ? state.reviewApp : state.currentApp;
  }
  function addAgent(btn) {
    var box = btn.closest('fieldset'); var panel = btn.closest('[data-testid="review-panel"]') || btn.closest('[data-step="3"]');
    var vm = contextApp(btn); var noticeEl = t('agent-notice', panel);
    var first = t('agent-first-name', box).value.trim(), last = t('agent-last-name', box).value.trim(), dob = t('agent-date-of-birth', box).value;
    function note(msg) { noticeEl.textContent = msg; noticeEl.hidden = false; }
    if (!vm) { note('Save the draft in step 2 before adding agents.'); return; }
    if (!first || !last || !dob) { note(MSG.agentFields); return; }
    api('POST', '/api/applications/' + vm.applicationId + '/agents', { firstName: first, lastName: last, dateOfBirth: dob }).then(function (updated) {
      if (panel.matches('[data-testid="review-panel"]')) { state.reviewApp = updated; renderReview(); } else { state.currentApp = updated; }
      renderRoster(t('agent-roster', panel), updated, noticeEl);
      t('agent-first-name', box).value = ''; t('agent-last-name', box).value = ''; t('agent-date-of-birth', box).value = '';
    }).catch(function (e) { note(e.message); });
  }
  function removeAgent(btn) {
    var panel = btn.closest('[data-testid="review-panel"]') || btn.closest('[data-step="3"]');
    var vm = contextApp(btn); var noticeEl = t('agent-notice', panel);
    api('DELETE', '/api/applications/' + vm.applicationId + '/agents/' + btn.getAttribute('data-agent-id')).then(function (updated) {
      if (panel.matches('[data-testid="review-panel"]')) { state.reviewApp = updated; renderReview(); } else { state.currentApp = updated; }
      renderRoster(t('agent-roster', panel), updated, noticeEl);
    }).catch(function (e) { noticeEl.textContent = e.message; noticeEl.hidden = false; });
  }

  // ------------------------------------------------------------------ buyer: my applications
  function renderMyList() {
    var ul = t('my-applications-list'), empty = t('my-applications-empty');
    if (!state.myIds.length) { ul.innerHTML = ''; empty.hidden = false; return; }
    api('GET', '/api/applications?ids=' + state.myIds.join(',')).then(function (rows) {
      empty.hidden = rows.length > 0;
      ul.innerHTML = rows.map(function (r) {
        return '<li data-testid="my-app-row"><span><strong>' + esc(r.applicationNumber) + '</strong> · ' + esc(r.buyerName) + ' · <span class="status-badge" data-status="' + esc(r.status.code) + '">' + esc(r.status.label) + '</span></span>' +
          '<button type="button" class="btn-secondary btn-small" data-action="open-my-app" data-id="' + r.applicationId + '" data-testid="open-my-app-btn">Open</button></li>';
      }).join('');
    }).catch(function (e) { banner(e.message); });
  }
  function parseAppNumber(v) { var m = String(v || '').match(/(\d+)\s*$/); return m ? Number(m[1]) : null; }
  function openMyApp(id) {
    banner('');
    api('GET', '/api/applications/' + id).then(function (vm) { state.myApp = vm; renderMyApp(); }).catch(function (e) { banner(e.message); });
  }
  function timelineHtml(history) {
    return history.map(function (h) {
      var line = esc(h.actionLabel) + (h.toStatusLabel ? ' — ' + esc(h.toStatusLabel) : '');
      return '<li data-testid="timeline-item"><strong>' + line + '</strong><span class="caption">' + esc(when(h.occurredAt)) + ' · ' + esc(h.actorRole) + '</span>' + (h.reason ? '<em>' + esc(h.reason) + '</em>' : '') + '</li>';
    }).join('');
  }
  function documentsHtml(docs) {
    return docs.map(function (d) { return '<li data-testid="document-item"><span>' + esc(d.fileName) + ' (' + esc(d.typeLabel) + ', ' + esc(d.sizeLabel) + ')</span></li>'; }).join('');
  }
  function feeReportsHtml(reports) {
    return reports.map(function (r) { return '<li data-testid="fee-report-item"><span>' + esc(r.summary) + '</span></li>'; }).join('');
  }
  function renderMyApp() {
    var vm = state.myApp, sec = t('my-app-detail');
    if (!vm) { sec.hidden = true; return; }
    sec.hidden = false;
    t('my-app-number').textContent = vm.applicationNumber; setBadge(t('my-app-status'), vm.status);
    t('my-app-license-row').hidden = !vm.licenseNumber; t('my-app-license-number').textContent = vm.licenseNumber || '';
    t('my-app-decision-row').hidden = !vm.decisionReason; t('my-app-decision-reason').textContent = vm.decisionReason || '';
    t('my-app-summary').innerHTML = [['Buyer', vm.buyer.legalName], ['Licence year', vm.licenseYear], ['Required bond', money(cents(vm.requiredBondAmount))], ['Bond amount', money(cents(vm.bondAmount))], ['Bond check', vm.bondCheck],
      ['Agents', vm.agents.entries.map(function (a) { return a.fullName + ' (' + a.relationshipLabel + ')'; }).join(', ')]]
      .map(function (r) { return '<dt>' + esc(r[0]) + '</dt><dd>' + esc(r[1]) + '</dd>'; }).join('');
    var actions = t('my-app-actions');
    actions.innerHTML = allowed(vm.status.code, state.role).indexOf('SUBMIT') !== -1 && (vm.allowedTriggers || []).indexOf('SUBMIT') !== -1
      ? '<button type="button" class="btn-primary" data-action="submit-my-app" data-testid="submit-application-btn">Submit application</button>' : '';
    t('status-timeline').innerHTML = timelineHtml(vm.history);
    t('document-list', sec).innerHTML = documentsHtml(vm.documents);
    t('documents-empty', sec).hidden = vm.documents.length > 0;
    t('document-form').hidden = vm.status.code !== 'DRAFT';
    t('fee-report-list', sec).innerHTML = feeReportsHtml(vm.feeReports);
    t('fee-reports-empty', sec).hidden = vm.feeReports.length > 0;
    t('fee-report-form').hidden = vm.status.code !== 'ISSUED';
    var h = t('my-app-heading') || $('#my-app-heading'); if (h) h.focus({ preventScroll: true });
  }
  function addDocument() {
    banner(''); var vm = state.myApp; if (!vm) return;
    var name = t('document-name').value.trim(), type = t('document-type').value, size = parseInt(t('document-size').value, 10);
    if (!name) { markInvalid(t('document-name')); banner(MSG.docName); return; }
    api('POST', '/api/applications/' + vm.applicationId + '/documents', { fileName: name, contentType: type, sizeBytes: isNaN(size) ? 0 : size })
      .then(function () { t('document-name').value = ''; t('document-size').value = ''; return openMyApp(vm.applicationId); })
      .then(function () { banner('Document attached.', 'success'); }).catch(function (e) { banner(e.message); });
  }
  function liveFee(inputEl, outEl) {
    var v = parseAmount(inputEl.value); outEl.textContent = money(v === null || isNaN(v) || v < 0 ? 0 : feeCents(v));
  }
  function recordFeeReport() {
    banner(''); var vm = state.myApp; if (!vm) return;
    var total = parseAmount(t('fee-purchase-total').value);
    if (total === null || isNaN(total) || total < 0) { markInvalid(t('fee-purchase-total')); banner(MSG.feeTotal); return; }
    api('POST', '/api/applications/' + vm.applicationId + '/fee-reports', { quarter: t('fee-quarter').value, purchaseTotal: total })
      .then(function () { t('fee-purchase-total').value = ''; t('fee-due').textContent = '$0.00'; return openMyApp(vm.applicationId); })
      .then(function () { banner('Quarterly report recorded.', 'success'); }).catch(function (e) { banner(e.message); });
  }

  // ------------------------------------------------------------------ staff: queue & review
  function loadQueue() {
    var filter = t('queue-status-filter').value; state.queueFilter = filter;
    api('GET', '/api/applications' + (filter ? '?status=' + filter : '')).then(function (rows) {
      var body = t('queue-body'), empty = t('queue-empty'), table = t('queue-table');
      empty.hidden = rows.length > 0; table.hidden = rows.length === 0;
      body.innerHTML = rows.map(function (r) {
        return '<tr data-testid="queue-row" data-id="' + r.applicationId + '"><td><strong>' + esc(r.applicationNumber) + '</strong>' + (r.licenseNumber ? '<br><span class="caption">' + esc(r.licenseNumber) + '</span>' : '') + '</td>' +
          '<td>' + esc(r.buyerName) + '</td><td>' + esc(r.licenseYear) + '</td><td><span class="status-badge" data-status="' + esc(r.status.code) + '">' + esc(r.status.label) + '</span></td>' +
          '<td>' + esc(r.bondCheck === 'Sufficient' ? 'Sufficient' : 'Shortfall') + '</td><td>' + esc(r.submittedAt ? when(r.submittedAt).slice(0, 10) : 'Not submitted') + '</td>' +
          '<td><button type="button" class="btn-secondary btn-small" data-action="open-application" data-id="' + r.applicationId + '" data-testid="open-application-btn" aria-label="Open ' + esc(r.applicationNumber) + '">Open</button></td></tr>';
      }).join('');
    }).catch(function (e) { banner(e.message); });
  }
  function openReview(id) {
    banner('');
    api('GET', '/api/applications/' + id).then(function (vm) {
      state.reviewApp = vm; t('queue-section').hidden = true; renderReview();
      var h = $('#review-heading'); if (h) h.focus({ preventScroll: true });
    }).catch(function (e) { banner(e.message); });
  }
  function renderReview() {
    var vm = state.reviewApp, panel = t('review-panel');
    if (!vm) { panel.hidden = true; return; }
    panel.hidden = false;
    t('review-application-number').textContent = vm.applicationNumber; setBadge(t('review-status'), vm.status);
    t('review-license-row').hidden = !vm.licenseNumber; t('review-license-number').textContent = vm.licenseNumber || '';
    t('review-decision-row').hidden = !vm.decisionReason; t('review-decision-reason').textContent = vm.decisionReason || '';
    t('review-buyer-name').textContent = vm.buyer.legalName; t('review-entity-type').textContent = vm.buyer.entityTypeLabel;
    t('review-tax-id').textContent = vm.buyer.maskedTaxId; t('review-date-of-birth').textContent = vm.buyer.dateOfBirth || '—';
    t('review-buyer-standing').textContent = vm.buyer.suspensionLabel + (vm.buyer.underInvestigation ? ' · Under investigation' : '');
    t('review-prior-purchases').textContent = money(cents(vm.priorYearPurchases)); t('review-required-bond').textContent = money(cents(vm.requiredBondAmount));
    t('review-bond-amount').textContent = money(cents(vm.bondAmount)); t('review-bond-check').textContent = vm.bondCheck; t('review-surety').textContent = (vm.bondSuretyName || '—') + (vm.bondNumber ? ' · ' + vm.bondNumber : '');
    renderRoster(t('agent-roster', panel), vm, t('agent-notice', panel));
    t('document-list', panel).innerHTML = documentsHtml(vm.documents);
    t('documents-empty', panel).hidden = vm.documents.length > 0;
    t('fee-report-list', panel).innerHTML = feeReportsHtml(vm.feeReports);
    t('fee-reports-empty', panel).hidden = vm.feeReports.length > 0;
    var triggers = allowed(vm.status.code, state.role);
    t('decision-section').hidden = !(triggers.indexOf('ISSUE') !== -1 || triggers.indexOf('REJECT') !== -1);
    t('print-section').hidden = vm.status.code !== 'ISSUED';
    t('no-decision-note').hidden = !(triggers.length === 0 && vm.status.code !== 'ISSUED');
    t('audit-history').innerHTML = timelineHtml(vm.history);
  }
  function decide(trigger) {
    banner(''); var vm = state.reviewApp; if (!vm) return;
    var body = {};
    if (trigger === 'REJECT') {
      var reason = t('reject-reason').value.trim();
      if (reason.length < 10) { markInvalid(t('reject-reason')); banner(MSG.reason); return; }
      body.reason = reason;
    }
    api('POST', '/api/applications/' + vm.applicationId + '/' + (trigger === 'ISSUE' ? 'issue' : 'reject'), body).then(function (updated) {
      state.reviewApp = updated; renderReview();
      banner(trigger === 'ISSUE' ? 'Licence ' + updated.licenseNumber + ' issued to ' + updated.buyerName + '.' : 'Application ' + updated.applicationNumber + ' rejected; the buyer can see the reason.', 'success');
    }).catch(function (e) { banner(e.message); });
  }
  function print(kind) {
    banner(''); var vm = state.reviewApp; if (!vm) return;
    api('POST', '/api/applications/' + vm.applicationId + '/prints', { kind: kind }).then(function (updated) {
      state.reviewApp = updated; renderReview(); banner(updated.agents.notice + '.', 'success');
    }).catch(function (e) { banner(e.message); });
  }

  // ------------------------------------------------------------------ staff: registries
  function searchBuyers() {
    banner('');
    api('GET', '/api/buyers?q=' + encodeURIComponent(t('buyer-search').value.trim())).then(function (rows) {
      t('buyer-results-empty').hidden = rows.length > 0;
      t('buyer-results').innerHTML = rows.map(function (b) {
        return '<li data-testid="buyer-result-row" data-id="' + b.buyerId + '"><span><strong>' + esc(b.legalName) + '</strong> · ' + esc(b.maskedTaxId) + ' · ' + esc(b.city || '') +
          ' · <span class="tag ' + (b.suspended ? 'suspended' : 'active') + '" data-testid="buyer-standing">' + esc(b.suspensionLabel) + '</span>' + (b.underInvestigation ? ' <span class="tag">Under investigation</span>' : '') +
          ' <span class="caption">' + b.applicationCount + ' application' + (b.applicationCount === 1 ? '' : 's') + '</span></span>' +
          '<button type="button" class="btn-secondary btn-small" data-action="toggle-buyer" data-id="' + b.buyerId + '" data-next="' + (b.suspended ? 'false' : 'true') + '" data-testid="toggle-buyer-suspension-btn">' + (b.suspended ? 'Reinstate' : 'Suspend') + '</button></li>';
      }).join('');
    }).catch(function (e) { banner(e.message); });
  }
  function searchAgents() {
    banner('');
    api('GET', '/api/agents?q=' + encodeURIComponent(t('agent-search').value.trim())).then(function (rows) {
      t('agent-results-empty').hidden = rows.length > 0;
      t('agent-results').innerHTML = rows.map(function (a) {
        return '<li data-testid="agent-result-row" data-id="' + a.agentId + '"><span><strong>' + esc(a.fullName) + '</strong> · born ' + esc(a.dateOfBirth) +
          ' · <span class="tag ' + (a.suspended ? 'suspended' : 'active') + '" data-testid="agent-standing">' + esc(a.suspensionLabel) + '</span>' +
          ' · <span data-testid="agent-current-license">' + esc(a.currentLicenseNumber ? 'Current licence ' + a.currentLicenseNumber : 'No current licence') + '</span></span>' +
          '<button type="button" class="btn-secondary btn-small" data-action="toggle-agent" data-id="' + a.agentId + '" data-next="' + (a.suspended ? 'false' : 'true') + '" data-testid="toggle-agent-suspension-btn">' + (a.suspended ? 'Reinstate' : 'Suspend') + '</button></li>';
      }).join('');
    }).catch(function (e) { banner(e.message); });
  }
  function toggleSuspension(kind, btn) {
    var next = btn.getAttribute('data-next') === 'true';
    api('POST', '/api/' + (kind === 'buyer' ? 'buyers' : 'agents') + '/' + btn.getAttribute('data-id') + '/suspension', { suspended: next, reason: next ? 'Suspended by licensing staff' : 'Reinstated by licensing staff' })
      .then(function () { banner((next ? 'Suspended. ' : 'Reinstated. ') + 'The registry has been updated.', 'success'); return kind === 'buyer' ? searchBuyers() : searchAgents(); })
      .catch(function (e) { banner(e.message); });
  }

  // ------------------------------------------------------------------ events (delegated)
  document.addEventListener('click', function (ev) {
    var tab = ev.target.closest('[role="tab"]');
    if (tab) { var view = tab.closest('[data-view]'); if (view.getAttribute('data-view') === 'staff') state.staffTab = tab.getAttribute('data-tab'); else state.buyerTab = tab.getAttribute('data-tab'); selectTab(view, tab.getAttribute('data-tab')); return; }
    var btn = ev.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    if (btn.tagName === 'BUTTON' && btn.type === 'submit') return; // handled by the form's submit event
    runAction(action, btn, ev);
  });
  document.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var btn = $('button[type="submit"][data-action]', ev.target);
    if (btn) runAction(btn.getAttribute('data-action'), btn, ev);
  });
  function runAction(action, btn) {
    switch (action) {
      case 'step1-continue': step1Continue(); break;
      case 'save-draft': saveDraft(); break;
      case 'step-back': showStep(Number(btn.getAttribute('data-to'))); break;
      case 'add-agent': addAgent(btn); break;
      case 'remove-agent': removeAgent(btn); break;
      case 'step3-continue': refreshCurrent().then(function () { showStep(4); }); break;
      case 'submit-application':
        if (!state.currentApp) { banner('Save the draft in step 2 before submitting.'); break; }
        submitApplication(state.currentApp, function (u) { state.currentApp = u; renderCurrent(); renderSummary(); $('[data-step="4"] [data-testid="submit-application-btn"]').hidden = u.status.code !== 'DRAFT'; });
        break;
      case 'lookup': {
        var id = parseAppNumber(t('lookup-application-number').value);
        if (!id) { markInvalid(t('lookup-application-number')); banner(MSG.lookup); break; }
        openMyApp(id); break;
      }
      case 'open-my-app': openMyApp(Number(btn.getAttribute('data-id'))); break;
      case 'submit-my-app': submitApplication(state.myApp, function (u) { state.myApp = u; renderMyApp(); }); break;
      case 'add-document': addDocument(); break;
      case 'record-fee-report': recordFeeReport(); break;
      case 'open-application': openReview(Number(btn.getAttribute('data-id'))); break;
      case 'back-to-queue': state.reviewApp = null; t('review-panel').hidden = true; t('queue-section').hidden = false; loadQueue(); break;
      case 'issue': decide('ISSUE'); break;
      case 'reject': decide('REJECT'); break;
      case 'print': print(btn.getAttribute('data-kind')); break;
      case 'search-buyers': searchBuyers(); break;
      case 'search-agents': searchAgents(); break;
      case 'toggle-buyer': toggleSuspension('buyer', btn); break;
      case 'toggle-agent': toggleSuspension('agent', btn); break;
      default: break;
    }
  }
  document.addEventListener('input', function (ev) {
    var id = ev.target.getAttribute && ev.target.getAttribute('data-testid');
    if (id === 'prior-year-purchases' || id === 'bond-amount') liveBond();
    else if (id === 'fee-purchase-total') liveFee(ev.target, t('fee-due'));
    else if (id === 'calc-purchase-total') liveFee(ev.target, t('calc-fee-due'));
    else if (id === 'buyer-tax-id') { ev.target.dataset.raw = ev.target.value; delete ev.target.dataset.masked; }
  });
  document.addEventListener('change', function (ev) {
    var id = ev.target.getAttribute && ev.target.getAttribute('data-testid');
    if (id === 'role-switcher') { state.role = ev.target.value; applyRole(); }
    else if (id === 'queue-status-filter') loadQueue();
    else if (id === 'buyer-tax-id') maskTaxId(ev.target);
    else if (id === 'buyer-tax-id-kind') { var el = t('buyer-tax-id'); if (el.dataset.masked === '1') { el.value = el.dataset.raw || ''; delete el.dataset.masked; } }
  });
  document.addEventListener('focusin', function (ev) {
    if (ev.target.getAttribute && ev.target.getAttribute('data-testid') === 'buyer-tax-id' && ev.target.dataset.masked === '1') { ev.target.value = ev.target.dataset.raw || ''; delete ev.target.dataset.masked; }
  });
  document.addEventListener('keydown', function (ev) {
    var tab = ev.target.closest && ev.target.closest('[role="tab"]');
    if (!tab || (ev.key !== 'ArrowRight' && ev.key !== 'ArrowLeft')) return;
    var tabs = $$('[role="tab"]', tab.closest('[role="tablist"]')); var i = tabs.indexOf(tab);
    var nxt = tabs[(i + (ev.key === 'ArrowRight' ? 1 : tabs.length - 1)) % tabs.length];
    nxt.focus(); nxt.click(); ev.preventDefault();
  });

  // ------------------------------------------------------------------ boot
  t('role-switcher').value = state.role;
  showStep(1, true);
  liveBond();
  document.querySelectorAll('[role="tab"]').forEach(function (tab) { tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1; });
})();
