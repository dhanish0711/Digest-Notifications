document.addEventListener('DOMContentLoaded', () => {
  // Set default dates
  const todayStr = new Date().toISOString().split('T')[0];
  document.getElementById('refDate').value = todayStr;
  const tomorrow = new Date();
  tomorrow.setDate(tomorrow.getDate() + 1);
  document.getElementById('date').value = tomorrow.toISOString().split('T')[0];
  document.getElementById('time').value = '10:00';

  // State
  let currentGeneratedDigest = null;

  // Selectors — Digest Generator
  const interviewForm    = document.getElementById('interviewForm');
  const timelineList     = document.getElementById('timelineList');
  const totalCountBadge  = document.getElementById('totalCount');
  const generateBtn      = document.getElementById('generateBtn');
  const digestType       = document.getElementById('digestType');
  const refDateInput     = document.getElementById('refDate');
  const previewEmpty     = document.getElementById('previewEmpty');
  const previewTypeBadge = document.getElementById('previewTypeBadge');
  const previewDateRange = document.getElementById('previewDateRange');
  const previewIframe    = document.getElementById('previewIframe');
  const sendBtn          = document.getElementById('sendBtn');
  const logsList         = document.getElementById('logsList');
  const batchSizeBadge   = document.getElementById('batchSizeBadge');
  const textPreviewBox   = document.getElementById('textPreviewBox');

  // ── Load batch size config ────────────────────────────────────────────────
  fetch('/api/config')
    .then(r => r.json())
    .then(cfg => {
      if (batchSizeBadge) batchSizeBadge.textContent = `Batch limit: ${cfg.batch_size}`;
    });

  // ── Load and render interviews ────────────────────────────────────────────
  const loadInterviews = async () => {
    const res  = await fetch('/api/interviews');
    const list = await res.json();
    list.sort((a, b) => (a.date + ' ' + a.time).localeCompare(b.date + ' ' + b.time));
    totalCountBadge.textContent = list.length;
    timelineList.innerHTML = '';

    if (list.length === 0) {
      timelineList.innerHTML =
        '<div style="color:var(--text-muted);text-align:center;padding:20px;font-size:13px;">No interviews scheduled</div>';
      return;
    }

    list.forEach(interview => {
      const item = document.createElement('div');
      item.className = 'timeline-item';
      const dateObj = new Date(interview.date);
      const formattedDate = dateObj.toLocaleDateString('en-US', {
        weekday: 'short', month: 'short', day: 'numeric'
      });
      item.innerHTML = `
        <div class="timeline-content">
          <h4>${escapeHTML(interview.candidate_name)}</h4>
          <p>${escapeHTML(interview.role)}</p>
          <div class="timeline-meta">
            <span>🕒 ${interview.time}</span>
            <span>👤 ${escapeHTML(interview.interviewer_name)}</span>
            <span>📅 ${formattedDate}</span>
          </div>
        </div>
        <button class="btn-danger" data-id="${interview.id}">Delete</button>`;
      item.querySelector('.btn-danger').addEventListener('click', async e => {
        if (confirm('Delete this interview?')) await deleteInterview(e.target.dataset.id);
      });
      timelineList.appendChild(item);
    });
  };

  // ── Add interview ─────────────────────────────────────────────────────────
  interviewForm.addEventListener('submit', async e => {
    e.preventDefault();
    const body = {
      candidate_name:   document.getElementById('candidateName').value,
      role:             document.getElementById('role').value,
      interviewer_name: document.getElementById('interviewerName').value,
      date:             document.getElementById('date').value,
      time:             document.getElementById('time').value,
    };
    const res = await fetch('/api/interviews', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      interviewForm.reset();
      document.getElementById('date').value = tomorrow.toISOString().split('T')[0];
      document.getElementById('time').value = '10:00';
      await loadInterviews();
    } else {
      alert('Failed to schedule interview');
    }
  });

  // ── Delete interview ──────────────────────────────────────────────────────
  const deleteInterview = async id => {
    const res = await fetch(`/api/interviews?id=${id}`, { method: 'DELETE' });
    if (res.ok) await loadInterviews();
    else alert('Failed to delete interview');
  };

  // ── Generate Digest Preview ───────────────────────────────────────────────
  generateBtn.addEventListener('click', async () => {
    generateBtn.disabled = true;
    generateBtn.innerHTML = '<span>⚡</span> Generating...';

    const res  = await fetch('/api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: digestType.value, ref_date: refDateInput.value }),
    });
    const data = await res.json();

    generateBtn.disabled = false;
    generateBtn.innerHTML = '<span>⚡</span> Generate Preview';

    // ── Empty digest suppression UI ───────────────────────────────────────
    if (data.status === 'skipped') {
      previewEmpty.style.display  = 'flex';
      previewEmpty.querySelector('h3').textContent = 'No Interviews Found';
      previewEmpty.querySelector('p').textContent  =
        'There are no upcoming interviews for this period. Digest suppressed — nothing will be sent.';
      sendBtn.disabled  = true;
      sendBtn.className = 'btn btn-secondary';
      if (textPreviewBox) textPreviewBox.style.display = 'none';
      return;
    }

    if (data.status === 'success') {
      currentGeneratedDigest = {
        type: digestType.value, count: data.count, date_range: data.date_range
      };
      previewTypeBadge.textContent = digestType.value.toUpperCase();
      previewDateRange.textContent = data.date_range;

      // HTML iframe preview
      const doc = previewIframe.contentDocument || previewIframe.contentWindow.document;
      doc.open(); doc.write(data.html); doc.close();
      previewEmpty.style.display = 'none';
      previewEmpty.querySelector('h3').textContent = 'No Digest Generated Yet';
      previewEmpty.querySelector('p').textContent  =
        'Select your configuration above and click "Generate Preview" to review the email batch.';

      // Plain-text preview
      if (textPreviewBox && data.text) {
        textPreviewBox.textContent = data.text;
        textPreviewBox.style.display = 'block';
      }

      sendBtn.disabled  = false;
      sendBtn.className = 'btn';
    } else {
      alert('Error generating preview: ' + data.message);
    }
  });

  // ── Dispatch Email ────────────────────────────────────────────────────────
  sendBtn.addEventListener('click', async () => {
    if (!currentGeneratedDigest) return;
    sendBtn.disabled = true;
    sendBtn.innerHTML = '<span>📨</span> Sending...';

    const res  = await fetch('/api/send', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(currentGeneratedDigest),
    });
    const data = await res.json();

    if (data.status === 'success') {
      alert(data.message);
      sendBtn.disabled  = true;
      sendBtn.className = 'btn btn-secondary';
      sendBtn.innerHTML = '<span>📨</span> Dispatch Email Notification';
      previewEmpty.style.display = 'flex';
      previewIframe.src = 'about:blank';
      if (textPreviewBox) { textPreviewBox.textContent = ''; textPreviewBox.style.display = 'none'; }
      currentGeneratedDigest = null;
      await loadLogs();
    } else {
      alert(data.message || 'Failed to send digest');
      sendBtn.disabled  = false;
      sendBtn.innerHTML = '<span>📨</span> Dispatch Email Notification';
    }
  });

  // ── Load Dispatch Logs ────────────────────────────────────────────────────
  const loadLogs = async () => {
    const res  = await fetch('/api/logs');
    const logs = await res.json();
    logsList.innerHTML = '';
    if (logs.length === 0) {
      logsList.innerHTML =
        '<div style="color:var(--text-muted);text-align:center;padding:20px;font-size:13px;">No mail dispatches logged</div>';
      return;
    }
    logs.forEach(log => {
      const item = document.createElement('div');
      item.className = 'log-item';
      const timeStr = new Date(log.timestamp).toLocaleString();
      item.innerHTML = `
        <div class="log-left">
          <span class="log-title">${log.type} Digest (${log.count} Items)</span>
          <span class="log-sub">Sent: ${timeStr} &bull; To: ${escapeHTML(log.recipient)}</span>
        </div>
        <span class="log-badge">SENT</span>`;
      logsList.appendChild(item);
    });
  };

  // ── Helper ────────────────────────────────────────────────────────────────
  const escapeHTML = str => (str || '').replace(
    /[&<>'"]/g,
    t => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[t] || t)
  );

  // Initial load
  loadInterviews();
  loadLogs();
});
