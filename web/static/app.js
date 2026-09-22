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
  };

  // --- DOM Elements ---
  const el = {
    postUrl: document.getElementById('post-url'),
    clearUrlBtn: document.getElementById('clear-url-btn'),
    engineCards: document.querySelectorAll('.engine-card'),
    engineDisplayBadge: document.getElementById('engine-display-badge'),
    
    // Facebook Session
    fbSessionPill: document.getElementById('fb-session-pill'),
    fbSessionText: document.getElementById('fb-session-text'),
    btnRelogin: document.getElementById('btn-relogin'),

    // Actions
    btnStart: document.getElementById('btn-start'),
    btnStop: document.getElementById('btn-stop'),
    btnExportExcel: document.getElementById('btn-export-excel'),
    btnExportCsv: document.getElementById('btn-export-csv'),
    btnClear: document.getElementById('btn-clear'),
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
      if (data.logged_in) {
        el.fbSessionPill.className = 'fb-session-pill logged-in';
        el.fbSessionText.innerHTML = 'Facebook: Logged In &#10004;';
        el.btnRelogin.style.display = 'none';
      } else {
        el.fbSessionPill.className = 'fb-session-pill';
        el.fbSessionText.innerHTML = 'Facebook: Not Logged In';
        el.btnRelogin.style.display = 'inline-flex';
      }
    } catch (e) {
      el.fbSessionText.textContent = 'Facebook Session: Ready';
    }
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
      el.liveIndicator.className = 'live-status-pill status-active';
      el.liveStatusText.textContent = status === 'COLLECTING' ? 'LIVE STREAMING' : status;
      el.btnStart.disabled = true;
      el.btnStop.disabled = false;
    } else if (status === 'COMPLETED') {
      state.isCollecting = false;
      el.liveIndicator.className = 'live-status-pill status-idle';
      el.liveStatusText.textContent = 'COMPLETED';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Comment collection completed!', 'success');
    } else if (status === 'CANCELLED') {
      state.isCollecting = false;
      el.liveIndicator.className = 'live-status-pill status-idle';
      el.liveStatusText.textContent = 'STOPPED';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Collection stopped.', 'info');
    } else if (status === 'ERROR') {
      state.isCollecting = false;
      el.liveIndicator.className = 'live-status-pill status-idle';
      el.liveStatusText.textContent = 'ERROR';
      el.btnStart.disabled = false;
      el.btnStop.disabled = true;
      showToast(message || 'Error occurred during collection.', 'error');
    } else {
      state.isCollecting = false;
      el.liveIndicator.className = 'live-status-pill status-idle';
      el.liveStatusText.textContent = 'SYSTEM READY';
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
    }

    try {
      updateStatusUI('CONNECTING', 'Initiating real comment extraction from post...');
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

      const res = await resp.json();
      if (!res.success) {
        showToast(res.error || 'Failed to start collection.', 'error');
        updateStatusUI('ERROR', res.error);
      } else {
        showToast(`Targeting post: ${url.slice(0, 45)}...`, 'info');
      }
    } catch (err) {
      showToast('Could not connect to server: ' + err.message, 'error');
      updateStatusUI('ERROR', err.message);
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
      showToast('Error stopping collection: ' + err.message, 'error');
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
      showToast('Error clearing: ' + err.message, 'error');
    }
  }

  function handleExport(format) {
    if (!state.comments.length) {
      showToast('No comments to export.', 'error');
      return;
    }
    const sort = state.sortOrder === 'oldest' ? 'oldest' : 'newest';
    const endpoint = format === 'excel' ? `/api/export/excel?sort=${sort}` : `/api/export/csv?sort=${sort}`;
    
    const link = document.createElement('a');
    link.href = endpoint;
    link.setAttribute('download', '');
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);

    showToast(`Generating and downloading ${format.toUpperCase()} spreadsheet...`, 'success');
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
    el.clearUrlBtn.addEventListener('click', () => {
      el.postUrl.value = '';
      el.postUrl.focus();
    });

    // Re-login button
    el.btnRelogin.addEventListener('click', async () => {
      showToast('Opening browser window to log in to Facebook...', 'info');
      try {
        await fetch('/api/auth/login', { method: 'POST' });
      } catch (e) {}
    });

    // Sound Chime Toggle
    el.soundToggle.addEventListener('click', () => {
      state.soundEnabled = !state.soundEnabled;
      el.soundIcon.innerHTML = state.soundEnabled ? '&#128266;' : '&#128263;';
      showToast(state.soundEnabled ? 'Chime sound enabled' : 'Chime sound muted', 'info');
      try {
        localStorage.setItem('comment_absorber_sound', state.soundEnabled ? '1' : '0');
      } catch (e) {}
    });

    // Auto-scroll Checkbox
    el.autoscrollToggle.addEventListener('change', (e) => {
      state.autoScroll = e.target.checked;
      if (state.autoScroll) {
        scrollToTarget();
      }
    });

    el.streamContainer.addEventListener('scroll', () => {
      if (state.sortOrder === 'newest') {
        if (el.streamContainer.scrollTop > 50 && state.autoScroll) {
          state.autoScroll = false;
          el.autoscrollToggle.checked = false;
        }
      } else {
        const isNearBottom = (el.streamContainer.scrollHeight - el.streamContainer.scrollTop - el.streamContainer.clientHeight) < 50;
        if (!isNearBottom && state.autoScroll) {
          state.autoScroll = false;
          el.autoscrollToggle.checked = false;
        }
      }
    });

    // Sort Toggle Button
    el.sortToggleBtn.addEventListener('click', () => {
      if (state.sortOrder === 'newest') {
        state.sortOrder = 'oldest';
        el.sortLabel.innerHTML = '&#8593; Oldest First';
      } else {
        state.sortOrder = 'newest';
        el.sortLabel.innerHTML = '&#8595; Newest First';
      }
      renderCommentsList();
      showToast(`Sorted by ${state.sortOrder === 'newest' ? 'Newest First' : 'Oldest First'}`, 'info');
    });

    // Live Search Filter
    el.feedSearch.addEventListener('input', (e) => {
      state.searchQuery = e.target.value;
      renderCommentsList();
    });

    // Main Buttons
    el.btnStart.addEventListener('click', handleStart);
    el.btnStop.addEventListener('click', handleStop);
    el.btnClear.addEventListener('click', handleClear);
    el.btnExportExcel.addEventListener('click', () => handleExport('excel'));
    el.btnExportCsv.addEventListener('click', () => handleExport('csv'));

    el.postUrl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') {
        handleStart();
      }
    });
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
