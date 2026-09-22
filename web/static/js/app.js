/**
 * Comment Absorber Studio - Real-Time Web Application Client
 * Handles Server-Sent Events (SSE), real Facebook comment extraction,
 * session detection, Web Audio chimes, and instant exports.
 */

(function () {
  'use strict';

  // --- State ---
  const state = {
    comments: [],
    selectedMode: 'browser', // DEFAULT TO REAL BROWSER EXTRACTION
    sortOrder: 'newest',     // 'newest' | 'oldest'
    soundEnabled: true,
    autoScroll: true,
    isCollecting: false,
    searchQuery: '',
    eventSource: null,
    audioCtx: null,
    isLoggedIn: false,
    sessionPollInterval: null,
  };

  // --- DOM Elements ---
  const el = {
    postUrl: document.getElementById('post-url'),
    clearUrlBtn: document.getElementById('clear-url-btn'),
    engineCards: document.querySelectorAll('.engine-card'),
    engineDisplayBadge: document.getElementById('engine-display-badge'),
    
    // Facebook Session & Login Prompt
    fbSessionPill: document.getElementById('fb-session-pill'),
    fbSessionText: document.getElementById('fb-session-text'),
    btnRelogin: document.getElementById('btn-relogin'),
    fbLoginNotice: document.getElementById('fb-login-notice'),
    btnLoginPrompt: document.getElementById('btn-login-prompt'),
    btnDismissNotice: document.getElementById('btn-dismiss-notice'),

    // Actions
    btnStart: document.getElementById('btn-start'),
    btnStop: document.getElementById('btn-stop'),
    btnCollectAnother: document.getElementById('btn-collect-another'),
    btnExportExcel: document.getElementById('btn-export-excel'),
    btnExportCsv: document.getElementById('btn-export-csv'),
    btnClear: document.getElementById('btn-clear'),

    // Direct Paste Modal
    btnPasteModal: document.getElementById('btn-paste-modal'),
    pasteModal: document.getElementById('paste-modal'),
    btnClosePasteModal: document.getElementById('btn-close-paste-modal'),
    btnCancelPaste: document.getElementById('btn-cancel-paste'),
    btnDoPasteAbsorb: document.getElementById('btn-do-paste-absorb'),
    btnDemoTest: document.getElementById('btn-demo-test'),
    pasteInput: document.getElementById('paste-input'),
    statusMessage: document.getElementById('status-message'),
    liveIndicator: document.getElementById('live-indicator'),
    liveStatusText: document.getElementById('live-status-text'),
    soundToggle: document.getElementById('sound-toggle'),
    soundIcon: document.getElementById('sound-icon'),
    
    // KPIs
    kpiTotal: document.getElementById('kpi-total'),
    kpiSpeed: document.getElementById('kpi-speed'),
    kpiTime: document.getElementById('kpi-time'),
    kpiUnique: document.getElementById('kpi-unique'),
    
    // Spotlight Card
    spotlightTime: document.getElementById('spotlight-time'),
    spotlightAvatar: document.getElementById('spotlight-avatar'),
    spotlightAuthor: document.getElementById('spotlight-author'),
    spotlightText: document.getElementById('spotlight-text'),
    
    // Stream Feed
    feedCounter: document.getElementById('feed-counter'),
    feedSearch: document.getElementById('feed-search'),
    autoscrollToggle: document.getElementById('autoscroll-toggle'),
    sortToggleBtn: document.getElementById('sort-toggle-btn'),
    sortLabel: document.getElementById('sort-label'),
    streamContainer: document.getElementById('stream-container'),
    streamEmpty: document.getElementById('stream-empty'),
    streamList: document.getElementById('stream-list'),
    
    toastContainer: document.getElementById('toast-container'),
  };

  // --- Web Audio Chime ---
  function playCommentChime() {
    if (!state.soundEnabled) return;
    try {
      if (!state.audioCtx) {
        state.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      }
      if (state.audioCtx.state === 'suspended') {
        state.audioCtx.resume();
      }
      const osc = state.audioCtx.createOscillator();
      const gain = state.audioCtx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(587.33, state.audioCtx.currentTime); // D5
      osc.frequency.exponentialRampToValueAtTime(880, state.audioCtx.currentTime + 0.08); // A5
      gain.gain.setValueAtTime(0.04, state.audioCtx.currentTime);
      gain.gain.exponentialRampToValueAtTime(0.001, state.audioCtx.currentTime + 0.12);
      osc.connect(gain);
      gain.connect(state.audioCtx.destination);
      osc.start();
      osc.stop(state.audioCtx.currentTime + 0.12);
    } catch (e) {}
  }

  // --- Toast Notifications ---
  function showToast(message, type = 'info') {
    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    const icons = { success: '&#9989;', error: '&#10060;', info: '&#8505;' };
    toast.innerHTML = `<span>${icons[type] || '&#8505;'}</span><span>${escapeHtml(message)}</span>`;
    el.toastContainer.appendChild(toast);
    setTimeout(() => {
      toast.style.opacity = '0';
      setTimeout(() => toast.remove(), 250);
    }, 4000);
  }

  function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text || '';
    return div.innerHTML;
  }

  // --- Check Facebook Session ---
  async function checkFacebookSession() {
    try {
      const resp = await fetch('/api/auth/status');
      const data = await resp.json();
      state.isLoggedIn = !!data.logged_in;
      if (data.logged_in) {
        if (el.fbSessionPill) el.fbSessionPill.className = 'session-badge connected';
        if (el.fbSessionText) el.fbSessionText.innerHTML = 'Facebook: Logged In &#10004;';
        if (el.btnRelogin) el.btnRelogin.style.display = 'none';
        if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'none';
      } else {
        if (el.fbSessionPill) el.fbSessionPill.className = 'session-badge';
        if (el.fbSessionText) el.fbSessionText.innerHTML = 'Facebook: Not Logged In';
        if (el.btnRelogin) el.btnRelogin.style.display = 'inline-flex';
        if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'flex';
        if (el.statusMessage) {
          el.statusMessage.textContent = 'Please log in to your Facebook account to access post comments from Facebook.';
        }
      }
    } catch (e) {
      if (el.fbSessionText) el.fbSessionText.textContent = 'Facebook Session: Ready';
    }
  }

  function startLoginFlow() {
    showToast('Opening Facebook login window in Chrome...', 'info');
    if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'flex';
    if (el.statusMessage) {
      el.statusMessage.textContent = 'Please log in to your Facebook account in the browser window to access post comments.';
    }
    fetch('/api/auth/login', { method: 'POST' }).catch(() => {});

    // Poll for login completion automatically
    if (state.sessionPollInterval) clearInterval(state.sessionPollInterval);
    let attempts = 0;
    state.sessionPollInterval = setInterval(async () => {
      attempts++;
      if (attempts > 60) {
        clearInterval(state.sessionPollInterval);
        return;
      }
      try {
        const resp = await fetch('/api/auth/status');
        const data = await resp.json();
        if (data.logged_in) {
          clearInterval(state.sessionPollInterval);
          state.isLoggedIn = true;
          if (el.fbSessionPill) el.fbSessionPill.className = 'session-badge connected';
          if (el.fbSessionText) el.fbSessionText.innerHTML = 'Facebook: Logged In &#10004;';
          if (el.btnRelogin) el.btnRelogin.style.display = 'none';
          if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'none';
          showToast('Facebook logged in successfully! You can now start collecting comments.', 'success');
          if (el.statusMessage) {
            el.statusMessage.textContent = 'Facebook connected. Ready to absorb comments.';
          }
        }
      } catch (err) {}
    }, 2500);
  }

  // --- Format Duration ---
  function formatDuration(sec) {
    const s = Math.floor(sec || 0);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `${String(m).padStart(2, '0')}:${String(r).padStart(2, '0')}`;
  }

  function updateKpis(stats) {
    if (!stats) return;
    el.kpiTotal.textContent = Number(stats.count || 0).toLocaleString();
    el.kpiSpeed.innerHTML = `${stats.comments_per_sec || 0} <small style="font-size:14px;font-weight:600">/sec</small>`;
    el.kpiTime.textContent = formatDuration(stats.elapsed_seconds || 0);
    el.kpiUnique.textContent = Number(stats.unique_authors || 0).toLocaleString();
    el.feedCounter.textContent = Number(stats.count || 0).toLocaleString();

    const hasComments = (stats.count || 0) > 0;
    el.btnExportExcel.disabled = !hasComments;
    el.btnExportCsv.disabled = !hasComments;
  }

  function updateSpotlight(comment) {
    if (!comment) return;
    el.spotlightAuthor.textContent = comment.user_name || 'Facebook User';
    el.spotlightText.textContent = comment.message || '(empty message)';
    el.spotlightTime.textContent = comment.created_time ? `Absorbed at ${comment.created_time}` : 'Just now';
    el.spotlightAvatar.textContent = comment.avatar_initials || 'FB';
    el.spotlightAvatar.style.backgroundColor = comment.avatar_color || '#1877F2';

    const spotCard = document.getElementById('spotlight-section');
    if (spotCard) {
      spotCard.style.borderColor = '#22d3ee';
      setTimeout(() => {
        spotCard.style.borderColor = 'rgba(6, 182, 212, 0.35)';
      }, 350);
    }
  }

  function createCommentRowElement(c, isLatest = false) {
    const row = document.createElement('div');
    row.className = `comment-row ${isLatest ? 'is-latest' : ''}`;
    row.id = `comment-${c.comment_id}`;
    row.innerHTML = `
      <div class="row-index">#${c.index}</div>
      <div class="row-avatar" style="background-color: ${escapeHtml(c.avatar_color || '#1877f2')}">
        ${escapeHtml(c.avatar_initials || 'FB')}
      </div>
      <div class="row-content">
        <div class="row-header">
          <div class="row-author">${escapeHtml(c.user_name || 'Facebook User')}</div>
          <div class="row-time">${escapeHtml(c.created_time || '')}</div>
        </div>
        <div class="row-message">${escapeHtml(c.message || '')}</div>
      </div>
    `;
    return row;
  }

  function renderCommentsList() {
    const query = state.searchQuery.trim().toLowerCase();
    let filtered = state.comments;
    if (query) {
      filtered = state.comments.filter(
        c => (c.user_name && c.user_name.toLowerCase().includes(query)) ||
             (c.message && c.message.toLowerCase().includes(query))
      );
    }

    if (state.sortOrder === 'oldest') {
      filtered = [...filtered].sort((a, b) => a.timestamp_raw - b.timestamp_raw);
    } else {
      filtered = [...filtered].sort((a, b) => b.timestamp_raw - a.timestamp_raw);
    }

    if (filtered.length === 0) {
      el.streamEmpty.style.display = 'block';
      el.streamList.innerHTML = '';
      if (query && state.comments.length > 0) {
        el.streamEmpty.querySelector('.empty-title').textContent = 'No matching comments found';
        el.streamEmpty.querySelector('.empty-desc').textContent = `No comments match "${query}".`;
      } else {
        el.streamEmpty.querySelector('.empty-title').textContent = 'No comments collected yet';
        el.streamEmpty.querySelector('.empty-desc').textContent = 'Enter your Facebook post URL above and click Start Collecting Real Comments.';
      }
      return;
    }

    el.streamEmpty.style.display = 'none';
    const fragment = document.createDocumentFragment();
    filtered.forEach((c, idx) => {
      const isLatest = (idx === 0 && state.sortOrder === 'newest') || (idx === filtered.length - 1 && state.sortOrder === 'oldest');
      fragment.appendChild(createCommentRowElement(c, isLatest && state.isCollecting));
    });

    el.streamList.innerHTML = '';
    el.streamList.appendChild(fragment);

    if (state.autoScroll) {
      scrollToTarget();
    }
  }

  function scrollToTarget() {
    if (state.sortOrder === 'newest') {
      el.streamContainer.scrollTop = 0;
    } else {
      el.streamContainer.scrollTop = el.streamContainer.scrollHeight;
    }
  }

  function appendNewComment(comment) {
    state.comments.push(comment);

    // Update Spotlight Card
    updateSpotlight(comment);

    // Audio chime
    playCommentChime();

    // Check search filter
    const q = state.searchQuery.trim().toLowerCase();
    const matches = !q || (
      (comment.user_name && comment.user_name.toLowerCase().includes(q)) ||
      (comment.message && comment.message.toLowerCase().includes(q))
    );

    if (matches) {
      el.streamEmpty.style.display = 'none';
      const row = createCommentRowElement(comment, true);
      
      const prevLatest = el.streamList.querySelectorAll('.comment-row.is-latest');
      prevLatest.forEach(r => r.classList.remove('is-latest'));

      if (state.sortOrder === 'newest') {
        el.streamList.prepend(row);
      } else {
        el.streamList.appendChild(row);
      }

      if (state.autoScroll) {
        scrollToTarget();
      }
    }
  }

  function updateStatusUI(status, message) {
    el.statusMessage.textContent = message || '';

    if (status === 'COLLECTING' || status === 'CONNECTING' || status === 'ACCESSING') {
      state.isCollecting = true;
      el.liveIndicator.className = 'status-pill status-ongoing';
      el.liveStatusText.textContent = 'Ongoing';
      el.btnStart.disabled = true;
      el.btnStop.disabled = false;
    } else if (status === 'COMPLETED') {
      state.isCollecting = false;
      el.liveIndicator.className = 'status-pill status-done';
      el.liveStatusText.textContent = 'Done';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Comment collection done!', 'success');
    } else if (status === 'CANCELLED') {
      state.isCollecting = false;
      el.liveIndicator.className = 'status-pill status-stopped';
      el.liveStatusText.textContent = 'Stopped';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Collection stopped.', 'info');
    } else if (status === 'ERROR') {
      state.isCollecting = false;
      el.liveIndicator.className = 'status-pill status-error';
      el.liveStatusText.textContent = 'Error';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Error occurred during collection.', 'error');
    } else {
      state.isCollecting = false;
      el.liveIndicator.className = 'status-pill status-ready';
      el.liveStatusText.textContent = 'Ready';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
    }
  }

  // --- SSE Connection ---
  function initEventStream() {
    if (state.eventSource) {
      state.eventSource.close();
    }

    state.eventSource = new EventSource('/api/collect/stream');

    state.eventSource.addEventListener('init', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.stats) updateKpis(data.stats);
        if (data.comments && Array.isArray(data.comments)) {
          state.comments = data.comments;
          renderCommentsList();
        }
        if (data.stats && data.stats.latest_comment) {
          updateSpotlight(data.stats.latest_comment);
        }
      } catch (err) {
        console.error('Error in init event', err);
      }
    });

    state.eventSource.addEventListener('comment', (e) => {
      try {
        const data = JSON.parse(e.data);
        if (data.comment) {
          appendNewComment(data.comment);
        }
        if (data.stats) {
          updateKpis(data.stats);
        }
      } catch (err) {
        console.error('Error in comment event', err);
      }
    });

    state.eventSource.addEventListener('status', (e) => {
      try {
        const data = JSON.parse(e.data);
        updateStatusUI(data.status, data.message);
        if (data.stats) updateKpis(data.stats);
        if (data.message && data.message.toLowerCase().includes('log in') || data.message && data.message.toLowerCase().includes('login')) {
          if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'flex';
          if (el.btnRelogin) el.btnRelogin.style.display = 'inline-flex';
        }
      } catch (err) {
        console.error('Error in status event', err);
      }
    });

    state.eventSource.addEventListener('clear', (e) => {
      try {
        const data = JSON.parse(e.data);
        state.comments = [];
        updateKpis(data.stats);
        renderCommentsList();
        el.spotlightAuthor.textContent = 'System Ready';
        el.spotlightText.textContent = 'Paste your Facebook post URL and click Start Collecting Real Comments.';
        el.spotlightTime.textContent = 'Waiting to collect...';
        el.spotlightAvatar.textContent = 'FB';
        el.spotlightAvatar.style.backgroundColor = '#1877F2';
      } catch (err) {}
    });

    state.eventSource.onerror = (err) => {
      console.warn('SSE stream disconnected, reconnecting in 3s...', err);
    };
  }

  // --- Action Handlers ---

  async function handleStart() {
    const url = (el.postUrl.value || '').trim();
    const mode = state.selectedMode;

    // Strict validation for real scraper
    if (mode === 'browser') {
      if (!url) {
        showToast('Please paste a Facebook post URL first!', 'error');
        el.postUrl.focus();
        el.postUrl.style.borderColor = '#ef4444';
        setTimeout(() => { el.postUrl.style.borderColor = ''; }, 2000);
        return;
      }
      if (!url.toLowerCase().includes('facebook.com') && !url.toLowerCase().includes('fb.com')) {
        showToast('The URL must be a valid Facebook link (e.g. facebook.com/...)', 'error');
        el.postUrl.focus();
        return;
      }
      if (!state.isLoggedIn) {
        showToast('Please log in to your Facebook account to access post comments from Facebook.', 'error');
        if (el.fbLoginNotice) {
          el.fbLoginNotice.style.display = 'flex';
          el.fbLoginNotice.scrollIntoView({ behavior: 'smooth', block: 'center' });
        }
        startLoginFlow();
        return;
      }
    }

    try {
      updateStatusUI('CONNECTING', 'Initiating comment extraction...');
      const resp = await fetch('/api/collect/start', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: url,
          mode: mode,
          max_comments: 200,
          speed: 0.25
        })
      });

      if (resp.status === 404) {
        // Static GitHub Pages environment
        updateStatusUI('IDLE', 'Static Web Mode (GitHub Pages)');
        showToast('Running on GitHub Pages. Use "Paste Comments Directly" or load sample comments to absorb in your browser!', 'info');
        if (el.pasteModal) {
          el.pasteModal.style.display = 'flex';
          if (el.pasteInput) el.pasteInput.focus();
        }
        return;
      }

      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Failed to start collection.', 'error');
        updateStatusUI('ERROR', res.error);
      } else {
        showToast(`Targeting post: ${url.slice(0, 45)}...`, 'info');
      }
    } catch (err) {
      // Offline / GitHub Pages static fallback
      showToast('Static Web Mode: Open "Paste Comments Directly" to absorb Facebook comments in browser!', 'info');
      updateStatusUI('IDLE', 'Static Web Mode. Paste comments directly or connect local backend.');
      if (el.pasteModal) el.pasteModal.style.display = 'flex';
    }
  }

  async function handleStop() {
    try {
      const resp = await fetch('/api/collect/stop', { method: 'POST' });
      const res = await resp.json();
      if (res.success) {
        showToast('Collection stopped.', 'info');
      }
    } catch (err) {
      state.isCollecting = false;
      updateStatusUI('CANCELLED', 'Collection stopped.');
      showToast('Collection stopped.', 'info');
    }
  }

  async function handleClear() {
    if (state.comments.length > 0 && !confirm('Clear all collected comments from feed?')) {
      return;
    }
    try {
      await fetch('/api/collect/clear', { method: 'POST' });
      showToast('Feed cleared.', 'info');
    } catch (err) {
      state.comments = [];
      renderCommentsList();
      updateKpis({ count: 0, unique_authors: 0, elapsed_seconds: 0, comments_per_sec: 0 });
      showToast('Feed cleared.', 'info');
    }
  }

  async function handleCollectAnother() {
    if (state.isCollecting) {
      try {
        await fetch('/api/collect/stop', { method: 'POST' });
      } catch (e) {}
    }
    try {
      await fetch('/api/collect/clear', { method: 'POST' });
    } catch (e) {}

    state.comments = [];
    state.isCollecting = false;
    el.postUrl.value = '';
    renderCommentsList();
    updateKpis({ count: 0, unique_authors: 0, elapsed_seconds: 0, comments_per_sec: 0 });

    el.spotlightAuthor.textContent = 'System Ready';
    el.spotlightText.textContent = 'Comments absorbed by the system will be displayed here live in real-time as they stream in.';
    el.spotlightTime.textContent = 'Waiting to collect...';
    el.spotlightAvatar.textContent = 'FB';
    el.spotlightAvatar.style.backgroundColor = '#1877f2';

    updateStatusUI('IDLE', 'Ready. Paste your new Facebook post or reel URL and click Start Collecting.');
    el.postUrl.focus();
    showToast('Ready for new link! Paste your Facebook post URL.', 'info');
  }

  function escapeXml(unsafe) {
    return String(unsafe || '').replace(/[<>&'"]/g, function (c) {
      switch (c) {
        case '<': return '&lt;';
        case '>': return '&gt;';
        case '&': return '&amp;';
        case '\'': return '&apos;';
        case '"': return '&quot;';
      }
    });
  }

  async function handleExport(format) {
    if (!state.comments.length) {
      showToast('No comments to export.', 'error');
      return;
    }
    const sort = state.sortOrder === 'oldest' ? 'oldest' : 'newest';
    let sortedComments = [...state.comments];
    if (sort === 'oldest') {
      sortedComments.sort((a, b) => a.timestamp_raw - b.timestamp_raw);
    } else {
      sortedComments.sort((a, b) => b.timestamp_raw - a.timestamp_raw);
    }

    // Try server endpoint first
    try {
      const endpoint = format === 'excel' ? `/api/export/excel?sort=${sort}` : `/api/export/csv?sort=${sort}`;
      const resp = await fetch(endpoint);
      if (resp.ok) {
        const blob = await resp.blob();
        const url = window.URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        const now = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '_');
        link.download = format === 'excel' ? `Facebook_Comments_${now}.xlsx` : `Facebook_Comments_${now}.csv`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        window.URL.revokeObjectURL(url);
        showToast(`Downloaded ${format.toUpperCase()} spreadsheet!`, 'success');
        return;
      }
    } catch (e) {
      // Server not reachable (e.g. running on GitHub Pages) -> Fall through to client-side exporter
    }

    // Universal Client-Side Export (Works 100% on GitHub Pages & Static Hosts)
    const timestamp = new Date().toISOString().slice(0, 19).replace(/[-:T]/g, '_');
    if (format === 'csv') {
      const bom = '\uFEFF';
      let csvContent = bom + '"User","Comment","Date"\r\n';
      sortedComments.forEach(c => {
        const u = '"' + (c.user_name || 'Facebook User').replace(/"/g, '""') + '"';
        const m = '"' + (c.message || '').replace(/"/g, '""') + '"';
        const d = '"' + (c.created_time || '').replace(/"/g, '""') + '"';
        csvContent += `${u},${m},${d}\r\n`;
      });
      const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `Facebook_Comments_${timestamp}.csv`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showToast('Downloaded CSV spreadsheet directly!', 'success');
    } else {
      // Universal Excel XML Spreadsheet (Opens natively in Microsoft Excel with headers)
      let xml = `<?xml version="1.0"?>
<?mso-application progid="Excel.Sheet"?>
<Workbook xmlns="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:o="urn:schemas-microsoft-com:office:office"
 xmlns:x="urn:schemas-microsoft-com:office:excel"
 xmlns:ss="urn:schemas-microsoft-com:office:spreadsheet"
 xmlns:html="http://www.w3.org/TR/REC-html40">
 <Styles>
  <Style ss:ID="Header">
   <Font ss:Bold="1" ss:Color="#FFFFFF" ss:Size="11" ss:FontName="Segoe UI"/>
   <Interior ss:Color="#1877F2" ss:Pattern="Solid"/>
   <Alignment ss:Horizontal="Center" ss:Vertical="Center"/>
  </Style>
  <Style ss:ID="Row">
   <Font ss:Size="10" ss:FontName="Segoe UI"/>
   <Alignment ss:Vertical="Top" ss:WrapText="1"/>
  </Style>
 </Styles>
 <Worksheet ss:Name="Facebook Comments">
  <Table ss:DefaultRowHeight="20">
   <Column ss:Width="160"/>
   <Column ss:Width="360"/>
   <Column ss:Width="140"/>
   <Row ss:StyleID="Header" ss:Height="26">
    <Cell><Data ss:Type="String">User</Data></Cell>
    <Cell><Data ss:Type="String">Comment</Data></Cell>
    <Cell><Data ss:Type="String">Date</Data></Cell>
   </Row>`;

      sortedComments.forEach(c => {
        const u = escapeXml(c.user_name || 'Facebook User');
        const m = escapeXml(c.message || '');
        const d = escapeXml(c.created_time || '');
        xml += `
   <Row ss:StyleID="Row">
    <Cell><Data ss:Type="String">${u}</Data></Cell>
    <Cell><Data ss:Type="String">${m}</Data></Cell>
    <Cell><Data ss:Type="String">${d}</Data></Cell>
   </Row>`;
      });

      xml += `
  </Table>
 </Worksheet>
</Workbook>`;

      const blob = new Blob([xml], { type: 'application/vnd.ms-excel;charset=utf-8;' });
      const url = URL.createObjectURL(blob);
      const link = document.createElement('a');
      link.href = url;
      link.download = `Facebook_Comments_${timestamp}.xls`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      URL.revokeObjectURL(url);
      showToast('Downloaded Excel (.xls) spreadsheet directly!', 'success');
    }
  }

  // --- Client-Side Comment Text & HTML Parser ---
  function parsePastedComments(text) {
    if (!text || !text.trim()) return [];
    
    // Check if HTML was pasted
    let plain = text;
    if (text.includes('<div') || text.includes('<span') || text.includes('<p')) {
      const temp = document.createElement('div');
      temp.innerHTML = text;
      const commentEls = temp.querySelectorAll('[aria-label*="Comment by"], [aria-label*="Reply by"], [role="article"]');
      if (commentEls.length > 0) {
        const parsed = [];
        commentEls.forEach(el => {
          const authorEl = el.querySelector('a[role="link"] span, h3 span, strong');
          const author = authorEl ? authorEl.textContent.trim() : 'Facebook User';
          const msgEl = el.querySelector('div[dir="auto"]');
          const msg = msgEl ? msgEl.textContent.trim() : el.textContent.trim();
          if (author && msg && msg !== author) {
            parsed.push({ author, message: msg, time: 'Just now' });
          }
        });
        if (parsed.length > 0) return parsed;
      }
      plain = temp.innerText || temp.textContent || text;
    }

    const lines = plain.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const parsed = [];
    const badgeWords = /^(Top fan|Author|Follow|Shared by author|Admin|Moderator|Group expert|\d+[smhdw]|yesterday|just now|\d+ (mins?|hours?|days?|weeks?) ago)$/i;

    let currentAuthor = '';
    let currentMsg = '';
    let currentTime = 'Just now';

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (badgeWords.test(line)) {
        if (/(\d+[smhdw]|yesterday|just now|ago)/i.test(line)) {
          currentTime = line;
        }
        continue;
      }

      const isName = /^[A-Z][a-zA-Z0-9.'\- ]{1,35}$/.test(line) && !line.includes('?') && !line.includes('!') && line.length < 35;

      if (isName && currentAuthor && currentMsg) {
        parsed.push({ author: currentAuthor, message: currentMsg, time: currentTime });
        currentAuthor = line;
        currentMsg = '';
        currentTime = 'Just now';
      } else if (!currentAuthor && isName) {
        currentAuthor = line;
      } else if (currentAuthor) {
        currentMsg = currentMsg ? (currentMsg + ' ' + line) : line;
      } else {
        parsed.push({ author: 'Facebook User', message: line, time: 'Just now' });
      }
    }

    if (currentAuthor && currentMsg) {
      parsed.push({ author: currentAuthor, message: currentMsg, time: currentTime });
    }

    return parsed;
  }

  function startClientSideAbsorption(parsedList) {
    if (!parsedList || !parsedList.length) {
      showToast('No valid comments detected in pasted text.', 'error');
      return;
    }

    updateStatusUI('COLLECTING', `Absorbing ${parsedList.length} comments...`);
    state.isCollecting = true;
    let idx = state.comments.length;
    let counter = 0;
    const startTime = Date.now();

    const interval = setInterval(() => {
      if (counter >= parsedList.length || !state.isCollecting) {
        clearInterval(interval);
        updateStatusUI('COMPLETED', `Done! Absorbed ${parsedList.length} comments.`);
        showToast(`Successfully absorbed ${parsedList.length} comments!`, 'success');
        return;
      }

      const item = parsedList[counter];
      counter++;
      idx++;

      const avatarColors = ['#1877F2', '#10B981', '#6366F1', '#EC4899', '#F59E0B', '#8B5CF6'];
      const initials = (item.author || 'FB').split(' ').map(p => p[0]).join('').slice(0, 2).toUpperCase() || 'FB';
      const color = avatarColors[counter % avatarColors.length];

      const now = new Date();
      const dateStr = `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')} ${String(now.getHours()).padStart(2,'0')}:${String(now.getMinutes()).padStart(2,'0')}:${String(now.getSeconds()).padStart(2,'0')}`;

      const commentObj = {
        index: idx,
        comment_id: 'client_' + Date.now() + '_' + counter,
        user_name: item.author || 'Facebook User',
        message: item.message || '',
        created_time: item.time && item.time !== 'Just now' ? item.time : dateStr,
        timestamp_raw: Date.now() / 1000,
        avatar_initials: initials,
        avatar_color: color
      };

      appendNewComment(commentObj);

      const elapsed = (Date.now() - startTime) / 1000;
      const speed = (counter / Math.max(elapsed, 0.1)).toFixed(1);
      const uniqueCount = new Set(state.comments.map(c => c.user_name)).size;
      updateKpis({
        count: state.comments.length,
        unique_authors: uniqueCount,
        elapsed_seconds: Math.floor(elapsed),
        comments_per_sec: parseFloat(speed)
      });
    }, 80);
  }

  // --- Event Listeners Setup ---
  function setupEventListeners() {
    // Engine Selector Cards
    el.engineCards.forEach(card => {
      card.addEventListener('click', () => {
        el.engineCards.forEach(c => c.classList.remove('active'));
        card.classList.add('active');
        const radio = card.querySelector('input[type="radio"]');
        if (radio) radio.checked = true;
        
        state.selectedMode = card.dataset.mode;
        
        const badgeMap = {
          browser: '&#9889; Real Facebook Extractor',
          simulator: '&#127918; Offline Demo / Simulation'
        };
        el.engineDisplayBadge.innerHTML = badgeMap[state.selectedMode] || state.selectedMode;

        if (state.selectedMode === 'browser') {
          el.btnStart.querySelector('span:last-child').textContent = 'Start Collecting Real Comments';
        } else {
          el.btnStart.querySelector('span:last-child').textContent = 'Start Demo Simulation';
        }
      });
    });

    // Clear URL button
    if (el.clearUrlBtn && el.postUrl) {
      el.clearUrlBtn.addEventListener('click', () => {
        el.postUrl.value = '';
        el.postUrl.focus();
      });
    }

    // Facebook Login actions
    if (el.btnLoginPrompt) {
      el.btnLoginPrompt.addEventListener('click', startLoginFlow);
    }
    if (el.btnDismissNotice) {
      el.btnDismissNotice.addEventListener('click', () => {
        if (el.fbLoginNotice) el.fbLoginNotice.style.display = 'none';
      });
    }
    if (el.btnRelogin) {
      el.btnRelogin.addEventListener('click', startLoginFlow);
    }

    // Sound Chime Toggle
    if (el.soundToggle) {
      el.soundToggle.addEventListener('click', () => {
        state.soundEnabled = !state.soundEnabled;
        if (el.soundIcon) {
          el.soundIcon.innerHTML = state.soundEnabled ? '&#128266;' : '&#128263;';
        }
        showToast(state.soundEnabled ? 'Chime sound enabled' : 'Chime sound muted', 'info');
        try {
          localStorage.setItem('comment_absorber_sound', state.soundEnabled ? '1' : '0');
        } catch (e) {}
      });
    }

    // Auto-scroll Checkbox
    if (el.autoscrollToggle) {
      el.autoscrollToggle.addEventListener('change', (e) => {
        state.autoScroll = e.target.checked;
        if (state.autoScroll) {
          scrollToTarget();
        }
      });
    }

    if (el.streamContainer) {
      el.streamContainer.addEventListener('scroll', () => {
        if (state.sortOrder === 'newest') {
          if (el.streamContainer.scrollTop > 50 && state.autoScroll) {
            state.autoScroll = false;
            if (el.autoscrollToggle) el.autoscrollToggle.checked = false;
          }
        } else {
          const isNearBottom = (el.streamContainer.scrollHeight - el.streamContainer.scrollTop - el.streamContainer.clientHeight) < 50;
          if (!isNearBottom && state.autoScroll) {
            state.autoScroll = false;
            if (el.autoscrollToggle) el.autoscrollToggle.checked = false;
          }
        }
      });
    }

    // Sort Toggle Button
    if (el.sortToggleBtn) {
      el.sortToggleBtn.addEventListener('click', () => {
        if (state.sortOrder === 'newest') {
          state.sortOrder = 'oldest';
          if (el.sortLabel) el.sortLabel.innerHTML = '&#8593; Oldest First';
        } else {
          state.sortOrder = 'newest';
          if (el.sortLabel) el.sortLabel.innerHTML = '&#8595; Newest First';
        }
        renderCommentsList();
        showToast(`Sorted by ${state.sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}`, 'info');
      });
    }

    // Live Search Filter
    if (el.feedSearch) {
      el.feedSearch.addEventListener('input', (e) => {
        state.searchQuery = e.target.value;
        renderCommentsList();
      });
    }

    // Main Buttons
    if (el.btnStart) el.btnStart.addEventListener('click', handleStart);
    if (el.btnStop) el.btnStop.addEventListener('click', handleStop);
    if (el.btnCollectAnother) el.btnCollectAnother.addEventListener('click', handleCollectAnother);
    if (el.btnClear) el.btnClear.addEventListener('click', handleClear);
    if (el.btnExportExcel) el.btnExportExcel.addEventListener('click', () => handleExport('excel'));
    if (el.btnExportCsv) el.btnExportCsv.addEventListener('click', () => handleExport('csv'));

    // Direct Paste Modal Listeners
    if (el.btnPasteModal) {
      el.btnPasteModal.addEventListener('click', () => {
        if (el.pasteModal) {
          el.pasteModal.style.display = 'flex';
          if (el.pasteInput) el.pasteInput.focus();
        }
      });
    }
    if (el.btnClosePasteModal) {
      el.btnClosePasteModal.addEventListener('click', () => {
        if (el.pasteModal) el.pasteModal.style.display = 'none';
      });
    }
    if (el.btnCancelPaste) {
      el.btnCancelPaste.addEventListener('click', () => {
        if (el.pasteModal) el.pasteModal.style.display = 'none';
      });
    }
    if (el.btnDemoTest) {
      el.btnDemoTest.addEventListener('click', () => {
        const sampleText = `Maria Santos
Top fan
1h
Mine 1 set please! Available pa po ba with COD delivery? Salamat po!

Juan Dela Cruz
Author
45m
Super legit seller! Received my order in perfect condition. Highly recommended!

Angelica Gomez
30m
How much po shipping fee to Cebu City? Interested to order 2 boxes.

Reynaldo Bautista
12m
Pa-order po ng 1 piece medium size, cash on delivery po. Thank you!

Kaye Anne Mendoza
just now
Ganda ng product! Will definitely order again next week! ✨`;
        if (el.pasteInput) el.pasteInput.value = sampleText;
        showToast('Sample comments loaded into box. Click Absorb Comments!', 'info');
      });
    }
    if (el.btnDoPasteAbsorb) {
      el.btnDoPasteAbsorb.addEventListener('click', () => {
        const text = el.pasteInput ? el.pasteInput.value : '';
        if (!text || !text.trim()) {
          showToast('Please paste comments text or HTML first!', 'error');
          return;
        }
        const parsed = parsePastedComments(text);
        if (parsed.length === 0) {
          showToast('Could not parse comments. Make sure text includes author and comment message.', 'error');
          return;
        }
        if (el.pasteModal) el.pasteModal.style.display = 'none';
        showToast(`Parsed ${parsed.length} comments! Absorbing...`, 'info');
        startClientSideAbsorption(parsed);
      });
    }

    if (el.postUrl) {
      el.postUrl.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
          handleStart();
        }
      });
    }
  }

  // --- Initialization ---
  function init() {
    try {
      const savedSound = localStorage.getItem('comment_absorber_sound');
      if (savedSound !== null) {
        state.soundEnabled = (savedSound === '1');
        el.soundIcon.innerHTML = state.soundEnabled ? '&#128266;' : '&#128263;';
      }
    } catch (e) {}

    setupEventListeners();
    initEventStream();
    checkFacebookSession();
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
