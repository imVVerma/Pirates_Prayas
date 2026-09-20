/* M2 integration-only shim. Original intake-spine.html is served unmodified.
 * No Claude dependency, no fake test results, no diagnosis and no UI redesign.
 * Requires local Python device_server.py running (browser-only offline not yet supported).
 */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const touched = new Set();
  let consentAt = null;
  let submittedAt = null;
  let lastCase = null;
  let busy = false;

  // Functional necessities, not a visual redesign: M0 demands explicit consent.
  const actions = $('genBtn').parentNode;
  const gate = document.createElement('div');
  gate.innerHTML =
    '<label><input id="m2-consent" type="checkbox"> ' +
    'I confirm explicit consent for data collection and sharing with a qualified verifier.</label><br>' +
    '<label><input id="m2-synthetic" type="checkbox"> ' +
    'I am entering SYNTHETIC demo data only (no real patient information).</label>';
  actions.parentNode.insertBefore(gate, actions);
  $('m2-consent').addEventListener('change', e => {
    consentAt = e.target.checked ? new Date().toISOString() : null;
  });
  ['fever', 'sweats', 'weightloss'].forEach(id => {
    $(id).addEventListener('change', () => touched.add(id));
  });
  $('loc').placeholder = 'DEMO-AREA-A (synthetic code only)';
  $('age').min = '18';
  $('xrayAvail').disabled = true; // M3 must provide evidence provenance before enabling.
  $('esrAvail').disabled = true; // Legacy flat ESR=20 threshold is unverified.
  $('genBtn').textContent = 'Save case + draft summary';
  $('dlBtn').textContent = 'Save + download validated JSON';
  $('summaryOut').textContent = 'Synthetic symptom-only intake; unassessed symptoms stay unknown. ' +
    'X-ray/ESR buttons in the legacy form cannot be submitted until the M3 provenance adapter is integrated.';
  const footer = document.querySelector('footer.note');
  if (footer) footer.textContent = 'M2 backend bridge: M0-validated synthetic symptom records, local durable outbox and optional central sync. ' +
    'Manual X-ray/ESR inputs are blocked from submission until M3 supplies verifiable test provenance.';

  function collect() {
    // Original form's in-memory state is only used for its stable initial UUID.
    // The canonical payload is built from real input fields, not this preview.
    let legacy;
    try { legacy = JSON.parse($('record').textContent); }
    catch (_) { throw new Error('Original form case ID is unavailable'); }
    const age = $('age').value.trim();
    const cough = $('cough').value.trim();
    if (age && !/^\d+$/.test(age)) throw new Error('Enter an integer age');
    if (cough && !/^\d+$/.test(cough)) throw new Error('Enter whole cough days');
    if (age === '') throw new Error('Age is required for the adult-only M0 contract');
    if ($('loc').value.trim() === '') throw new Error('Synthetic DEMO-area code is required');
    if (!$('m2-consent').checked || !consentAt)
      throw new Error('Explicit collection and verifier-sharing consent is required');
    if (!$('m2-synthetic').checked)
      throw new Error('Use only synthetic demo data (confirm before saving)');
    if ($('xrayAvail').checked || $('esrAvail').checked)
      throw new Error('X-ray/ESR captured metadata is absent in the original UI. ' +
        'Uncheck these and submit symptoms only; M3 will provide test adapters.');
    // Timestamp must be generated once. Repeated submits are idempotent and
    // changed content at the same revision produces an explicit 409 conflict.
    if (!submittedAt) submittedAt = new Date().toISOString();
    const answer = id => touched.has(id) ? $(id).checked : null;
    return {
      case_id: legacy.case_id, created_at: submittedAt,
      consent_recorded_at: consentAt, consent_confirmed: true,
      synthetic_acknowledged: true, age: age === '' ? null : Number(age),
      sex: $('sex').value ? $('sex').value.toLowerCase() : 'not_recorded',
      location: $('loc').value.trim(),
      cough_duration_days: cough === '' ? null : Number(cough),
      fever: answer('fever'), night_sweats: answer('sweats'),
      weight_loss: answer('weightloss'),
      xray_available: false, esr_available: false
    };
  }

  async function jsonPost(path, obj) {
    let response;
    try {
      response = await fetch(path, {
        method: 'POST', headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(obj)
      });
    } catch (_) {
      throw new Error('Local intake service unreachable; start device_server.py. ' +
        'The browser form itself does NOT store unsent cases offline.');
    }
    let data;
    try { data = await response.json(); }
    catch (_) { throw new Error('Local service returned invalid JSON'); }
    if (!response.ok) throw new Error(data.detail || data.error || 'Save failed');
    return data;
  }

  async function submit(download) {
    if (busy) return;
    busy = true;
    $('genBtn').disabled = $('dlBtn').disabled = true;
    const out = $('summaryOut');
    out.className = 'summary-text';
    try {
      const input = collect();
      const saved = await jsonPost('/v1/intake', input);
      lastCase = saved.case;
      const summary = saved.case.case_summary.brief_text;
      out.textContent = summary + '\n\nSaved locally (' + saved.result + ').';
      $('record').textContent = JSON.stringify(saved.case, null, 2);
      $('metaBox').textContent = 'case ' + saved.case.case_id.slice(0,8) + ' · ' + saved.case.case_status;
      if (download) {
        const blob = new Blob([JSON.stringify(saved.case, null, 2)], {type:'application/json'});
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'case-' + saved.case.case_id.slice(0,8) + '.json';
        a.click();
        URL.revokeObjectURL(url);
      }
      // Best effort: no remote server -> local SQLite retains the case pending.
      try {
        const result = await jsonPost('/v1/sync', {});
        const own = result.outbox.find(row => row.case_id === saved.case.case_id &&
          row.revision === saved.case.revision);
        out.textContent += own && own.sync_status === 'acked'
          ? '\nCentral receiver ACK confirmed.'
          : '\nCentral receiver unavailable; safe to retry from local outbox.';
      } catch (_) {
        out.textContent += '\nSync attempt deferred; saved case remains local.';
      }
    } catch (error) {
      out.textContent = 'NOT SAVED: ' + error.message;
    } finally {
      busy = false;
      $('genBtn').disabled = $('dlBtn').disabled = false;
    }
  }

  // Capture before the original Claude-only click handlers; preserve HTML/CSS.
  // These two original handlers are not compatible with frozen M0 snapshots.
  document.addEventListener('click', event => {
    if (event.target === $('genBtn') || event.target === $('dlBtn')) {
      event.preventDefault();
      event.stopImmediatePropagation();
      submit(event.target === $('dlBtn'));
    }
  }, true);

  // Small testable integration surface; not a clinical authorization boundary.
  window.TBM2 = {collect, submit, syncPending: () => jsonPost('/v1/sync',{}),
                  savedCase: () => lastCase};
})();
