'use strict';
const API = '';
let token = localStorage.getItem('lm_token') || '';
let labId = parseInt(localStorage.getItem('lm_lab') || '0');
let username = localStorage.getItem('lm_user') || '';
let pollTimer = null, sessionStart = null, timerInterval = null;
let knownAlertIds = new Set();
let subjects = [], machines = [], pendingApps = [];
let editingSubjectId = null;

const $ = id => document.getElementById(id);
const auth = () => ({ 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + token });

async function api(method, path, body) {
  const opts = { method, headers: auth() };
  if (body) opts.body = JSON.stringify(body);
  const r = await fetch(API + '/api' + path, opts);
  if (r.status === 401) { logout(); return null; }
  return r.ok ? r.json() : null;
}

// ── AUTH ──────────────────────────────────────────────────────────────────────
$('loginForm').addEventListener('submit', async e => {
  e.preventDefault();
  const u = $('loginUsername').value.trim(), p = $('loginPassword').value;
  $('loginBtn').disabled = true;
  $('loginBtn').innerHTML = '<i class="fas fa-spinner fa-spin"></i> Signing in...';
  try {    const r = await fetch(API + '/api/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, password: p })
    });
    const d = await r.json();
    if (!r.ok) { showLoginError(d.msg || 'Login failed'); return; }
    token = d.token; labId = d.lab_id; username = d.username;
    localStorage.setItem('lm_token', token);
    localStorage.setItem('lm_lab', labId);
    localStorage.setItem('lm_user', username);
    startApp();
  } catch { showLoginError('Cannot connect to server.'); }
  finally {
    $('loginBtn').disabled = false;
    $('loginBtn').innerHTML = '<i class="fas fa-sign-in-alt"></i> Sign In';
  }
});

function showLoginError(msg) {
  const el = $('loginError');
  const txt = $('loginErrorText');
  if (txt) txt.textContent = msg;
  else el.textContent = msg;
  el.style.display = 'flex';
  // Shake animation
  const card = document.querySelector('.login-card');
  card.classList.remove('shake');
  void card.offsetWidth;
  card.classList.add('shake');
}

function clearLoginError() {
  $('loginError').style.display = 'none';
}
function togglePw() {
  const i = $('loginPassword'); i.type = i.type === 'password' ? 'text' : 'password';
  $('pwEye').className = i.type === 'password' ? 'fas fa-eye' : 'fas fa-eye-slash';
}
function logout() {
  localStorage.removeItem('lm_token'); localStorage.removeItem('lm_lab'); localStorage.removeItem('lm_user');
  location.reload();
}

// ── INIT ──────────────────────────────────────────────────────────────────────
function startApp() {
  $('loginScreen').style.display = 'none';
  $('app').style.display = 'flex';
  $('sidebarUsername').textContent = username;
  loadSubjects(); loadMachines(); poll();
  pollTimer = setInterval(poll, 3000);
}

if (token) startApp();

// ── SERVER STATUS CHECK (login page) ─────────────────────────────────────────
async function checkServerStatus() {
  const dot  = $('loginStatusDot');
  const text = $('loginStatusText');
  if (!dot) return;
  try {
    const r = await fetch('/api/health');
    if (r.ok) {
      dot.className  = 'login-status-dot online';
      text.textContent = 'Server online — ready to connect';
    } else {
      dot.className  = 'login-status-dot offline';
      text.textContent = 'Server error — check backend';
    }
  } catch {
    dot.className  = 'login-status-dot offline';
    text.textContent = 'Cannot reach server';
  }
}

// Run status check on load and every 5s while on login screen
checkServerStatus();
setInterval(() => { if ($('loginScreen').style.display !== 'none') checkServerStatus(); }, 5000);

// ── SIDEBAR / NAV ─────────────────────────────────────────────────────────────
function toggleSidebar() {
  document.querySelector('.sidebar').classList.toggle('collapsed');
}
function showView(name) {
  document.querySelectorAll('.view').forEach(v => v.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  $('view-' + name).classList.add('active');
  document.querySelector(`[data-view="${name}"]`).classList.add('active');
  const titles = { dashboard: 'Dashboard', alerts: 'Alerts', subjects: 'Subjects', machines: 'Machines', history: 'History' };
  $('pageTitle').textContent = titles[name] || name;
  if (name === 'alerts') loadAlerts();
  if (name === 'subjects') renderSubjects();
  if (name === 'machines') renderMachines();
  if (name === 'history') loadHistory('sessions');
}

// ── POLL ──────────────────────────────────────────────────────────────────────
async function poll() {
  const d = await api('GET', `/labs/${labId}/dashboard`);
  if (!d) return;
  renderDashboard(d);
  if (d.active_session && !sessionStart) activateSession(d.active_session);
  if (!d.active_session && sessionStart) deactivateSession();
  updateBadge(d.total_unseen);
  checkNewAlerts(d);
}

function checkNewAlerts(d) {
  if (!d.active_session) return;
  d.machines.forEach(m => {
    if (!m.current_allowed && m.is_online) {
      const key = `${m.id}_${m.current_app}`;
      if (!knownAlertIds.has(key)) {
        knownAlertIds.add(key);
        showToast('alert', `⚠️ ${m.pc_number}`, `Opened: ${m.current_app || 'Unknown'}`, 6000);
        playAlertSound();
        setTimeout(() => knownAlertIds.delete(key), 70000);
      }
    }
  });
}

// ── DASHBOARD RENDER ──────────────────────────────────────────────────────────
function renderDashboard(d) {
  const online = d.machines.filter(m => m.is_online).length;
  const violations = d.machines.filter(m => !m.current_allowed && m.is_online && !m.is_paused).length;
  const paused = d.machines.filter(m => m.is_paused).length;
  const compliant = online - violations - paused;
  const scores = d.machines.filter(m => m.is_online && !m.is_paused).map(m => m.compliance_score);
  const avg = scores.length ? Math.round(scores.reduce((a, b) => a + b, 0) / scores.length) : 0;
  $('statOnline').textContent = online;
  $('statCompliant').textContent = compliant;
  $('statViolations').textContent = violations;
  $('statAvgCompliance').textContent = scores.length ? avg + '%' : '—';

  const grid = $('pcGrid');
  if (!d.machines.length) {
    grid.innerHTML = `
      <div class="lab-empty-state">
        <div class="lab-empty-icon"><i class="fas fa-network-wired"></i></div>
        <h3>No Computers Connected</h3>
        <p>Go to <strong>Machines</strong> tab to register student PCs, then download and install the agent on each PC.</p>
        <button class="btn-primary" onclick="showView('machines')" style="margin-top:1rem">
          <i class="fas fa-plus"></i> Add Machines
        </button>
      </div>`;
    return;
  }

  // Remove empty state if present
  const emptyState = grid.querySelector('.lab-empty-state');
  if (emptyState) emptyState.remove();

  // Remove cards that no longer exist
  const currentIds = new Set(d.machines.map(m => 'pc_' + m.id));
  Array.from(grid.children).forEach(child => {
    if (!currentIds.has(child.id)) child.remove();
  });

  d.machines.forEach(m => {
    let card = document.getElementById('pc_' + m.id);
    if (!card) {
      card = document.createElement('div');
      card.className = 'pc-card';
      card.id = 'pc_' + m.id;
      grid.appendChild(card);
    }

    const isViolation = !m.current_allowed && m.is_online && !m.is_paused;
    const isPaused    = m.is_paused;
    const isOffline   = !m.is_online;

    card.className = 'pc-card' +
      (isOffline ? ' offline' : isViolation ? ' violation' : isPaused ? ' paused' : '');

    const score = m.compliance_score;
    const scoreColor = score >= 80 ? 'var(--green)' : score >= 50 ? 'var(--yellow)' : 'var(--red)';
    const dotClass = isOffline ? 'offline' : isViolation ? 'violation' : isPaused ? 'paused' : 'online';

    // PC number — clean label (PC-01 → PC 01)
    const pcLabel = m.pc_number.replace('-', ' ');

    // Status chip
    let statusChip = '';
    if (isOffline)   statusChip = `<span class="pc-chip offline-chip">Offline</span>`;
    else if (isPaused) statusChip = `<span class="pc-chip paused-chip"><i class="fas fa-pause"></i> Paused</span>`;
    else if (isViolation) statusChip = `<span class="pc-chip violation-chip"><i class="fas fa-triangle-exclamation"></i> Alert</span>`;
    else statusChip = `<span class="pc-chip online-chip"><i class="fas fa-circle-check"></i> Active</span>`;

    // Current activity display
    let activityHtml = '';
    if (!isOffline && m.current_app) {
      activityHtml = `
        <div class="pc-activity">
          <i class="fas fa-window-maximize pc-activity-icon"></i>
          <div class="pc-activity-info">
            <div class="pc-activity-app">${m.current_app}</div>
            ${m.current_title && m.current_title !== m.current_app
              ? `<div class="pc-activity-title">${m.current_title}</div>` : ''}
          </div>
        </div>`;
    } else if (isOffline) {
      activityHtml = `<div class="pc-offline-msg"><i class="fas fa-power-off"></i> Powered off</div>`;
    } else {
      activityHtml = `<div class="pc-offline-msg"><i class="fas fa-moon"></i> Idle</div>`;
    }

    card.innerHTML = `
      <div class="pc-card-top">
        <div class="pc-card-left">
          <div class="pc-icon"><i class="fas fa-desktop"></i></div>
          <div>
            <div class="pc-number">${pcLabel}</div>
            ${m.hostname ? `<div class="pc-hostname">${m.hostname}</div>` : ''}
          </div>
        </div>
        <div class="pc-card-right">
          <span class="pc-status-dot ${dotClass}"></span>
        </div>
      </div>

      ${statusChip}
      ${activityHtml}

      ${!isOffline && !isPaused ? `
      <div class="pc-score-row">
        <div class="pc-score-bar">
          <div class="pc-score-fill" style="width:${score}%;background:${scoreColor}"></div>
        </div>
        <span class="pc-score-label" style="color:${scoreColor}">${score}%</span>
      </div>` : ''}

      <div class="pc-card-actions">
        <button class="pc-btn-detail" onclick="event.stopPropagation();openPcDetail(${m.id})" title="View activity">
          <i class="fas fa-chart-line"></i>
        </button>
        ${!isOffline ? `
        <button class="pc-btn-pause ${isPaused ? 'is-paused' : ''}"
          onclick="event.stopPropagation();togglePause(${m.id},${labId},${isPaused})"
          title="${isPaused ? 'Resume monitoring' : 'Pause monitoring (lecturer mode)'}">
          <i class="fas fa-${isPaused ? 'play' : 'pause'}"></i>
        </button>` : ''}
        ${m.unseen_alerts > 0 ? `<span class="pc-alert-badge">${m.unseen_alerts}</span>` : ''}
      </div>`;
  });
}

async function togglePause(machineId, labId, isPaused) {
  const action = isPaused ? 'resume' : 'pause';
  const r = await api('POST', `/labs/${labId}/machines/${machineId}/${action}`);
  if (r) {
    showToast(
      isPaused ? 'success' : 'info',
      isPaused ? 'Monitoring Resumed' : 'Monitoring Paused',
      isPaused ? 'This PC is now being tracked again.' : 'Lecturer mode ON — violations suppressed.'
    );
  }
}

// ── SESSION ───────────────────────────────────────────────────────────────────
function activateSession(s) {
  sessionStart = new Date(s.started_at + 'Z');
  $('sessionLabel').textContent = s.subject_name;
  $('sessionInactive').style.display = 'none';
  $('sessionActive').style.display = 'flex';
  timerInterval = setInterval(updateTimer, 1000);
  updateTimer();
}
function deactivateSession() {
  sessionStart = null;
  clearInterval(timerInterval);
  $('sessionInactive').style.display = 'flex';
  $('sessionActive').style.display = 'none';
  $('sessionTimer').textContent = '00:00';
}
function updateTimer() {
  if (!sessionStart) return;
  const s = Math.floor((Date.now() - sessionStart) / 1000);
  $('sessionTimer').textContent = `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
}
async function startSession() {
  const sid = $('subjectSelect').value;
  if (!sid) { alert('Select a subject first.'); return; }
  const r = await api('POST', `/labs/${labId}/sessions/start`, { subject_id: parseInt(sid) });
  if (r) { showToast('success', 'Session Started', `Monitoring started for selected subject.`); knownAlertIds.clear(); }
}
async function endSession() {
  if (!confirm('End this session?')) return;
  const r = await api('POST', `/labs/${labId}/sessions/end`);
  if (r) { showToast('info', 'Session Ended', 'Session has been stopped.'); if (r.report) showReport(r.report); }
}

// ── ALERTS ────────────────────────────────────────────────────────────────────
function updateBadge(n) {
  const bell = $('bellBadge'), nav = $('navAlertBadge');
  if (n > 0) { bell.style.display = nav.style.display = 'inline-block'; bell.textContent = nav.textContent = n; }
  else { bell.style.display = nav.style.display = 'none'; }
}
async function loadAlerts() {
  const unseenOnly = $('unseenOnly')?.checked;
  const groupByPc  = $('groupByPc')?.checked !== false;
  const sortOrder  = $('alertSort')?.value || 'newest';

  const alerts = await api('GET', `/labs/${labId}/alerts?unseen_only=${unseenOnly}`);
  const list = $('alertsList');

  if (!alerts || !alerts.length) {
    $('alertCount').textContent = '0 alerts';
    list.innerHTML = `
      <div class="alerts-empty">
        <div class="alerts-empty-icon"><i class="fas fa-shield-check"></i></div>
        <h3>All Clear!</h3>
        <p>No violations detected. All students are working on assigned tasks.</p>
      </div>`;
    return;
  }

  // Sort
  const sorted = [...alerts].sort((a, b) => {
    const da = new Date(a.created_at), db = new Date(b.created_at);
    return sortOrder === 'newest' ? db - da : da - db;
  });

  $('alertCount').textContent = sorted.length + ' alert' + (sorted.length > 1 ? 's' : '');

  if (!groupByPc) {
    // Flat list sorted by date
    list.innerHTML = sorted.map(a => {
      const dt = new Date(a.created_at + 'Z').toLocaleString('en-IN', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true
      });
      const msgClean = a.message.replace(a.pc_number + ' ', '').replace('opened ', '').trim();
      const ss = a.screenshot_path
        ? `<button class="alert-ss-btn" onclick="viewScreenshot('${a.screenshot_path}')"><i class="fas fa-image"></i></button>`
        : '';
      return `
        <div class="alert-row ${a.seen ? 'seen' : 'unseen'}">
          <div class="alert-row-left"><div class="alert-row-dot ${a.seen ? '' : 'active'}"></div></div>
          <div class="alert-group-pc-badge" style="flex-shrink:0;font-size:.75rem">
            <i class="fas fa-desktop"></i><span>${a.pc_number}</span>
          </div>
          <div class="alert-row-content">
            <div class="alert-row-app"><i class="fas fa-ban" style="color:var(--red);font-size:.7rem"></i> ${msgClean}</div>
            <div class="alert-row-time"><i class="fas fa-clock"></i> ${dt}</div>
          </div>
          <div class="alert-row-right">${ss}<span class="alert-badge-pill ${a.seen ? 'seen' : 'new'}">${a.seen ? 'Seen' : 'New'}</span></div>
        </div>`;
    }).join('');
    return;
  }

  // Group by PC (maintaining sort order within groups)
  const grouped = {};
  sorted.forEach(a => {
    if (!grouped[a.pc_number]) grouped[a.pc_number] = [];
    grouped[a.pc_number].push(a);
  });

  const sortedPCs = Object.keys(grouped).sort();

  list.innerHTML = sortedPCs.map((pc, idx) => {
    const pcAlerts = grouped[pc];
    const unseenCount = pcAlerts.filter(a => !a.seen).length;
    const isExpanded = unseenCount > 0 || idx === 0;

    const rows = pcAlerts.map(a => {
      const dt = new Date(a.created_at + 'Z').toLocaleString('en-IN', {
        day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', hour12: true
      });
      const msgClean = a.message.replace(pc + ' ', '').replace('opened ', '').trim();
      const ss = a.screenshot_path
        ? `<button class="alert-ss-btn" onclick="event.stopPropagation();viewScreenshot('${a.screenshot_path}')" title="View screenshot"><i class="fas fa-image"></i></button>`
        : '';
      return `
        <div class="alert-row ${a.seen ? 'seen' : 'unseen'}">
          <div class="alert-row-left"><div class="alert-row-dot ${a.seen ? '' : 'active'}"></div></div>
          <div class="alert-row-content">
            <div class="alert-row-app"><i class="fas fa-ban" style="color:var(--red);font-size:.7rem"></i> ${msgClean}</div>
            <div class="alert-row-time"><i class="fas fa-clock"></i> ${dt}</div>
          </div>
          <div class="alert-row-right">${ss}<span class="alert-badge-pill ${a.seen ? 'seen' : 'new'}">${a.seen ? 'Seen' : 'New'}</span></div>
        </div>`;
    }).join('');

    return `
      <div class="alert-group">
        <div class="alert-group-hdr" onclick="toggleAlertGroup(this)">
          <div class="alert-group-hdr-left">
            <div class="alert-group-pc-badge"><i class="fas fa-desktop"></i><span>${pc}</span></div>
            <div class="alert-group-stats">
              <span class="alert-stat-total">${pcAlerts.length} violation${pcAlerts.length > 1 ? 's' : ''}</span>
              ${unseenCount > 0
                ? `<span class="alert-stat-new"><i class="fas fa-circle" style="font-size:.45rem"></i> ${unseenCount} new</span>`
                : `<span class="alert-stat-clear"><i class="fas fa-circle-check" style="font-size:.7rem"></i> All seen</span>`}
            </div>
          </div>
          <i class="fas fa-chevron-${isExpanded ? 'up' : 'down'} alert-chevron"></i>
        </div>
        <div class="alert-group-body ${isExpanded ? 'expanded' : 'collapsed'}">${rows}</div>
      </div>`;
  }).join('');
}

function toggleAlertGroup(hdr) {
  const body = hdr.nextElementSibling;
  const chevron = hdr.querySelector('.alert-chevron');
  const isExpanded = body.classList.contains('expanded');
  body.classList.toggle('expanded', !isExpanded);
  body.classList.toggle('collapsed', isExpanded);
  chevron.className = `fas fa-chevron-${isExpanded ? 'down' : 'up'} alert-chevron`;
}
async function markAllSeen() {
  await api('POST', `/labs/${labId}/alerts/mark-seen`);
  updateBadge(0); loadAlerts();
}
function viewScreenshot(path) {
  $('screenshotImg').src = API + '/api/' + path;
  $('screenshotModal').style.display = 'flex';
}

// ── SUBJECTS ──────────────────────────────────────────────────────────────────
async function loadSubjects() {
  subjects = await api('GET', `/labs/${labId}/subjects`) || [];
  const sel = $('subjectSelect');
  sel.innerHTML = '<option value="">— Select Subject —</option>' + subjects.map(s => `<option value="${s.id}">${s.name}</option>`).join('');
}
function renderSubjects() {
  loadSubjects().then(() => {
    const list = $('subjectsList');
    if (!subjects.length) { list.innerHTML = '<div class="empty-state"><i class="fas fa-book"></i><p>No subjects yet.</p></div>'; return; }
    list.innerHTML = subjects.map(s => `
      <div class="subject-card">
        <div class="subject-card-header">
          <span class="subject-name"><i class="fas fa-book"></i> ${s.name}</span>
          <div class="subject-actions">
            <button class="btn-secondary btn-sm" onclick="openEditSubjectModal(${s.id})"><i class="fas fa-pen"></i> Edit</button>
            <button class="btn-danger btn-sm" onclick="deleteSubject(${s.id})"><i class="fas fa-trash"></i></button>
          </div>
        </div>
        <div class="subject-apps">
          ${s.allowed_apps.length ? s.allowed_apps.map(a => `<span class="app-chip"><i class="fas fa-check"></i>${a.app_name}${a.allow_browser ? '<span class="browser-tag">+Browser</span>' : ''}</span>`).join('') : '<span style="font-size:.8rem;color:var(--text-muted)">No allowed apps defined — everything will be flagged.</span>'}
        </div>
      </div>`).join('');
  });
}
function openAddSubjectModal() { editingSubjectId = null; $('subjectModalTitle').textContent = 'Add Subject'; $('subjectName').value = ''; pendingApps = []; renderAppsList(); $('addSubjectModal').style.display = 'flex'; }
function openEditSubjectModal(id) {
  const s = subjects.find(x => x.id === id); if (!s) return;
  editingSubjectId = id; $('subjectModalTitle').textContent = 'Edit Subject'; $('subjectName').value = s.name;
  pendingApps = s.allowed_apps.map(a => ({ app_name: a.app_name, allow_browser: a.allow_browser }));
  renderAppsList(); $('addSubjectModal').style.display = 'flex';
}
function renderAppsList() {
  $('appsList').innerHTML = pendingApps.map((a, i) => `
    <div class="app-row">
      <span class="app-row-name"><i class="fas fa-cube"></i> ${a.app_name}</span>
      ${a.allow_browser ? '<span class="browser-flag"><i class="fas fa-globe"></i> Browser OK</span>' : ''}
      <button class="btn-danger btn-sm" onclick="removeApp(${i})"><i class="fas fa-times"></i></button>
    </div>`).join('');
}
function addAppRow() {
  const name = $('newAppName').value.trim(); if (!name) return;
  pendingApps.push({ app_name: name, allow_browser: $('newAppBrowser').checked });
  $('newAppName').value = ''; $('newAppBrowser').checked = false; renderAppsList();
}
function removeApp(i) { pendingApps.splice(i, 1); renderAppsList(); }
async function saveSubject() {
  const name = $('subjectName').value.trim(); if (!name) { alert('Enter a subject name.'); return; }
  const body = { name, allowed_apps: pendingApps };
  if (editingSubjectId) await api('PUT', `/labs/${labId}/subjects/${editingSubjectId}`, body);
  else await api('POST', `/labs/${labId}/subjects`, body);
  closeModal('addSubjectModal'); renderSubjects(); loadSubjects();
  showToast('success', 'Saved', 'Subject updated.');
}
async function deleteSubject(id) {
  if (!confirm('Delete this subject?')) return;
  await api('DELETE', `/labs/${labId}/subjects/${id}`);
  renderSubjects(); loadSubjects();
}

// ── MACHINES ──────────────────────────────────────────────────────────────────
async function loadMachines() { machines = await api('GET', `/labs/${labId}/machines`) || []; }
function renderMachines() {
  loadMachines().then(() => {
    const list = $('machinesList');
    if (!machines.length) {
      list.innerHTML = '<div class="empty-state"><i class="fas fa-desktop"></i><p>No machines yet.</p></div>';
      return;
    }
    list.innerHTML = `
      <table class="machines-table">
        <thead>
          <tr>
            <th>PC</th>
            <th>Hostname</th>
            <th>Status</th>
            <th>Last Seen</th>
            <th>Token</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          ${machines.map(m => {
            const lastSeen = m.last_seen
              ? new Date(m.last_seen + 'Z').toLocaleString('en-IN', {day:'2-digit',month:'short',hour:'2-digit',minute:'2-digit',hour12:true})
              : 'Never';
            const tokenShort = m.token.substring(0,8) + '...' + m.token.slice(-6);
            return `<tr>
              <td><strong>${m.pc_number}</strong></td>
              <td class="text-muted">${m.hostname || '—'}</td>
              <td>
                <span class="m-status-dot ${m.is_online ? 'online' : 'offline'}"></span>
                <span class="text-muted" style="font-size:.78rem">${m.is_online ? 'Online' : 'Offline'}</span>
              </td>
              <td class="text-muted" style="font-size:.78rem">${lastSeen}</td>
              <td>
                <div class="token-cell">
                  <code class="token-short" title="${m.token}">${tokenShort}</code>
                  <button class="icon-btn" onclick="copyToken('${m.token}')" title="Copy token"><i class="fas fa-copy"></i></button>
                </div>
              </td>
              <td>
                <div class="m-actions">
                  <button class="btn-primary btn-sm" onclick="downloadAgentZip(${m.id},'${m.pc_number}')">
                    <i class="fas fa-download"></i> ZIP
                  </button>
                  <button class="btn-danger btn-sm icon-only" onclick="deleteMachine(${m.id})" title="Remove">
                    <i class="fas fa-trash"></i>
                  </button>
                </div>
              </td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  });
}
function openAddMachineModal() { $('newPcNumber').value = ''; $('newHostname').value = ''; $('addMachineModal').style.display = 'flex'; }
async function addMachine() {
  const pc = $('newPcNumber').value.trim(); if (!pc) { alert('Enter PC number.'); return; }
  const r = await api('POST', `/labs/${labId}/machines`, { pc_number: pc, hostname: $('newHostname').value.trim() });
  if (r) { closeModal('addMachineModal'); renderMachines(); showToast('success', 'Machine Added', `${pc} — Token copied!`); copyToken(r.token); }
}
async function deleteMachine(id) {
  if (!confirm('Delete this machine?')) return;
  await api('DELETE', `/labs/${labId}/machines/${id}`);
  renderMachines(); document.getElementById('pc_' + id)?.remove();
}
function copyToken(t) { navigator.clipboard.writeText(t).then(() => showToast('info', 'Copied!', 'Token copied to clipboard.')); }

// Store last download info for re-download
let lastDownload = null;

async function downloadAgentZip(machineId, pcNumber) {
  showToast('info', 'Generating...', `Building agent package for ${pcNumber}`);
  try {
    const res = await fetch(`${API}/api/labs/${labId}/machines/${machineId}/generate-agent`, {
      method: 'POST',
      headers: auth(),
      body: JSON.stringify({ server_url: null })
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      showToast('alert', 'Error', err.msg || 'Failed to generate ZIP');
      return;
    }

    const blob    = await res.blob();
    const zipName = `${pcNumber}_agent.zip`;
    const url     = URL.createObjectURL(blob);
    const a       = document.createElement('a');
    a.href = url; a.download = zipName;
    document.body.appendChild(a); a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);

    // Store for re-download
    lastDownload = { machineId, pcNumber };

    // Get machine token for display
    const machine = machines.find(m => m.id === machineId);
    const token_  = machine?.token || '—';

    // Auto-detect server URL (same as what's in the ZIP)
    let serverUrl = window.location.origin;

    // Show deployment instructions modal
    $('deployPcName').textContent  = pcNumber;
    $('deployPcName2').textContent = pcNumber;
    $('deployZipName').textContent = zipName;
    $('deployZipName2').textContent = zipName;
    $('deployMachineName').textContent = pcNumber;
    $('deployServerUrl').textContent   = serverUrl;
    $('deployToken').textContent       = token_;
    $('deployModal').style.display     = 'flex';

  } catch (e) {
    showToast('alert', 'Error', 'Network error generating ZIP');
  }
}

function redownloadZip() {
  if (lastDownload) {
    closeModal('deployModal');
    downloadAgentZip(lastDownload.machineId, lastDownload.pcNumber);
  }
}

// ── PC DETAIL ─────────────────────────────────────────────────────────────────
async function openPcDetail(machineId) {
  const m = (await api('GET', `/labs/${labId}/dashboard`))?.machines?.find(x => x.id === machineId);
  if (!m) return;
  $('pcDetailTitle').innerHTML = `<i class="fas fa-desktop"></i> ${m.pc_number}`;
  const scoreColor = m.compliance_score >= 80 ? 'var(--green)' : m.compliance_score >= 50 ? 'var(--yellow)' : 'var(--red)';
  $('pcDetailInfo').innerHTML = `
    <div class="info-row"><span class="info-label">Status</span><span style="color:${m.is_online ? 'var(--green)' : 'var(--text-muted)'}">${m.is_online ? '🟢 Online' : '⚫ Offline'}</span></div>
    <div class="info-row"><span class="info-label">Current App</span><span>${m.current_app || '—'}</span></div>
    <div class="info-row"><span class="info-label">Window</span><span style="font-size:.78rem;word-break:break-all">${m.current_title || '—'}</span></div>
    <div class="info-row"><span class="info-label">Compliance</span><span style="color:${scoreColor};font-weight:700">${m.compliance_score}%</span></div>
    <div class="info-row"><span class="info-label">Violations</span><span style="color:${m.violation_count > 0 ? 'var(--red)' : 'var(--green)'}">${m.violation_count}</span></div>
    <div class="info-row"><span class="info-label">Hostname</span><span>${m.hostname || '—'}</span></div>`;
  const acts = await api('GET', `/labs/${labId}/machines/${machineId}/activities`);
  const tl = $('pcTimeline');
  if (!acts || !acts.length) { tl.innerHTML = '<p style="color:var(--text-muted);font-size:.82rem">No activity recorded yet.</p>'; }
  else {
    tl.innerHTML = acts.map(a => {
      const t = new Date(a.start_time + 'Z').toLocaleTimeString();
      return `<div class="tl-item">
        <span class="tl-dot ${a.is_allowed ? 'allowed' : 'forbidden'}"></span>
        <span class="tl-app">${a.app_name || '?'}</span>
        <span class="tl-time">${t}</span>
      </div>`;
    }).join('');
  }
  $('pcDetailModal').style.display = 'flex';
}
function closePcDetail(e) { if (e.target === $('pcDetailModal')) closePcDetailModal(); }
function closePcDetailModal() { $('pcDetailModal').style.display = 'none'; }

// ── SESSION REPORT ────────────────────────────────────────────────────────────
function showReport(r) {
  const dur = r.duration_secs;
  const hm = `${Math.floor(dur/3600)}h ${Math.floor((dur%3600)/60)}m`;
  const rows = r.machines.map(m => {
    const cls = m.compliance_score >= 80 ? 'good' : m.compliance_score >= 50 ? 'medium' : 'bad';
    return `<tr><td>${m.pc_number}</td><td><span class="score-pill ${cls}">${m.compliance_score}%</span></td><td>${m.violation_count}</td></tr>`;
  }).join('');
  const topApps = r.top_apps.map(a => `<li>${a.app} — ${a.count}×</li>`).join('') || '<li>None</li>';
  $('reportBody').innerHTML = `
    <div class="report-hero"><h2>📊 ${r.subject_name}</h2><div class="report-sub">${new Date(r.started_at+'Z').toLocaleTimeString()} → ${new Date(r.ended_at+'Z').toLocaleTimeString()}</div></div>
    <div class="report-stats">
      <div class="report-stat"><div class="val">${hm}</div><div class="lbl">Duration</div></div>
      <div class="report-stat"><div class="val" style="color:var(--red)">${r.total_alerts}</div><div class="lbl">Total Alerts</div></div>
      <div class="report-stat"><div class="val">${r.machines.length}</div><div class="lbl">PCs Monitored</div></div>
    </div>
    <h4 style="margin:.5rem 0">PC Compliance</h4>
    <table class="report-table"><thead><tr><th>PC</th><th>Score</th><th>Violations</th></tr></thead><tbody>${rows}</tbody></table>
    <h4 style="margin:.75rem 0 .4rem">Top Unauthorized Apps</h4><ul style="padding-left:1.25rem;font-size:.85rem;color:var(--text-muted)">${topApps}</ul>`;
  $('reportModal').style.display = 'flex';
}

// ── MODALS ────────────────────────────────────────────────────────────────────
function closeModal(id, e) { if (!e || e.target.id === id) $(id).style.display = 'none'; }

// ── TOAST ─────────────────────────────────────────────────────────────────────
function showToast(type, title, msg, dur = 4000) {
  const icons = { alert: '🚨', success: '✅', info: 'ℹ️' };
  const t = document.createElement('div');
  t.className = `toast ${type}-toast`;
  t.innerHTML = `<span class="toast-icon">${icons[type]||'📢'}</span><div class="toast-body"><div class="toast-title">${title}</div><div class="toast-msg">${msg}</div></div><button class="toast-close" onclick="this.closest('.toast').remove()">✕</button>`;
  $('toastContainer').appendChild(t);
  setTimeout(() => t.remove(), dur);
}

// ── AUDIO ALERT ───────────────────────────────────────────────────────────────
function playAlertSound() {
  try {
    const ctx = new (window.AudioContext || window.webkitAudioContext)();
    [600, 800, 600].forEach((freq, i) => {
      const osc = ctx.createOscillator(), gain = ctx.createGain();
      osc.connect(gain); gain.connect(ctx.destination);
      osc.frequency.value = freq; gain.gain.setValueAtTime(0.2, ctx.currentTime + i * 0.15);
      gain.gain.exponentialRampToValueAtTime(0.001, ctx.currentTime + i * 0.15 + 0.12);
      osc.start(ctx.currentTime + i * 0.15); osc.stop(ctx.currentTime + i * 0.15 + 0.12);
    });
  } catch {}
}

// ── HISTORY ───────────────────────────────────────────────────────────────────
let activeHistoryTab = 'sessions';

function switchHistoryTab(tab) {
  activeHistoryTab = tab;
  document.querySelectorAll('.history-tab').forEach(b => b.classList.remove('active'));
  $('htab-' + tab).classList.add('active');
  loadHistory(tab);
}

async function loadHistory(tab) {
  const content = $('historyContent');
  content.innerHTML = '<div class="loading-spinner"><i class="fas fa-spinner fa-spin"></i> Loading...</div>';

  if (tab === 'sessions') {
    const sessions = await api('GET', `/labs/${labId}/history/sessions`);
    if (!sessions || !sessions.length) {
      content.innerHTML = '<div class="empty-state"><i class="fas fa-calendar-xmark"></i><p>No past sessions yet. Start and end a session to see history here.</p></div>';
      return;
    }
    content.innerHTML = `
      <table class="history-table">
        <thead>
          <tr>
            <th>Subject</th>
            <th>Date</th>
            <th>Start</th>
            <th>End</th>
            <th>Duration</th>
            <th>PCs</th>
            <th>Alerts</th>
            <th>Avg Compliance</th>
          </tr>
        </thead>
        <tbody>
          ${sessions.map(s => {
            const start = s.started_at ? new Date(s.started_at + 'Z') : null;
            const end   = s.ended_at   ? new Date(s.ended_at   + 'Z') : null;
            const dur   = s.duration_secs;
            const durStr = dur ? `${Math.floor(dur/3600)}h ${Math.floor((dur%3600)/60)}m ${dur%60}s` : '—';
            const scoreColor = s.avg_compliance >= 80 ? 'var(--green)' : s.avg_compliance >= 50 ? 'var(--yellow)' : 'var(--red)';
            return `<tr>
              <td><strong>${s.subject_name}</strong></td>
              <td>${start ? start.toLocaleDateString() : '—'}</td>
              <td>${start ? start.toLocaleTimeString() : '—'}</td>
              <td>${end   ? end.toLocaleTimeString()   : '—'}</td>
              <td>${durStr}</td>
              <td>${s.machines_count}</td>
              <td style="color:${s.alert_count > 0 ? 'var(--red)' : 'var(--green)'}">${s.alert_count}</td>
              <td><span style="color:${scoreColor};font-weight:700">${s.avg_compliance}%</span></td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  } else {
    const machines = await api('GET', `/labs/${labId}/history/machines`);
    if (!machines || !machines.length) {
      content.innerHTML = '<div class="empty-state"><i class="fas fa-desktop"></i><p>No machines registered yet.</p></div>';
      return;
    }
    content.innerHTML = `
      <table class="history-table">
        <thead>
          <tr>
            <th>PC</th>
            <th>Hostname</th>
            <th>Status</th>
            <th>Sessions</th>
            <th>Total Alerts</th>
            <th>Avg Compliance</th>
            <th>Last Session</th>
            <th>Last Seen</th>
          </tr>
        </thead>
        <tbody>
          ${machines.map(m => {
            const scoreColor = m.avg_compliance >= 80 ? 'var(--green)' : m.avg_compliance >= 50 ? 'var(--yellow)' : 'var(--red)';
            const lastSeen = m.last_seen ? new Date(m.last_seen + 'Z').toLocaleString() : 'Never';
            return `<tr>
              <td><strong>${m.pc_number}</strong></td>
              <td>${m.hostname || '—'}</td>
              <td><span style="color:${m.is_online ? 'var(--green)' : 'var(--text-muted)'}">${m.is_online ? '🟢 Online' : '⚫ Offline'}</span></td>
              <td>${m.sessions_count}</td>
              <td style="color:${m.total_alerts > 0 ? 'var(--red)' : 'var(--green)'}">${m.total_alerts}</td>
              <td><span style="color:${scoreColor};font-weight:700">${m.sessions_count > 0 ? m.avg_compliance + '%' : '—'}</span></td>
              <td>${m.last_session || '—'}</td>
              <td style="font-size:.78rem;color:var(--text-muted)">${lastSeen}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  }
}
