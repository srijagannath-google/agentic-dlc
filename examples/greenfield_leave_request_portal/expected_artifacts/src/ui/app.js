/* Employee Leave & Exception Request Portal — single-page UI.
 * Renders only ViewModel fields returned by the API (labels, masked references); the §3.3 workflow is enforced by
 * the backend and mirrored here through `allowedActions` — no transition button exists unless the API lists it. */
(function () {
  'use strict';

  var IDENTITY = {
    employee: { role: 'Employee' },
    manager: { role: 'Manager' },
    hr: { role: 'HR Certifier' },
    payroll: { role: 'Payroll Integration' }
  };
  var state = {
    roleKey: 'employee', ref: 'EMP-10042', role: 'Employee',
    selected: null,          // RequestView of the selected request (persists across role switches)
    editing: false,          // Employee form open (new request or own Draft)
    balance: null,
    audit: []
  };

  var $ = function (id) { return document.getElementById(id); };
  var el = function (tag, attrs, text) {
    var n = document.createElement(tag);
    Object.keys(attrs || {}).forEach(function (k) { n.setAttribute(k, attrs[k]); });
    if (text != null) n.textContent = text;
    return n;
  };
  function fmtHours(h) { var n = Math.round(Number(h) * 100) / 100; return String(n) + ' h'; }
  function announce(msg) { $('status-region').textContent = msg; }

  // ------------------------------------------------------------------ API client (identity adapter headers)
  function api(method, path, body) {
    var headers = { 'Accept': 'application/json', 'X-Actor-Role': state.role, 'X-Actor-Ref': state.ref };
    var init = { method: method, headers: headers };
    if (body !== undefined) { headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(body); }
    return fetch(path, init).then(function (r) {
      return r.text().then(function (t) {
        var data = null;
        try { data = t ? JSON.parse(t) : null; } catch (e) { data = null; }
        return { ok: r.ok, status: r.status, data: data };
      });
    }).catch(function () {
      return { ok: false, status: 0, data: { message: 'The portal could not reach the server. Check your connection and try again.' } };
    });
  }

  // ------------------------------------------------------------------ rendering
  function showView() {
    ['employee', 'manager', 'hr', 'payroll'].forEach(function (k) { $(k + '-view').hidden = (k !== state.roleKey); });
  }

  function renderBalance() {
    var b = state.balance;
    if (!b) return;
    $('available-balance').textContent = fmtHours(b.availableHours);
    $('pending-balance').textContent = fmtHours(b.pendingHours);
    liveCalc();
  }

  function liveCalc() {
    var b = state.balance;
    var form = $('request-form');
    var hours = parseFloat($('hours').value);
    var type = $('leave-type').value;
    if (form.hidden || !b) { $('post-request-balance').textContent = '—'; return; }
    var warn = $('hours-error');
    if (!isNaN(hours) && hours > 0) {
      $('post-request-balance').textContent = fmtHours(b.availableHours - hours);
      if (hours > b.availableHours) {
        var excess = Math.round((hours - b.availableHours) * 100) / 100;
        warn.textContent = 'Requested hours exceed your available balance by ' + excess + ' h. Reduce the request to at most ' + Math.max(b.availableHours, 0) + ' h.';
        warn.hidden = false;
      } else { warn.hidden = true; warn.textContent = ''; }
    } else {
      $('post-request-balance').textContent = fmtHours(b.availableHours);
      warn.hidden = true; warn.textContent = '';
    }
    var needsCert = (!isNaN(hours) && hours > b.certificationThresholdHours) || type === 'Exception';
    $('certification-indicator').textContent = needsCert ? 'HR certification required' : 'Manager approval is final';
    if (type === 'Exception') {
      $('lead-time-hint').textContent = 'No lead time required for Exception';
    } else {
      var d = new Date(b.today + 'T00:00:00Z');
      d.setUTCDate(d.getUTCDate() + b.leadTimeDays);
      $('lead-time-hint').textContent = 'Earliest start date: ' + d.toISOString().slice(0, 10);
    }
    var reason = $('reason').value || '';
    $('reason-count').textContent = reason.length + ' / 500 characters';
  }

  function openForm(prefill) {
    var form = $('request-form');
    form.hidden = false;
    clearErrors();
    if (prefill) {
      $('leave-type').value = prefill.leaveType;
      $('start-date').value = prefill.startDate;
      $('end-date').value = prefill.endDate;
      $('hours').value = prefill.hours;
      $('reason').value = prefill.reason || '';
    } else {
      form.reset();
    }
    state.editing = true;
    liveCalc();
  }

  function closeForm() {
    $('request-form').hidden = true;
    state.editing = false;
    liveCalc();
  }

  var FIELD_IDS = { leaveType: 'leave-type', startDate: 'start-date', endDate: 'end-date', hours: 'hours', reason: 'reason' };
  var FIELD_DESC = { hours: 'hours-error', startDate: 'lead-time-hint', reason: 'reason-count', endDate: 'validation-summary', leaveType: 'validation-summary' };

  function clearErrors() {
    var s = $('validation-summary'); s.hidden = true; s.textContent = '';
    Object.keys(FIELD_IDS).forEach(function (f) {
      var inp = $(FIELD_IDS[f]);
      inp.removeAttribute('aria-invalid'); inp.removeAttribute('aria-describedby');
    });
    var e = $('action-error'); e.hidden = true; e.textContent = '';
  }

  function showFormError(err) {
    var s = $('validation-summary');
    s.textContent = err.message || 'Please check the request and try again.';
    s.hidden = false;
    if (err.field && FIELD_IDS[err.field]) {
      var inp = $(FIELD_IDS[err.field]);
      inp.setAttribute('aria-invalid', 'true');
      inp.setAttribute('aria-describedby', FIELD_DESC[err.field] || 'validation-summary');
      if (err.field === 'hours') { $('hours-error').textContent = err.message; $('hours-error').hidden = false; }
    }
    s.focus();
  }

  function showActionError(err) {
    var e = $('action-error');
    e.textContent = err.message || 'That action is not available right now.';
    e.hidden = false;
    e.focus();
  }

  function formPayload() {
    return {
      leaveType: $('leave-type').value,
      startDate: $('start-date').value,
      endDate: $('end-date').value,
      hours: $('hours').value === '' ? null : Number($('hours').value),
      reason: $('reason').value || ''
    };
  }

  function rowCells(tr, cells) {
    cells.forEach(function (c) { tr.appendChild(el('td', {}, c)); });
  }

  function openButton(ref) {
    var td = el('td');
    var b = el('button', { type: 'button', 'class': 'btn btn-text', 'data-action': 'open', 'data-ref': ref, 'data-testid': 'open-' + ref }, 'Open');
    b.setAttribute('aria-label', 'Open request ' + ref);
    td.appendChild(b);
    return td;
  }

  function fillTable(tableId, emptyId, rows, build) {
    var table = $(tableId), tbody = table.querySelector('tbody');
    tbody.textContent = '';
    rows.forEach(function (r) { tbody.appendChild(build(r)); });
    table.hidden = rows.length === 0;
    $(emptyId).hidden = rows.length !== 0;
  }

  function renderHistory(rows) {
    fillTable('history-table', 'history-empty', rows, function (r) {
      var tr = el('tr', { 'data-testid': 'history-row-' + r.reference });
      rowCells(tr, [r.reference, r.leaveType, r.startDate + ' – ' + r.endDate, fmtHours(r.hours), r.statusLabel, r.nextApprover]);
      tr.appendChild(openButton(r.reference));
      return tr;
    });
  }

  function renderQueue(tableId, emptyId, rows) {
    fillTable(tableId, emptyId, rows, function (r) {
      var tr = el('tr', { 'data-testid': 'queue-row-' + r.reference });
      rowCells(tr, [r.reference, r.employee.displayName, r.leaveType, r.startDate + ' – ' + r.endDate, fmtHours(r.hours), r.certificationLabel]);
      tr.appendChild(openButton(r.reference));
      return tr;
    });
  }

  function renderPostings(rows) {
    fillTable('posting-log', 'posting-empty', rows, function (p) {
      var tr = el('tr', { 'data-testid': 'posting-row-' + p.reference });
      rowCells(tr, [p.reference, p.outcomeLabel, p.payrollReference || (p.alert ? 'Alert: ' + p.alert : '—'), p.attemptedAt, p.statusLabel || '']);
      tr.appendChild(openButton(p.reference));
      return tr;
    });
  }

  function renderDetail() {
    var d = $('request-detail');
    var r = state.selected;
    if (!r) { d.hidden = true; return; }
    d.hidden = false;
    $('request-reference').textContent = r.reference;
    var chip = $('request-status');
    chip.textContent = r.statusLabel;
    chip.className = 'chip chip-' + r.statusLabel.toLowerCase().replace(/[^a-z]+/g, '-');
    $('request-next-approver').textContent = r.nextApprover;
    $('request-employee').textContent = r.employee.displayName + ' · ' + r.employee.maskedReference;
    $('request-type').textContent = r.leaveType;
    $('request-dates').textContent = r.startDate + ' – ' + r.endDate;
    $('request-hours').textContent = fmtHours(r.hours);
    $('request-routing').textContent = r.certificationLabel;
    var rc = $('return-comment');
    if (r.returnComment) { rc.textContent = 'Returned by ' + r.returnedByRole + ': ' + r.returnComment; rc.hidden = false; } else { rc.hidden = true; rc.textContent = ''; }
    var po = $('posting-outcome');
    if (r.posting) {
      po.textContent = r.posting.outcomeLabel + (r.posting.payrollReference ? ' — reference ' + r.posting.payrollReference : ' — the request stays Approved until the next attempt');
      po.className = 'alert ' + (r.posting.alert ? 'alert-error' : 'alert-success');
      po.hidden = false;
    } else { po.hidden = true; po.textContent = ''; }
    var reason = $('request-reason');
    if (r.reason && state.role !== 'Payroll Integration') { reason.textContent = 'Reason: ' + r.reason; reason.hidden = false; } else { reason.hidden = true; }

    var actions = $('detail-actions');
    actions.textContent = '';
    var a = r.allowedActions || [];
    $('review-box').hidden = a.indexOf('return') === -1;
    if (a.indexOf('approve') !== -1) actions.appendChild(el('button', { type: 'button', 'class': 'btn btn-primary', 'data-action': 'approve', 'data-testid': 'approve-btn' }, 'Approve'));
    if (a.indexOf('certify') !== -1) actions.appendChild(el('button', { type: 'button', 'class': 'btn btn-primary', 'data-action': 'certify', 'data-testid': 'certify-btn' }, 'Certify'));
    if (a.indexOf('return') !== -1) actions.appendChild(el('button', { type: 'button', 'class': 'btn btn-secondary', 'data-action': 'return', 'data-testid': 'return-btn' }, 'Return to employee'));
    if (a.indexOf('withdraw') !== -1) actions.appendChild(el('button', { type: 'button', 'class': 'btn btn-secondary', 'data-action': 'withdraw', 'data-testid': 'withdraw-btn' }, 'Withdraw request'));
    renderAudit();
  }

  function renderAudit() {
    var ol = $('audit-log');
    ol.textContent = '';
    state.audit.forEach(function (e) {
      var txt = e.fromLabel + ' → ' + e.toLabel + (e.outcome === 'denied' ? ' (attempt refused)' : '');
      if (e.actor) txt += ' · ' + e.actor + ' (' + e.role + ')';
      txt += ' · ' + e.at;
      if (e.detail) txt += ' · ' + e.detail;
      ol.appendChild(el('li', {}, txt));
    });
  }

  // ------------------------------------------------------------------ data loading
  function loadSelected() {
    if (!state.selected) { state.audit = []; renderDetail(); return Promise.resolve(); }
    return api('GET', '/api/requests/' + state.selected.reference).then(function (res) {
      if (!res.ok) { state.selected = null; state.audit = []; renderDetail(); return; }
      state.selected = res.data;
      return api('GET', '/api/requests/' + res.data.reference + '/audit').then(function (a) {
        state.audit = a.ok ? a.data : [];
        renderDetail();
      });
    });
  }

  function refresh() {
    showView();
    var jobs = [];
    if (state.roleKey === 'employee') {
      jobs.push(api('GET', '/api/balance').then(function (r) { if (r.ok) { state.balance = r.data; renderBalance(); } }));
      jobs.push(api('GET', '/api/requests').then(function (r) { renderHistory(r.ok ? r.data : []); }));
    } else if (state.roleKey === 'manager') {
      jobs.push(api('GET', '/api/queues/manager').then(function (r) { renderQueue('manager-queue', 'manager-queue-empty', r.ok ? r.data : []); }));
    } else if (state.roleKey === 'hr') {
      jobs.push(api('GET', '/api/queues/certification').then(function (r) { renderQueue('hr-queue', 'hr-queue-empty', r.ok ? r.data : []); }));
    } else {
      jobs.push(api('GET', '/api/payroll-postings').then(function (r) { renderPostings(r.ok ? r.data : []); }));
    }
    jobs.push(loadSelected().then(function () {
      if (state.roleKey === 'employee') {
        var r = state.selected;
        if (r && (r.allowedActions || []).indexOf('edit') !== -1) openForm(r);
        else if (!state.editing) closeForm();
        else if (r && !r.allowedActions.length) closeForm();
      } else { $('request-form').hidden = true; }
      liveCalc();
    }));
    return Promise.all(jobs);
  }

  // ------------------------------------------------------------------ actions
  function saveDraft() {
    clearErrors();
    var payload = formPayload();
    var r = state.selected;
    var editingExisting = r && r.statusCode === 'DRAFT' && (r.allowedActions || []).indexOf('edit') !== -1;
    var p = editingExisting ? api('PUT', '/api/requests/' + r.reference, payload) : api('POST', '/api/requests', payload);
    return p.then(function (res) {
      if (!res.ok) { showFormError(res.data || {}); return null; }
      state.selected = res.data;
      announce('Draft saved');
      return refresh().then(function () { return res.data; });
    });
  }

  function submitRequest() {
    return saveDraft().then(function (saved) {
      if (!saved) return;
      return api('POST', '/api/requests/' + saved.reference + '/submit').then(function (res) {
        if (!res.ok) { state.selected = saved; return refresh().then(function () { showFormError(res.data || {}); }); }
        state.selected = res.data;
        closeForm();
        announce('Request submitted');
        return refresh().then(function () { $('detail-title').focus(); });
      });
    });
  }

  function transition(action) {
    clearErrors();
    var r = state.selected;
    if (!r) return Promise.resolve();
    var body = action === 'return' ? { comment: $('return-comment-input').value } : undefined;
    return api('POST', '/api/requests/' + r.reference + '/' + action, body).then(function (res) {
      if (!res.ok) { showActionError(res.data || {}); return; }
      state.selected = res.data;
      $('return-comment-input').value = '';
      var msg = { withdraw: 'Request withdrawn', approve: 'Request approved', certify: 'Request certified', 'return': 'Request returned to the employee' }[action];
      announce(msg);
      if (action === 'withdraw') state.editing = false;
      return refresh();
    });
  }

  function openRequest(ref) {
    clearErrors();
    state.selected = { reference: ref };
    state.editing = false;
    return refresh();
  }

  function setIdentity(value) {
    var parts = value.split(':');
    state.roleKey = parts[0];
    state.ref = parts[1];
    state.role = IDENTITY[state.roleKey].role;
    clearErrors();
    state.editing = false;
    $('request-form').hidden = true;
    return refresh().then(function () {
      var h2 = $(state.roleKey + '-view').querySelector('h2');
      if (h2) h2.focus();
    });
  }

  // ------------------------------------------------------------------ wiring (delegated)
  document.addEventListener('click', function (ev) {
    var btn = ev.target.closest('[data-action]');
    if (!btn) return;
    var action = btn.getAttribute('data-action');
    if (action === 'new-request') { state.selected = null; state.audit = []; renderDetail(); openForm(null); $('leave-type').focus(); }
    else if (action === 'switch-tab') {
      var tablist = btn.closest('[role="tablist"]');
      if (tablist) {
        Array.prototype.forEach.call(tablist.querySelectorAll('[role="tab"]'), function (t) {
          var active = (t === btn);
          t.setAttribute('aria-selected', active ? 'true' : 'false');
          var pid = t.getAttribute('aria-controls');
          if (pid && $(pid)) $(pid).hidden = !active;
        });
      }
    }
    else if (action === 'save-draft') saveDraft();
    else if (action === 'submit') { ev.preventDefault(); submitRequest(); }
    else if (action === 'open') openRequest(btn.getAttribute('data-ref'));
    else if (action === 'approve' || action === 'return' || action === 'certify' || action === 'withdraw') transition(action);
  });
  document.addEventListener('keydown', function (ev) {
    // Keyboard activation of action buttons (Enter); Space keeps its native activation on keyup.
    if (ev.key === 'Enter' && ev.target && ev.target.matches && ev.target.matches('button[data-action]')) { ev.preventDefault(); ev.target.click(); }
  });
  $('request-form').addEventListener('submit', function (ev) { ev.preventDefault(); submitRequest(); });
  $('request-form').addEventListener('input', liveCalc);
  $('request-form').addEventListener('change', liveCalc);
  $('role-switcher').addEventListener('change', function (ev) { setIdentity(ev.target.value); });

  // ------------------------------------------------------------------ start (external role first)
  $('role-switcher').value = 'employee:EMP-10042';
  setIdentity('employee:EMP-10042');
})();
