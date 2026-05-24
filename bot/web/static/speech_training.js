(function () {
    'use strict';

    // ── State ────────────────────────────────────────────────────────
    const state = {
        selectedUserId: null,
        labelFilter: 'unlabeled',
        page: 1,
        perPage: 20,
        search: '',
        sort: 'newest',
        totalPages: 1,
        users: [],
        selectedIds: new Set(),
        currentlyPlaying: null, // audio element reference
        _clipReqToken: 0,
        _userReqToken: 0,
        _passiveRefreshPending: null,
        _passiveIntervalMs: 5000,
        _scanMode: false, // true when displaying keyword scan results
        _scanClips: [],   // cached scan match clips
        _scanKeyword: '', // the keyword that was scanned for
        _scanJobId: null, // pending scan job id for polling
        _scanPollTimer: null, // setTimeout handle for polling
        _transcriptJobId: null, // pending transcript job id for polling
        _transcriptPollTimer: null, // setTimeout handle for polling
        _transcriptProcessing: false, // true while transcript job is running
        _scanConfidence: 0.5, // fixed min confidence (always 50%)
        labelOptions: ['chapada', 'ventura', 'none'],
    };

    // ── Passive refresh guards / toast timer (module-level) ──────────
    let _passiveRefreshInProgress = false;
    let _passiveRefreshScheduled = false;
    let _scanToastTimer = null;

    // ── DOM refs ─────────────────────────────────────────────────────
    const $ = (id) => document.getElementById(id);
    const userList = $('userList');
    const userCount = $('userCount');
    const clipList = $('clipList');
    const datasetTitle = $('datasetTitle');
    const datasetPagination = $('datasetPagination');
    const datasetSearch = $('datasetSearch');
    const storageUsed = $('storageUsed');
    const guildSelector = document.getElementById('guildSelector');
    const labelFilterSelect = $('labelFilterSelect');
    const datasetSort = $('datasetSort');
    const bulkCount = $('bulkCount');
    const bulkSelectAll = $('bulkSelectAll');
    const bulkClear = $('bulkClear');
    const bulkLabelSelect = $('bulkLabelSelect');
    const bulkApplyLabel = $('bulkApplyLabel');
    const bulkDelete = $('bulkDelete');
    const scanKeywordBtn = $('scanKeywordBtn');
    const scanStatus = $('scanStatus');
    const scanProgress = $('scanProgress');
    const transcribeBtn = $('transcribeBtn');

    // ── Theme toggle ───────────────────────────────────────────────────
    const themeToggle = document.querySelector('.theme-toggle');

    function applyThemePreference(theme) {
        const isDark = theme === 'dark';
        document.documentElement.classList.toggle('theme-dark', isDark);
        if (!themeToggle) {
            return;
        }
        themeToggle.textContent = isDark ? '☀️' : '🌙';
        themeToggle.setAttribute('aria-pressed', String(isDark));
        themeToggle.setAttribute('aria-label', isDark ? 'Disable dark mode' : 'Enable dark mode');
    }

    if (themeToggle) {
        let storedTheme = null;
        try {
            storedTheme = localStorage.getItem('brainrot-theme');
        } catch (error) {
            storedTheme = null;
        }
        applyThemePreference(storedTheme);
        themeToggle.addEventListener('click', () => {
            const nextTheme = document.documentElement.classList.contains('theme-dark') ? 'light' : 'dark';
            try {
                localStorage.setItem('brainrot-theme', nextTheme);
            } catch (error) {
                // Keep the in-page toggle usable even if storage is blocked.
            }
            applyThemePreference(nextTheme);
        });
    }

    // ── Guild selector sync ──────────────────────────────────────────
    function getSelectedGuildId() {
        return guildSelector ? guildSelector.value : '';
    }

    // ── URL helpers ──────────────────────────────────────────────────
    function apiBase() {
        const params = new URLSearchParams();
        if (state.selectedUserId) params.set('user_id', state.selectedUserId);
        if (state.labelFilter) params.set('label', state.labelFilter);
        params.set('page', String(state.page));
        params.set('per_page', String(state.perPage));
        if (state.search) params.set('search', state.search);
        if (state.sort) params.set('sort', state.sort);
        const gid = getSelectedGuildId();
        if (gid) params.set('guild_id', gid);
        return params;
    }

    // ── Load users ───────────────────────────────────────────────────
    async function loadUsers(opts) {
        opts = opts || {};
        state._userReqToken++;
        const token = state._userReqToken;
        const params = new URLSearchParams();
        const gid = getSelectedGuildId();
        if (gid) params.set('guild_id', gid);
        const resp = await fetch('/api/speech_training/users?' + params.toString());
        if (!resp.ok) return;
        if (token !== state._userReqToken) return; // stale response
        state.users = await resp.json();
        if (token !== state._userReqToken) return; // stale response
        renderUsers();
    }

    function renderUsers() {
        if (!userList) return;
        userList.innerHTML = '';
        userCount.textContent = String(state.users.length);

        // "All users" option
        const allEl = document.createElement('button');
        allEl.type = 'button';
        allEl.className = 'dataset-user-item' + (state.selectedUserId === null ? ' active' : '');
        allEl.setAttribute('role', 'option');
        allEl.setAttribute('aria-selected', String(state.selectedUserId === null));

        const allNameSpan = document.createElement('span');
        allNameSpan.className = 'dataset-user-name';
        allNameSpan.textContent = 'All users';

        const allMetaSpan = document.createElement('span');
        allMetaSpan.className = 'dataset-user-meta';
        var allTotal = 0;
        var allUnlabeled = 0;
        for (var ui = 0; ui < state.users.length; ui++) {
            allTotal += state.users[ui].total_count || 0;
            allUnlabeled += state.users[ui].unlabeled_count || 0;
        }
        allMetaSpan.textContent = allTotal + ' clips' + (allUnlabeled > 0 ? ' (' + allUnlabeled + ' unlabeled)' : '');

        allEl.appendChild(allNameSpan);
        allEl.appendChild(allMetaSpan);

        allEl.addEventListener('click', function () {
            state.selectedUserId = null;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            updateTitleFromFilter();
            loadClips();
            renderUsers();
        });

        userList.appendChild(allEl);

        for (const u of state.users) {
            const el = document.createElement('button');
            el.type = 'button';
            el.className = 'dataset-user-item' + (u.user_id === state.selectedUserId ? ' active' : '');
            el.setAttribute('role', 'option');
            el.setAttribute('aria-selected', String(u.user_id === state.selectedUserId));

            const nameSpan = document.createElement('span');
            nameSpan.className = 'dataset-user-name';
            nameSpan.textContent = u.display_name || u.username || u.user_id;

            const metaSpan = document.createElement('span');
            metaSpan.className = 'dataset-user-meta';
            const unlabeled = u.unlabeled_count || 0;
            metaSpan.textContent = u.total_count + ' clips' + (unlabeled > 0 ? ' (' + unlabeled + ' unlabeled)' : '');

            el.appendChild(nameSpan);
            el.appendChild(metaSpan);

            el.addEventListener('click', function () {
                if (state.selectedUserId === u.user_id) {
                    state.selectedUserId = null;
                } else {
                    state.selectedUserId = u.user_id;
                }
                state.page = 1;
                state.selectedIds.clear();
                updateBulkUI();
                updateTitleFromFilter();
                loadClips();
                renderUsers();
            });

            userList.appendChild(el);
        }
    }

    // ── Load storage summary ────────────────────────────────────────
    async function loadStorage() {
        if (!storageUsed) return;
        const params = new URLSearchParams();
        const gid = getSelectedGuildId();
        if (gid) params.set('guild_id', gid);
        try {
            const resp = await fetch('/api/speech_training/storage?' + params.toString());
            if (!resp.ok) {
                storageUsed.textContent = 'MP3 storage: —';
                return;
            }
            const data = await resp.json();
            storageUsed.textContent = 'MP3 storage: ' + (data.total_size || '—');
        } catch (e) {
            storageUsed.textContent = 'MP3 storage: —';
        }
    }

    // ── Label options helpers ─────────────────────────────────────────
    function escapeHtmlForAttr(str) {
        if (!str) return '';
        return str.replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/'/g, '&#39;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    function addLabelOption(label) {
        label = label.trim();
        if (!label) return;
        if (state.labelOptions.indexOf(label) === -1) {
            state.labelOptions.push(label);
            refreshAllLabelSelects();
            rebuildFilterDropdown();
        }
    }

    function buildLabelOptionsHtml(selectedLabel, includeEmpty, includeCustom) {
        let html = '';
        if (includeEmpty) {
            const sel = selectedLabel === '' || selectedLabel === null || selectedLabel === undefined ? ' selected' : '';
            html += '<option value=""' + sel + '>None</option>';
        }
        for (const opt of state.labelOptions) {
            const sel = opt === selectedLabel ? ' selected' : '';
            html += '<option value="' + escapeHtmlForAttr(opt) + '"' + sel + '>' + escapeHtml(opt) + '</option>';
        }
        if (includeCustom) {
            const isCustom = selectedLabel && state.labelOptions.indexOf(selectedLabel) === -1;
            html += '<option value="__custom__"' + (isCustom ? ' selected' : '') + '>Custom\u2026</option>';
        }
        return html;
    }

    function updateTitleFromFilter() {
        var prefix = state.selectedUserId
            ? (getUserDisplayName(state.selectedUserId) || 'Selected') + '\u2019s '
            : 'All users\u2019 ';
        if (state.labelFilter === 'unlabeled') {
            datasetTitle.textContent = prefix + 'unlabeled clips';
        } else if (state.labelFilter === 'none') {
            datasetTitle.textContent = prefix + '\u201cnone\u201d clips';
        } else if (state.labelFilter) {
            datasetTitle.textContent = prefix + '\u201c' + state.labelFilter + '\u201d clips';
        } else {
            datasetTitle.textContent = state.selectedUserId ? prefix + 'clips' : 'All clips';
        }
    }

    function rebuildFilterDropdown() {
        if (!labelFilterSelect) return;
        var currentValue = labelFilterSelect.value || state.labelFilter || '';
        var html = '<option value="">All</option>';
        html += '<option value="unlabeled"' + (currentValue === 'unlabeled' ? ' selected' : '') + '>Unlabeled</option>';
        html += '<option value="none"' + (currentValue === 'none' ? ' selected' : '') + '>None</option>';
        // Add dynamic labels from state.labelOptions, excluding 'unclear', 'none'
        for (var i = 0; i < state.labelOptions.length; i++) {
            var opt = state.labelOptions[i];
            if (opt === 'none' || opt === 'unclear') continue;
            var sel = opt === currentValue ? ' selected' : '';
            html += '<option value="' + escapeHtmlForAttr(opt) + '"' + sel + '>' + escapeHtml(opt) + '</option>';
        }
        labelFilterSelect.innerHTML = html;
    }

    function refreshAllLabelSelects() {
        // Quick label selects
        document.querySelectorAll('.dataset-quick-label-select').forEach(function (sel) {
            const clipEl = sel.closest('.dataset-clip');
            const currentLabel = clipEl ? (clipEl.querySelector('.dataset-clip-label-chip')?.dataset.label || '') : '';
            const currentValue = sel.value;
            sel.innerHTML = buildLabelOptionsHtml(currentLabel || currentValue, true, true);
        });
        // Expanded detail selects
        document.querySelectorAll('.dataset-clip-label-select').forEach(function (sel) {
            const currentValue = sel.value;
            const isCustom = currentValue === '__custom__' || (currentValue && state.labelOptions.indexOf(currentValue) === -1);
            sel.innerHTML = buildLabelOptionsHtml(isCustom ? '__custom__' : currentValue, true, true);
        });
        // Bulk label select
        updateBulkLabelSelect();
    }

    function updateBulkLabelSelect() {
        if (!bulkLabelSelect) return;
        const currentValue = bulkLabelSelect.value;
        bulkLabelSelect.innerHTML = '<option value="">Label\u2026</option>';
        bulkLabelSelect.innerHTML += buildLabelOptionsHtml('', false, true);
    }

    function updateLabelChip(clipEl, label) {
        const existingChip = clipEl.querySelector('.dataset-clip-label-chip');
        if (label) {
            if (existingChip) {
                existingChip.textContent = label;
                existingChip.dataset.label = label;
            } else {
                const meta = clipEl.querySelector('.dataset-clip-meta');
                if (meta) {
                    const chip = document.createElement('span');
                    chip.className = 'dataset-clip-label-chip';
                    chip.dataset.label = label;
                    chip.textContent = label;
                    meta.parentNode.insertBefore(chip, meta.nextSibling);
                }
            }
        } else {
            if (existingChip) existingChip.remove();
        }
    }

    async function loadLabels() {
        const params = new URLSearchParams();
        const gid = getSelectedGuildId();
        if (gid) params.set('guild_id', gid);
        try {
            const resp = await fetch('/api/speech_training/labels?' + params.toString());
            if (!resp.ok) return;
            const data = await resp.json();
            if (data.labels && Array.isArray(data.labels) && data.labels.length > 0) {
                state.labelOptions = data.labels;
                refreshAllLabelSelects();
                rebuildFilterDropdown();
            }
        } catch (e) {
            // keep defaults
            rebuildFilterDropdown();
        }
    }

    // ── Load clips ───────────────────────────────────────────────────
    async function loadClips(opts) {
        opts = opts || {};
        state._clipReqToken++;
        const token = state._clipReqToken;
        const resp = await fetch('/api/speech_training/clips?' + apiBase().toString());
        if (!resp.ok) {
            if (!opts.passive) clipList.innerHTML = '<p class="dataset-empty">Failed to load clips.</p>';
            return;
        }
        if (token !== state._clipReqToken) return; // stale response
        const data = await resp.json();
        if (token !== state._clipReqToken) return; // stale response
        state.totalPages = data.total_pages || 1;
        renderClips(data.items || []);
        renderPagination();
    }

    function escapeHtml(str) {
        if (!str) return '';
        var div = document.createElement('div');
        div.appendChild(document.createTextNode(str));
        return div.innerHTML;
    }

    // ── Relative timestamp formatting ────────────────────────────────
    function formatRelativeTime(ts) {
        if (!ts) return '';
        // Normalise SQLite "YYYY-MM-DD HH:MM:SS" to ISO "YYYY-MM-DDTHH:MM:SS"
        var normalized = ts.replace(' ', 'T');
        // Append Z (UTC) if no timezone indicator is already present
        if (!/Z$/i.test(normalized) && !/[+-]\d{2}:\d{2}$/.test(normalized)) {
            normalized += 'Z';
        }
        var date = new Date(normalized);
        if (isNaN(date.getTime())) return ts; // fallback to original string

        var diffMs = Date.now() - date.getTime();
        var diffSec = Math.floor(diffMs / 1000);

        if (diffSec < 0) return ts; // future timestamp, don't guess
        if (diffSec < 5) return 'just now';
        if (diffSec < 60) return diffSec + ' seconds ago';

        var diffMin = Math.floor(diffSec / 60);
        if (diffMin < 60) {
            return diffMin === 1 ? '1 minute ago' : diffMin + ' minutes ago';
        }

        // Older than 60 minutes: show original timestamp
        return ts;
    }

    // ── Progress helpers ──────────────────────────────────────────────
    function formatTime(seconds) {
        if (!Number.isFinite(seconds) || seconds < 0) return '0:00';
        var m = Math.floor(seconds / 60);
        var s = Math.floor(seconds % 60);
        return m + ':' + (s < 10 ? '0' : '') + s;
    }

    function getQuickProgress(clipEl) {
        return clipEl ? clipEl.querySelector('.dataset-quick-progress') : null;
    }

    function updateQuickProgress(audio) {
        var clipEl = audio ? audio.closest('.dataset-clip') : null;
        var progress = getQuickProgress(clipEl);
        if (!progress) return;

        var track = progress.querySelector('.dataset-quick-progress-track');
        var fill = progress.querySelector('.dataset-quick-progress-fill');
        var timeLabel = progress.querySelector('.dataset-quick-progress-time');
        if (!track || !fill || !timeLabel) return;

        var ct = audio.currentTime;
        var dur = audio.duration;

        if (Number.isFinite(dur) && dur > 0) {
            var pct = Math.min((ct / dur) * 100, 100);
            fill.style.width = pct + '%';
            track.setAttribute('aria-valuenow', String(Math.round(pct)));
            track.setAttribute('aria-valuetext', formatTime(ct) + ' / ' + formatTime(dur));
            timeLabel.textContent = formatTime(ct) + ' / ' + formatTime(dur);
        } else {
            fill.style.width = '0%';
            timeLabel.textContent = formatTime(ct) + ' / --:--';
        }
    }

    function showQuickProgress(audio) {
        var clipEl = audio ? audio.closest('.dataset-clip') : null;
        var progress = getQuickProgress(clipEl);
        if (!progress) return;
        progress.hidden = false;
        updateQuickProgress(audio);
    }

    function resetQuickProgress(audio) {
        var clipEl = audio ? audio.closest('.dataset-clip') : null;
        var progress = getQuickProgress(clipEl);
        if (!progress) return;

        var track = progress.querySelector('.dataset-quick-progress-track');
        var fill = progress.querySelector('.dataset-quick-progress-fill');
        var timeLabel = progress.querySelector('.dataset-quick-progress-time');
        if (track) {
            track.setAttribute('aria-valuenow', '0');
            track.setAttribute('aria-valuetext', '');
        }
        if (fill) fill.style.width = '0%';
        if (timeLabel) timeLabel.textContent = '0:00 / 0:00';
        progress.hidden = true;
    }

    function wireQuickProgress(audio) {
        if (!audio || audio.dataset.progressWired) return;
        audio.dataset.progressWired = '1';

        audio.addEventListener('play', function () {
            showQuickProgress(audio);
            // Update quick play button to pause
            var clipEl = audio.closest('.dataset-clip');
            if (clipEl) {
                var btn = clipEl.querySelector('.dataset-quick-play');
                if (btn) {
                    btn.innerHTML = '&#9646;&#9646;';
                    btn.setAttribute('aria-label', 'Pause clip');
                }
            }
            state.currentlyPlaying = audio;
        });

        audio.addEventListener('timeupdate', function () {
            updateQuickProgress(audio);
        });

        audio.addEventListener('loadedmetadata', function () {
            updateQuickProgress(audio);
        });

        audio.addEventListener('pause', function () {
            // Keep progress visible so user sees where they paused
            // Update quick play button to play
            var clipEl = audio.closest('.dataset-clip');
            if (clipEl) {
                var btn = clipEl.querySelector('.dataset-quick-play');
                if (btn) {
                    btn.innerHTML = '&#9654;';
                    btn.setAttribute('aria-label', 'Play clip');
                }
            }
        });

        audio.addEventListener('ended', function () {
            resetQuickProgress(audio);
            var clipEl = audio.closest('.dataset-clip');
            if (clipEl) {
                var btn = clipEl.querySelector('.dataset-quick-play');
                if (btn) {
                    btn.innerHTML = '&#9654;';
                    btn.setAttribute('aria-label', 'Play clip');
                }
            }
            if (state.currentlyPlaying === audio) {
                state.currentlyPlaying = null;
            }
        });

        audio.addEventListener('error', function () {
            resetQuickProgress(audio);
            var clipEl = audio.closest('.dataset-clip');
            if (clipEl) {
                var btn = clipEl.querySelector('.dataset-quick-play');
                if (btn) {
                    btn.innerHTML = '&#9654;';
                    btn.setAttribute('aria-label', 'Play clip');
                }
            }
            if (state.currentlyPlaying === audio) {
                state.currentlyPlaying = null;
            }
        });
    }

    // ── Quick seek / scrub ──────────────────────────────────────────
    function wireQuickSeek(track) {
        if (!track || track.dataset.seekWired) return;
        track.dataset.seekWired = '1';

        var isDragging = false;

        function getAudio() {
            var clipEl = track.closest('.dataset-clip');
            return clipEl ? clipEl.querySelector('.dataset-clip-player') : null;
        }

        function seekFromPointer(clientX) {
            if (clientX == null) return;
            var audio = getAudio();
            if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;

            var rect = track.getBoundingClientRect();
            var ratio = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
            var seekTime = ratio * audio.duration;
            audio.currentTime = seekTime;
            updateQuickProgress(audio);
        }

        track.addEventListener('pointerdown', function (e) {
            e.preventDefault();
            isDragging = true;
            track.setPointerCapture(e.pointerId);
            track.classList.add('dragging');
            seekFromPointer(e.clientX);
            showQuickProgress(getAudio());
        });

        track.addEventListener('pointermove', function (e) {
            if (!isDragging) return;
            e.preventDefault();
            seekFromPointer(e.clientX);
        });

        track.addEventListener('pointerup', function (e) {
            if (!isDragging) return;
            isDragging = false;
            track.classList.remove('dragging');
            try { track.releasePointerCapture(e.pointerId); } catch (_) {}
        });

        track.addEventListener('pointercancel', function () {
            isDragging = false;
            track.classList.remove('dragging');
        });

        track.addEventListener('keydown', function (e) {
            var audio = getAudio();
            if (!audio || !Number.isFinite(audio.duration) || audio.duration <= 0) return;

            var step = e.shiftKey ? 5 : 1;
            var newTime = audio.currentTime;

            switch (e.key) {
                case 'ArrowLeft':
                    e.preventDefault();
                    newTime = Math.max(0, newTime - step);
                    break;
                case 'ArrowRight':
                    e.preventDefault();
                    newTime = Math.min(audio.duration, newTime + step);
                    break;
                case 'Home':
                    e.preventDefault();
                    newTime = 0;
                    break;
                case 'End':
                    e.preventDefault();
                    newTime = audio.duration;
                    break;
                default:
                    return;
            }
            audio.currentTime = newTime;
            updateQuickProgress(audio);
        });
    }

    function renderClips(items) {
        if (!clipList) return;
        if (items.length === 0) {
            clipList.innerHTML = '<p class="dataset-empty">No clips found.</p>';
            return;
        }

        // Ensure custom labels from clips are available in select options
        for (const clip of items) {
            if (clip.label && state.labelOptions.indexOf(clip.label) === -1) {
                state.labelOptions.push(clip.label);
            }
        }

        let html = '';
        for (const clip of items) {
            const label = clip.label || '';
            const transcript = clip.transcript || '';
            const notes = clip.notes || '';
            const dur = clip.duration_seconds ? clip.duration_seconds.toFixed(1) + 's' : '';
            const ts = clip.captured_at || '';
            const tsDisplay = formatRelativeTime(ts);
            const tsTitle = ts ? ' title="' + escapeHtml(ts) + '"' : '';
            // Build meta text from non-empty parts to avoid orphan middot
            var metaParts = [];
            if (dur) metaParts.push(escapeHtml(dur));
            if (tsDisplay) metaParts.push(escapeHtml(tsDisplay));
            var metaText = metaParts.join(' &middot; ');
            const displayName = clip.display_name || clip.username || clip.user_id;
            const isSelected = state.selectedIds.has(clip.id);

            html += '<div class="dataset-clip' + (isSelected ? ' selected' : '') + '" data-id="' + clip.id + '">';

            // Quick action row
            html += '<div class="dataset-clip-quick">';
            html += '<label class="dataset-clip-checkbox-label">';
            html += '<input type="checkbox" class="dataset-clip-checkbox" data-id="' + clip.id + '"' + (isSelected ? ' checked' : '') + ' aria-label="Select clip">';
            html += '</label>';
            html += '<span class="dataset-clip-user">' + escapeHtml(displayName) + '</span>';
            html += '<span class="dataset-clip-meta"' + tsTitle + '>' + metaText + '</span>';
            if (label) {
                html += '<span class="dataset-clip-label-chip" data-label="' + escapeHtml(label) + '">' + escapeHtml(label) + '</span>';
            }
            if (clip.keyword_confidence !== undefined && clip.keyword_confidence !== null) {
                var pct = Math.round(clip.keyword_confidence * 100);
                html += '<span class="dataset-clip-conf-chip" title="Chapada certainty: ' + pct + '% (Vosk confidence ' + clip.keyword_confidence + ')">' + pct + '% certainty</span>';
            }

            // Quick progress indicator + scrubber (hidden by default)
            html += '<div class="dataset-quick-progress" hidden>';
            html += '<span class="dataset-quick-progress-track" role="slider" tabindex="0" aria-label="Clip position" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" aria-valuetext="0:00 / 0:00"><span class="dataset-quick-progress-fill"></span></span>';
            html += '<span class="dataset-quick-progress-time">0:00 / 0:00</span>';
            html += '</div>';

            // Quick action buttons
            html += '<div class="dataset-clip-actions">';
            html += '<button type="button" class="dataset-quick-play" data-id="' + clip.id + '" title="Play clip" aria-label="Play clip">&#9654;</button>';
            html += '<select class="dataset-quick-label-select" data-id="' + clip.id + '" aria-label="Quick label">' + buildLabelOptionsHtml(label, true, true) + '</select>';
            html += '<button type="button" class="dataset-quick-label-apply" data-id="' + clip.id + '" title="Apply label" aria-label="Apply label">Label</button>';
            html += '<button type="button" class="dataset-quick-delete" data-id="' + clip.id + '" title="Delete clip" aria-label="Delete clip">Delete</button>';
            html += '<button type="button" class="dataset-quick-more" data-id="' + clip.id + '" aria-expanded="false" title="More options" aria-label="More options">&#9660;</button>';
            html += '</div>';
            html += '</div>'; // .dataset-clip-quick

            // Expanded details (hidden by default)
            html += '<div class="dataset-clip-details" hidden>';
            html += '<audio class="dataset-clip-player" controls preload="none">';
            html += '<source src="/api/speech_training/clips/' + clip.id + '/audio" type="audio/mpeg">';
            html += '</audio>';
            html += '<div class="dataset-clip-fields">';

            // Label select with custom option
            html += '<div class="dataset-field">';
            html += '<label class="dataset-field-label">Label</label>';
            html += '<select class="dataset-clip-label-select" data-field="label">';
            html += buildLabelOptionsHtml(label, true, true);
            html += '</select>';
            // Custom label input (hidden by default)
            html += '<input type="text" class="dataset-clip-custom-label" data-field="custom_label" maxlength="64" placeholder="Custom label" hidden>';
            html += '</div>';

            // Transcript
            html += '<div class="dataset-field">';
            html += '<label class="dataset-field-label">Transcript</label>';
            html += '<textarea class="dataset-clip-transcript" data-field="transcript" rows="2" maxlength="2000" placeholder="Optional transcript">' + escapeHtml(transcript) + '</textarea>';
            html += '</div>';

            // Notes
            html += '<div class="dataset-field">';
            html += '<label class="dataset-field-label">Notes</label>';
            html += '<textarea class="dataset-clip-notes" data-field="notes" rows="2" maxlength="2000" placeholder="Optional notes">' + escapeHtml(notes) + '</textarea>';
            html += '</div>';

            // Save button
            html += '<button type="button" class="dataset-save-btn">Save</button>';
            html += '<span class="dataset-save-status"></span>';
            html += '</div>'; // .dataset-clip-fields
            html += '</div>'; // .dataset-clip-details
            html += '</div>'; // .dataset-clip
        }
        clipList.innerHTML = html;

        // Bind events
        bindClipEvents(clipList);
    }

    function bindClipEvents(container) {
        // Wire progress events for all audio players (works for both quick play and native controls)
        container.querySelectorAll('.dataset-clip-player').forEach(function (audio) {
            wireQuickProgress(audio);
        });

        // Wire seek/scrub for all progress tracks
        container.querySelectorAll('.dataset-quick-progress-track').forEach(function (track) {
            wireQuickSeek(track);
        });

        // Checkbox toggle
        container.querySelectorAll('.dataset-clip-checkbox').forEach(function (cb) {
            cb.addEventListener('change', function () {
                const id = parseInt(cb.dataset.id, 10);
                if (cb.checked) {
                    state.selectedIds.add(id);
                } else {
                    state.selectedIds.delete(id);
                }
                // Toggle selected class on parent clip
                const clipEl = cb.closest('.dataset-clip');
                if (clipEl) {
                    clipEl.classList.toggle('selected', cb.checked);
                }
                updateBulkUI();
            });
        });

        // Quick play
        container.querySelectorAll('.dataset-quick-play').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const clipEl = btn.closest('.dataset-clip');
                const details = clipEl ? clipEl.querySelector('.dataset-clip-details') : null;
                const audio = details ? details.querySelector('.dataset-clip-player') : null;
                if (!audio) return;

                // Pause any other playing clip and reset its progress
                if (state.currentlyPlaying && state.currentlyPlaying !== audio) {
                    state.currentlyPlaying.pause();
                    resetQuickProgress(state.currentlyPlaying);
                }

                if (audio.paused) {
                    audio.play().catch(function () {});
                } else {
                    audio.pause();
                }
            });
        });

        // Quick label apply button
        container.querySelectorAll('.dataset-quick-label-apply').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const clipEl = btn.closest('.dataset-clip');
                const select = clipEl ? clipEl.querySelector('.dataset-quick-label-select') : null;
                if (!select) return;
                const id = parseInt(btn.dataset.id, 10);
                let label = select.value;
                if (label === '__custom__') {
                    const custom = prompt('Enter custom label:');
                    if (custom === null) return; // cancelled
                    label = custom.trim();
                    if (!label) return;
                }
                quickLabelClip(id, label, btn, select, clipEl);
            });
        });

        // Quick delete
        container.querySelectorAll('.dataset-quick-delete').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const id = parseInt(btn.dataset.id, 10);
                if (confirm('Delete this clip?')) {
                    deleteClip(id, btn);
                }
            });
        });

        // More (expand details)
        container.querySelectorAll('.dataset-quick-more').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const clipEl = btn.closest('.dataset-clip');
                const details = clipEl ? clipEl.querySelector('.dataset-clip-details') : null;
                if (!details) return;
                const expanded = details.hidden;
                details.hidden = !expanded;
                btn.setAttribute('aria-expanded', String(expanded));
                btn.innerHTML = expanded ? '&#9650;' : '&#9660;';
            });
        });

        // Custom label select -> show custom input
        container.querySelectorAll('.dataset-clip-label-select').forEach(function (sel) {
            sel.addEventListener('change', function () {
                const clipEl = sel.closest('.dataset-clip');
                const customInput = clipEl ? clipEl.querySelector('.dataset-clip-custom-label') : null;
                if (customInput) {
                    customInput.hidden = sel.value !== '__custom__';
                    if (sel.value !== '__custom__') {
                        customInput.value = '';
                    } else {
                        customInput.focus();
                    }
                }
            });
        });

        // Save button
        container.querySelectorAll('.dataset-save-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const clipEl = btn.closest('.dataset-clip');
                saveClip(clipEl);
            });
        });

        // Auto-save label select on Enter (not auto on change to avoid spurious saves)
    }

    // ── Quick label ──────────────────────────────────────────────────
    async function quickLabelClip(id, label, btn, select, clipEl) {
        const originalText = btn.textContent;
        btn.textContent = '\u2026';
        btn.disabled = true;

        try {
            const resp = await fetch('/api/speech_training/clips/' + id + '/label', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ label: label, transcript: '', notes: '' }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                btn.textContent = 'Saved';
                btn.classList.add('saved');

                // If label is custom and not yet in options, add it
                if (label && state.labelOptions.indexOf(label) === -1) {
                    addLabelOption(label);
                }
                // Update the select to show the selected label
                if (select) {
                    select.innerHTML = buildLabelOptionsHtml(label, true, true);
                }
                // Also sync the expanded detail select if visible
                if (clipEl) {
                    const detailSelect = clipEl.querySelector('.dataset-clip-label-select');
                    if (detailSelect) {
                        detailSelect.innerHTML = buildLabelOptionsHtml(label, true, true);
                    }
                    const customInput = clipEl.querySelector('.dataset-clip-custom-label');
                    if (customInput) {
                        customInput.value = '';
                        customInput.hidden = true;
                    }
                }

                setTimeout(function () {
                    btn.textContent = originalText;
                    btn.disabled = false;
                    btn.classList.remove('saved');
                }, 1200);
                // Remove clip if filter is active and doesn't match
                if (state.labelFilter && state.labelFilter !== label && state.labelFilter !== '') {
                    if (clipEl) clipEl.remove();
                    checkEmptyList();
                } else if (clipEl) {
                    updateLabelChip(clipEl, label);
                }
                loadUsers();
            } else {
                btn.textContent = 'Error';
                setTimeout(function () {
                    btn.textContent = originalText;
                    btn.disabled = false;
                }, 1500);
            }
        } catch (e) {
            btn.textContent = 'Error';
            setTimeout(function () {
                btn.textContent = originalText;
                btn.disabled = false;
            }, 1500);
        }
    }

    // ── Delete clip ──────────────────────────────────────────────────
    async function deleteClip(id, btn) {
        btn.textContent = '…';
        btn.disabled = true;

        try {
            const resp = await fetch('/api/speech_training/clips/' + id, {
                method: 'DELETE',
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                const clipEl = btn.closest('.dataset-clip');
                if (clipEl) clipEl.remove();
                checkEmptyList();
                loadUsers();
                loadStorage();
            } else {
                btn.textContent = 'Error';
                setTimeout(function () {
                    btn.textContent = 'Delete';
                    btn.disabled = false;
                }, 1500);
            }
        } catch (e) {
            btn.textContent = 'Error';
            setTimeout(function () {
                btn.textContent = 'Delete';
                btn.disabled = false;
            }, 1500);
        }
    }

    function checkEmptyList() {
        if (clipList && clipList.querySelectorAll('.dataset-clip').length === 0) {
            loadClips();
        }
    }

    // ── Scan toast helper ────────────────────────────────────────────
    function showScanToast(message, kind) {
        kind = kind || 'info';

        var region = document.getElementById('speechToastRegion');
        if (!region) {
            region = document.createElement('div');
            region.id = 'speechToastRegion';
            region.className = 'speech-toast-region';
            region.setAttribute('role', 'status');
            region.setAttribute('aria-live', 'polite');
            region.setAttribute('aria-atomic', 'true');
            document.body.appendChild(region);
        }

        // Remove any existing toast in the region
        var existing = region.querySelector('.speech-toast');
        if (existing) {
            existing.remove();
            if (_scanToastTimer) {
                clearTimeout(_scanToastTimer);
                _scanToastTimer = null;
            }
        }

        var toast = document.createElement('div');
        toast.className = 'speech-toast ' + kind;
        toast.textContent = message;
        region.appendChild(toast);

        // Auto-dismiss after 6 seconds with fade-out
        _scanToastTimer = setTimeout(function () {
            if (toast.parentNode) {
                toast.classList.add('speech-toast-hiding');
                setTimeout(function () {
                    if (toast.parentNode) toast.remove();
                }, 180);
            }
            _scanToastTimer = null;
        }, 6000);
    }

    // ── Scan mode ────────────────────────────────────────────────────
    function enterScanMode(clips, keyword, maxDurationSeconds) {
        state._scanMode = true;
        state._scanClips = clips;
        state._scanKeyword = keyword;
        state.selectedIds.clear();
        updateBulkUI();
        var pct = Math.round((state._scanConfidence || 0.5) * 100);
        var durLabel = maxDurationSeconds ? ' \u2264' + maxDurationSeconds + 's' : '';
        datasetTitle.textContent = 'Scan results: "' + keyword + '" (\u2265' + pct + '%' + durLabel + ')';
        renderClips(clips);
        datasetPagination.innerHTML = '<div class="pagination-inner"><button type="button" class="pagination-btn" id="clearScanBtn">Show all clips</button></div>';
        var clearBtn = $('clearScanBtn');
        if (clearBtn) {
            clearBtn.addEventListener('click', function () {
                clearScanMode();
            });
        }
    }

    function clearScanMode(skipReload) {
        cancelScanPoll();
        state._scanMode = false;
        state._scanClips = [];
        state._scanKeyword = '';
        if (scanStatus) scanStatus.textContent = '';
        if (scanProgress) {
            scanProgress.hidden = true;
            scanProgress.value = 0;
        }
        updateTitleFromFilter();
        if (!skipReload) {
            loadClips();
            renderPagination();
        }
    }

    function getUserDisplayName(userId) {
        for (var i = 0; i < state.users.length; i++) {
            if (state.users[i].user_id === userId) {
                return state.users[i].display_name || state.users[i].username || userId;
            }
        }
        return null;
    }

    async function runKeywordScan() {
        // Cancel any previous poll
        cancelScanPoll();

        if (scanKeywordBtn) scanKeywordBtn.disabled = true;
        if (transcribeBtn) transcribeBtn.disabled = true;
        if (scanStatus) scanStatus.textContent = '';
        showScanToast('Starting scan (clips \u226430s)\u2026', 'info');
        if (scanProgress) {
            scanProgress.hidden = false;
            scanProgress.value = 0;
            scanProgress.max = 100;
        }

        state._scanConfidence = 0.5;

        var body = { keyword: 'chapada', min_confidence: 0.5, label_non_matches_as_none: true };
        var gid = getSelectedGuildId();
        if (gid) body.guild_id = gid;
        if (state.selectedUserId) body.user_id = state.selectedUserId;

        try {
            var resp = await fetch('/api/speech_training/keyword_scan', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var data = await safeParseJson(resp);
            if (data.job_id) {
                state._scanJobId = data.job_id;
                showScanToast('Queued\u2026', 'info');
                pollScanJob(data.job_id);
            } else {
                showScanToast(data.error || 'Failed to start scan', 'error');
                if (scanKeywordBtn) scanKeywordBtn.disabled = false;
                if (scanProgress) scanProgress.hidden = true;
            }
        } catch (e) {
            showScanToast('Network error while starting scan', 'error');
            if (scanKeywordBtn) scanKeywordBtn.disabled = false;
            if (scanProgress) scanProgress.hidden = true;
        }
    }

    async function safeParseJson(resp) {
        // Parse response as JSON safely, handling non-JSON error responses
        var text = await resp.text();
        try {
            return JSON.parse(text);
        } catch (e) {
            return { error: text || ('HTTP ' + resp.status) };
        }
    }

    function pollScanJob(jobId) {
        var pollInterval = 500; // ms

        async function poll() {
            if (state._scanJobId !== jobId) return; // stale poll

            try {
                var resp = await fetch('/api/speech_training/keyword_scan/' + jobId);
                var data = await safeParseJson(resp);
                if (data.status === 'queued' || data.status === 'processing') {
                    updateScanProgress(data);
                    state._scanPollTimer = setTimeout(poll, pollInterval);
                } else if (data.status === 'done') {
                    onScanDone(data);
                } else if (data.status === 'error') {
                    onScanError(data.error || 'Scan failed');
                } else {
                    // Unknown status - treat as error
                    onScanError(data.error || 'Unexpected scan status: ' + data.status);
                }
            } catch (e) {
                onScanError('Network error while checking scan progress');
            }
        }

        state._scanPollTimer = setTimeout(poll, pollInterval);
    }

    function updateScanProgress(data) {
        var total = data.total || 0;
        var scanned = data.scanned || 0;
        var matched = data.matched || 0;
        var skipped = data.skipped || 0;
        var maxDur = data.max_duration_seconds ? '\u2264' + data.max_duration_seconds + 's ' : '';

        if (scanStatus) {
            scanStatus.textContent = '';
        }

        if (scanProgress && total > 0) {
            var pct = Math.min(Math.round((scanned / total) * 100), 100);
            scanProgress.value = pct;
        }
    }

    function onScanDone(data) {
        state._scanJobId = null;
        if (scanKeywordBtn) scanKeywordBtn.disabled = false;
        if (transcribeBtn) transcribeBtn.disabled = false;
        if (scanProgress) scanProgress.hidden = true;

        // Build suffix for non-matches action
        var nonMatchNote = '';
        if (data.delete_non_matches && data.deleted_non_matches > 0) {
            nonMatchNote = ' \u00b7 ' + data.deleted_non_matches + ' non-match' + (data.deleted_non_matches !== 1 ? 'es' : '') + ' deleted';
        } else if (data.label_non_matches_as_none && data.labeled_non_matches > 0) {
            nonMatchNote = ' \u00b7 ' + data.labeled_non_matches + ' non-match' + (data.labeled_non_matches !== 1 ? 'es' : '') + ' labeled as none';
        }

        // Refresh users and storage after potential deletion/labeling
        loadUsers();
        loadStorage();

        if (scanStatus) scanStatus.textContent = '';

        if (data.matched > 0) {
            var count = data.matched;
            var msg = count + ' match' + (count !== 1 ? 'es' : '') + ' found' + nonMatchNote;
            showScanToast(msg, 'success');
            enterScanMode(data.matches, data.keyword, data.max_duration_seconds);
        } else {
            var maxDur = data.max_duration_seconds ? ' among clips \u2264' + data.max_duration_seconds + 's' : '';
            showScanToast('No matches found' + maxDur + ' (scanned ' + data.scanned + ', skipped ' + data.skipped + ')' + nonMatchNote, 'info');
            datasetTitle.textContent = 'No matches';
            clipList.innerHTML = '<p class="dataset-empty">No clips matched "' + data.keyword + '" at \u2265' + Math.round(data.min_confidence * 100) + '% confidence' + maxDur + '.</p>';
            datasetPagination.innerHTML = '<div class="pagination-inner"><button type="button" class="pagination-btn" id="clearScanBtn">Show all clips</button></div>';
            var clearBtn = $('clearScanBtn');
            if (clearBtn) {
                clearBtn.addEventListener('click', function () {
                    clearScanMode();
                });
            }
        }
    }

    function onScanError(message) {
        state._scanJobId = null;
        if (scanKeywordBtn) scanKeywordBtn.disabled = false;
        if (transcribeBtn) transcribeBtn.disabled = false;
        if (scanProgress) scanProgress.hidden = true;
        showScanToast(message, 'error');
        if (scanStatus) scanStatus.textContent = '';
    }

    function cancelScanPoll() {
        if (state._scanPollTimer) {
            clearTimeout(state._scanPollTimer);
            state._scanPollTimer = null;
        }
        state._scanJobId = null;
    }

    // ── Auto-transcript job ───────────────────────────────────────────
    async function runTranscriptJob() {
        // Cancel any previous poll
        cancelTranscriptPoll();

        if (transcribeBtn) transcribeBtn.disabled = true;
        if (scanKeywordBtn) scanKeywordBtn.disabled = true;
        state._transcriptProcessing = true;
        showScanToast('Starting auto-transcript job\u2026', 'info');
        if (scanProgress) {
            scanProgress.hidden = false;
            scanProgress.value = 0;
            scanProgress.max = 100;
        }

        var body = {};
        var gid = getSelectedGuildId();
        if (gid) body.guild_id = gid;
        if (state.selectedUserId) body.user_id = state.selectedUserId;

        try {
            var resp = await fetch('/api/speech_training/transcribe_empty', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var data = await safeParseJson(resp);
            if (data.job_id) {
                state._transcriptJobId = data.job_id;
                showScanToast('Queued\u2026', 'info');
                pollTranscriptJob(data.job_id);
            } else {
                showScanToast(data.error || 'Failed to start transcript job', 'error');
                finishTranscriptJob();
            }
        } catch (e) {
            showScanToast('Network error while starting transcript job', 'error');
            finishTranscriptJob();
        }
    }

    async function pollTranscriptJob(jobId) {
        var pollInterval = 500; // ms

        async function poll() {
            if (state._transcriptJobId !== jobId) return; // stale poll

            try {
                var resp = await fetch('/api/speech_training/transcribe_empty/' + jobId);
                var data = await safeParseJson(resp);
                if (data.status === 'queued' || data.status === 'processing') {
                    updateTranscriptProgress(data);
                    state._transcriptPollTimer = setTimeout(poll, pollInterval);
                } else if (data.status === 'done') {
                    onTranscriptDone(data);
                } else if (data.status === 'error') {
                    onTranscriptError(data.error || 'Transcript job failed');
                } else {
                    onTranscriptError(data.error || 'Unexpected status: ' + data.status);
                }
            } catch (e) {
                onTranscriptError('Network error while checking transcript progress');
            }
        }

        state._transcriptPollTimer = setTimeout(poll, pollInterval);
    }

    function updateTranscriptProgress(data) {
        var total = data.total || 0;
        var processed = data.processed || 0;
        var updated = data.updated || 0;
        var emptyMarked = data.empty_marked || 0;
        var skipped = data.skipped || 0;

        if (scanProgress && total > 0) {
            var pct = Math.min(Math.round((processed / total) * 100), 100);
            scanProgress.value = pct;
        }
        if (scanStatus && total > 0) {
            var parts = [];
            parts.push(processed + '/' + total);
            if (updated > 0) parts.push(updated + ' updated');
            if (emptyMarked > 0) parts.push(emptyMarked + ' empty');
            if (skipped > 0) parts.push(skipped + ' skipped');
            scanStatus.textContent = parts.join(' \u00b7 ');
        }
    }

    function onTranscriptDone(data) {
        state._transcriptJobId = null;
        state._transcriptProcessing = false;
        if (transcribeBtn) transcribeBtn.disabled = false;
        if (scanKeywordBtn) scanKeywordBtn.disabled = false;
        if (scanProgress) scanProgress.hidden = true;
        if (scanStatus) scanStatus.textContent = '';

        var total = data.total || 0;
        var updated = data.updated || 0;
        var emptyMarked = data.empty_marked || 0;
        var skipped = data.skipped || 0;

        // Build summary message
        var parts = [];
        if (updated > 0) parts.push(updated + ' clip' + (updated !== 1 ? 's' : '') + ' updated');
        if (emptyMarked > 0) parts.push(emptyMarked + ' empty marked \u201c-\u201d');
        if (skipped > 0) parts.push(skipped + ' skipped');
        var summary = parts.length > 0 ? parts.join(', ') : 'No empty transcripts found';
        var msg = 'Transcript job complete: ' + summary;
        showScanToast(msg, 'success');

        // Refresh the clip list to show new transcripts
        loadClips();
        loadUsers();

        // If there were errors, show them too
        if (data.errors && data.errors.length > 0) {
            var errMsg = data.errors.slice(0, 3).join('; ');
            if (data.errors.length > 3) errMsg += ' (+' + (data.errors.length - 3) + ' more)';
            showScanToast('Errors: ' + errMsg, 'error');
        }
    }

    function onTranscriptError(message) {
        state._transcriptJobId = null;
        finishTranscriptJob();
        showScanToast(message, 'error');
    }

    function finishTranscriptJob() {
        state._transcriptProcessing = false;
        if (transcribeBtn) transcribeBtn.disabled = false;
        if (scanKeywordBtn) scanKeywordBtn.disabled = false;
        if (scanProgress) scanProgress.hidden = true;
        if (scanStatus) scanStatus.textContent = '';
    }

    function cancelTranscriptPoll() {
        if (state._transcriptPollTimer) {
            clearTimeout(state._transcriptPollTimer);
            state._transcriptPollTimer = null;
        }
        state._transcriptJobId = null;
    }

    // ── Passive refresh ──────────────────────────────────────────────
    function shouldSkipPassiveClipRefresh() {
        // Skip while in scan mode
        if (state._scanMode) return true;
        // Skip while transcript job is running
        if (state._transcriptProcessing) return true;
        // Skip while user has active selections
        if (state.selectedIds.size > 0) return true;
        // Skip while audio is playing
        if (state.currentlyPlaying !== null && !state.currentlyPlaying.paused) return true;
        // Skip while any clip details panel is expanded (passive re-render would collapse it)
        if (clipList && clipList.querySelector('.dataset-clip-details:not([hidden])')) return true;
        // Skip while user is focused on a form field inside the clip area or toolbar
        const active = document.activeElement;
        if (active && active.closest) {
            const inClipArea = active.closest('.dataset-clips, .dataset-action-toolbar');
            if (inClipArea && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) {
                return true;
            }
        }
        return false;
    }

    async function passiveRefresh() {
        if (_passiveRefreshInProgress) return;
        // Don't work while the tab is hidden
        if (document.visibilityState !== 'visible') return;

        _passiveRefreshInProgress = true;
        try {
            // Refresh users on every passive tick (low disruption)
            await loadUsers({ passive: true });
            await loadStorage();

            // Refresh clips conditionally to avoid disrupting active workflows
            if (!shouldSkipPassiveClipRefresh()) {
                await loadClips({ passive: true });
            }
        } finally {
            _passiveRefreshInProgress = false;
        }
    }

    function scheduleNextPassiveRefresh() {
        if (_passiveRefreshScheduled) return;
        _passiveRefreshScheduled = true;
        state._passiveRefreshPending = setTimeout(async function () {
            _passiveRefreshScheduled = false;
            state._passiveRefreshPending = null;
            await passiveRefresh();
            scheduleNextPassiveRefresh();
        }, state._passiveIntervalMs);
    }

    // ── Visibility change ────────────────────────────────────────────
    document.addEventListener('visibilitychange', function () {
        if (document.visibilityState === 'visible') {
            // Cancel any pending scheduled refresh
            if (state._passiveRefreshPending) {
                clearTimeout(state._passiveRefreshPending);
                state._passiveRefreshPending = null;
                _passiveRefreshScheduled = false;
            }
            // Do an immediate refresh and resume the scheduling chain
            passiveRefresh().then(function () {
                scheduleNextPassiveRefresh();
            });
        }
    });

    // ── Save clip (expanded details) ─────────────────────────────────
    async function saveClip(clipEl) {
        const id = clipEl.dataset.id;
        const labelSelect = clipEl.querySelector('.dataset-clip-label-select');
        const customInput = clipEl.querySelector('.dataset-clip-custom-label');
        let label = labelSelect ? labelSelect.value : '';
        if (label === '__custom__' && customInput) {
            label = customInput.value.trim();
        }
        const transcript = clipEl.querySelector('.dataset-clip-transcript');
        const notes = clipEl.querySelector('.dataset-clip-notes');
        const statusEl = clipEl.querySelector('.dataset-save-status');

        statusEl.textContent = 'Saving…';
        statusEl.className = 'dataset-save-status';

        try {
            const resp = await fetch('/api/speech_training/clips/' + id + '/label', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    label: label || '',
                    transcript: transcript ? transcript.value : '',
                    notes: notes ? notes.value : '',
                }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                statusEl.textContent = 'Saved';
                statusEl.className = 'dataset-save-status saved';
                loadUsers();
                // If label is custom and not yet in options, add it
                if (label && state.labelOptions.indexOf(label) === -1) {
                    addLabelOption(label);
                }
                // Update label chip in quick row
                updateLabelChip(clipEl, label || '');
                // Sync the quick label select
                const quickSelect = clipEl.querySelector('.dataset-quick-label-select');
                if (quickSelect) {
                    quickSelect.innerHTML = buildLabelOptionsHtml(label || '', true, true);
                }
            } else {
                statusEl.textContent = data.error || 'Error';
                statusEl.className = 'dataset-save-status error';
            }
        } catch (e) {
            statusEl.textContent = 'Network error';
            statusEl.className = 'dataset-save-status error';
        }
    }

    // ── Bulk UI ──────────────────────────────────────────────────────
    function updateBulkUI() {
        const count = state.selectedIds.size;
        if (bulkCount) bulkCount.textContent = count + ' selected';
        if (bulkLabelSelect) bulkLabelSelect.disabled = count === 0;
        if (bulkApplyLabel) bulkApplyLabel.disabled = count === 0;
        if (bulkDelete) bulkDelete.disabled = count === 0;
    }

    // ── Bulk operations ──────────────────────────────────────────────
    async function bulkLabelClips(label) {
        const ids = Array.from(state.selectedIds);
        if (ids.length === 0) return;

        try {
            const resp = await fetch('/api/speech_training/clips/bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'label', ids: ids, label: label }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                state.selectedIds.clear();
                updateBulkUI();
                loadClips();
                loadUsers();
            } else {
                alert(data.error || 'Bulk label failed');
            }
        } catch (e) {
            alert('Network error');
        }
    }

    async function bulkDeleteClips() {
        const ids = Array.from(state.selectedIds);
        if (ids.length === 0) return;
        if (!confirm('Delete ' + ids.length + ' selected clips?')) return;

        try {
            const resp = await fetch('/api/speech_training/clips/bulk', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ action: 'delete', ids: ids }),
            });
            const data = await resp.json();
            if (data.status === 'ok') {
                state.selectedIds.clear();
                updateBulkUI();
                loadClips();
                loadUsers();
                loadStorage();
            } else {
                alert(data.error || 'Bulk delete failed');
            }
        } catch (e) {
            alert('Network error');
        }
    }

    // ── Pagination ───────────────────────────────────────────────────
    function renderPagination() {
        if (!datasetPagination) return;
        if (state.totalPages <= 1) {
            datasetPagination.innerHTML = '';
            return;
        }
        let html = '<div class="pagination-inner">';
        if (state.page > 1) {
            html += '<button type="button" class="pagination-btn" data-page="' + (state.page - 1) + '">Previous</button>';
        }
        html += '<span class="pagination-info">Page ' + state.page + ' of ' + state.totalPages + '</span>';
        if (state.page < state.totalPages) {
            html += '<button type="button" class="pagination-btn" data-page="' + (state.page + 1) + '">Next</button>';
        }
        html += '</div>';
        datasetPagination.innerHTML = html;

        datasetPagination.querySelectorAll('.pagination-btn').forEach(function (btn) {
            btn.addEventListener('click', function () {
                state.page = parseInt(btn.dataset.page, 10);
                state.selectedIds.clear();
                updateBulkUI();
                loadClips();
                window.scrollTo({ top: 0, behavior: 'smooth' });
            });
        });
    }

    // ── Search ───────────────────────────────────────────────────────
    let searchTimeout = null;
    if (datasetSearch) {
        datasetSearch.addEventListener('input', function () {
            clearTimeout(searchTimeout);
            searchTimeout = setTimeout(function () {
                state.search = datasetSearch.value.trim();
                state.page = 1;
                state.selectedIds.clear();
                updateBulkUI();
                clearScanMode(true);
                loadClips();
            }, 300);
        });
    }

    // ── Label filter dropdown ───────────────────────────────────────
    if (labelFilterSelect) {
        labelFilterSelect.addEventListener('change', function () {
            state.labelFilter = labelFilterSelect.value;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            clearScanMode(true);
            updateTitleFromFilter();
            loadClips();
        });
    }

    // ── Sort ─────────────────────────────────────────────────────────
    if (datasetSort) {
        datasetSort.addEventListener('change', function () {
            state.sort = datasetSort.value;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            clearScanMode(true);
            loadClips();
        });
    }

    // ── Bulk select all matching filters ────────────────────────────
    if (bulkSelectAll) {
        bulkSelectAll.addEventListener('click', async function () {
            if (state._scanMode) {
                // In scan mode all results are rendered at once; select them all
                for (const clip of state._scanClips) {
                    state.selectedIds.add(clip.id);
                }
            } else {
                // Fetch all matching clip IDs from the server (no pagination)
                const btn = bulkSelectAll;
                btn.disabled = true;
                btn.textContent = 'Loading\u2026';
                try {
                    const params = new URLSearchParams();
                    if (state.selectedUserId) params.set('user_id', state.selectedUserId);
                    if (state.labelFilter) params.set('label', state.labelFilter);
                    if (state.search) params.set('search', state.search);
                    if (state.sort) params.set('sort', state.sort);
                    const gid = getSelectedGuildId();
                    if (gid) params.set('guild_id', gid);
                    const resp = await fetch('/api/speech_training/clips/ids?' + params.toString());
                    if (!resp.ok) {
                        alert('Failed to load clip IDs');
                        btn.disabled = false;
                        btn.textContent = 'Select all';
                        return;
                    }
                    const data = await resp.json();
                    for (const id of data.ids) {
                        state.selectedIds.add(id);
                    }
                } catch (e) {
                    alert('Network error while selecting all clips');
                    btn.disabled = false;
                    btn.textContent = 'Select all';
                    return;
                }
                btn.disabled = false;
                btn.textContent = 'Select all';
            }
            // Sync visible checkboxes with the updated selection
            const checkboxes = clipList.querySelectorAll('.dataset-clip-checkbox');
            checkboxes.forEach(function (cb) {
                const id = parseInt(cb.dataset.id, 10);
                if (state.selectedIds.has(id)) {
                    cb.checked = true;
                    const clipEl = cb.closest('.dataset-clip');
                    if (clipEl) clipEl.classList.add('selected');
                }
            });
            updateBulkUI();
        });
    }

    if (bulkClear) {
        bulkClear.addEventListener('click', function () {
            const checkboxes = clipList.querySelectorAll('.dataset-clip-checkbox');
            checkboxes.forEach(function (cb) {
                cb.checked = false;
                const clipEl = cb.closest('.dataset-clip');
                if (clipEl) clipEl.classList.remove('selected');
            });
            state.selectedIds.clear();
            updateBulkUI();
        });
    }

    // ── Bulk label apply ─────────────────────────────────────────────
    if (bulkApplyLabel) {
        bulkApplyLabel.addEventListener('click', function () {
            const value = bulkLabelSelect ? bulkLabelSelect.value : '';
            if (!value) {
                alert('Select a label first');
                return;
            }
            if (value === '__custom__') {
                const custom = prompt('Enter custom label:');
                if (custom && custom.trim()) {
                    const label = custom.trim();
                    if (state.labelOptions.indexOf(label) === -1) {
                        addLabelOption(label);
                    }
                    bulkLabelClips(label);
                }
                return;
            }
            bulkLabelClips(value);
        });
    }

    if (bulkDelete) {
        bulkDelete.addEventListener('click', bulkDeleteClips);
    }

    // ── Keyword scan button ──────────────────────────────────────────
    if (scanKeywordBtn) {
        scanKeywordBtn.addEventListener('click', runKeywordScan);
    }

    // ── Auto-transcript button ───────────────────────────────────────
    if (transcribeBtn) {
        transcribeBtn.addEventListener('click', runTranscriptJob);
    }

    // ── Guild selector change ────────────────────────────────────────
    if (guildSelector) {
        guildSelector.addEventListener('change', function () {
            state.selectedUserId = null;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            clearScanMode(true);
            state.labelFilter = 'unlabeled';
            if (labelFilterSelect) labelFilterSelect.value = 'unlabeled';
            updateTitleFromFilter();
            loadUsers();
            loadStorage();
            loadLabels();
            loadClips();
        });
    }

    // ── Init ─────────────────────────────────────────────────────────
    // Set label filter dropdown to the initial state value
    state.labelFilter = 'unlabeled';
    if (labelFilterSelect) labelFilterSelect.value = 'unlabeled';
    updateTitleFromFilter();

    loadUsers();
    loadStorage();
    loadLabels();
    loadClips();
    // Start passive refresh chain after a brief initial delay
    scheduleNextPassiveRefresh();

})();
