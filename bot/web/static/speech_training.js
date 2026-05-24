(function () {
    'use strict';

    // ── State ────────────────────────────────────────────────────────
    const state = {
        selectedUserId: null,
        labelFilter: '',
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
    };

    // ── Passive refresh guards (module-level) ────────────────────────
    let _passiveRefreshInProgress = false;
    let _passiveRefreshScheduled = false;

    const LABEL_OPTIONS = ['chapada', 'ventura', 'none', 'unclear'];

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
    const labelFilterBtns = document.querySelectorAll('.dataset-filter-btn');
    const datasetSort = $('datasetSort');
    const bulkCount = $('bulkCount');
    const bulkSelectAll = $('bulkSelectAll');
    const bulkClear = $('bulkClear');
    const bulkLabelSelect = $('bulkLabelSelect');
    const bulkApplyLabel = $('bulkApplyLabel');
    const bulkDelete = $('bulkDelete');

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
                    datasetTitle.textContent = 'All clips';
                } else {
                    state.selectedUserId = u.user_id;
                    datasetTitle.textContent = (u.display_name || u.username) + '\u2019s clips';
                }
                state.page = 1;
                state.selectedIds.clear();
                updateBulkUI();
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

    function renderClips(items) {
        if (!clipList) return;
        if (items.length === 0) {
            clipList.innerHTML = '<p class="dataset-empty">No clips found.</p>';
            return;
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

            // Quick action buttons
            html += '<div class="dataset-clip-actions">';
            html += '<button type="button" class="dataset-quick-play" data-id="' + clip.id + '" title="Play clip" aria-label="Play clip">&#9654;</button>';
            html += '<button type="button" class="dataset-quick-label" data-id="' + clip.id + '" data-label="chapada" title="Label chapada" aria-label="Label chapada">Chapada</button>';
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
            const selOpts = ['', ...LABEL_OPTIONS, '__custom__'];
            for (const opt of selOpts) {
                const display = opt === '' ? 'None' : opt === '__custom__' ? 'Custom…' : opt;
                html += '<option value="' + opt + '"' + (opt === label ? ' selected' : '') + '>' + display + '</option>';
            }
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

                // Pause any other playing clip
                if (state.currentlyPlaying && state.currentlyPlaying !== audio) {
                    state.currentlyPlaying.pause();
                }

                if (audio.paused) {
                    audio.play().catch(function () {});
                    state.currentlyPlaying = audio;
                } else {
                    audio.pause();
                    state.currentlyPlaying = null;
                }
            });
        });

        // Quick label (Chapada)
        container.querySelectorAll('.dataset-quick-label').forEach(function (btn) {
            btn.addEventListener('click', function () {
                const id = parseInt(btn.dataset.id, 10);
                const label = btn.dataset.label;
                quickLabelClip(id, label, btn);
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
    async function quickLabelClip(id, label, btn) {
        const statusEl = btn;
        const originalText = btn.textContent;
        btn.textContent = '…';
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
                setTimeout(function () {
                    btn.textContent = originalText;
                    btn.disabled = false;
                    btn.classList.remove('saved');
                }, 1200);
                // Remove clip if filter is active and doesn't match
                if (state.labelFilter && state.labelFilter !== label && state.labelFilter !== '') {
                    const clipEl = btn.closest('.dataset-clip');
                    if (clipEl) clipEl.remove();
                    checkEmptyList();
                } else {
                    // Update label chip
                    const clipEl = btn.closest('.dataset-clip');
                    if (clipEl) {
                        const existingChip = clipEl.querySelector('.dataset-clip-label-chip');
                        if (existingChip) {
                            existingChip.textContent = label;
                            existingChip.dataset.label = label;
                        } else {
                            // No chip exists, add one
                            const meta = clipEl.querySelector('.dataset-clip-meta');
                            if (meta) {
                                const chip = document.createElement('span');
                                chip.className = 'dataset-clip-label-chip';
                                chip.dataset.label = label;
                                chip.textContent = label;
                                meta.parentNode.insertBefore(chip, meta.nextSibling);
                            }
                        }
                    }
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

    // ── Passive refresh ──────────────────────────────────────────────
    function shouldSkipPassiveClipRefresh() {
        // Skip while user has active selections
        if (state.selectedIds.size > 0) return true;
        // Skip while audio is playing
        if (state.currentlyPlaying !== null && !state.currentlyPlaying.paused) return true;
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
                // Update label chip in quick row
                const chip = clipEl.querySelector('.dataset-clip-label-chip');
                if (label && chip) {
                    chip.textContent = label;
                    chip.dataset.label = label;
                    chip.hidden = false;
                } else if (label && !chip) {
                    const meta = clipEl.querySelector('.dataset-clip-meta');
                    if (meta) {
                        const newChip = document.createElement('span');
                        newChip.className = 'dataset-clip-label-chip';
                        newChip.dataset.label = label;
                        newChip.textContent = label;
                        meta.parentNode.insertBefore(newChip, meta.nextSibling);
                    }
                } else if (!label && chip) {
                    chip.remove();
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
                loadClips();
            }, 300);
        });
    }

    // ── Label filters ────────────────────────────────────────────────
    labelFilterBtns.forEach(function (btn) {
        btn.addEventListener('click', function () {
            labelFilterBtns.forEach(function (b) { b.classList.remove('active'); });
            btn.classList.add('active');
            state.labelFilter = btn.dataset.label;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            loadClips();
        });
    });

    // ── Sort ─────────────────────────────────────────────────────────
    if (datasetSort) {
        datasetSort.addEventListener('change', function () {
            state.sort = datasetSort.value;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            loadClips();
        });
    }

    // ── Bulk select all visible ──────────────────────────────────────
    if (bulkSelectAll) {
        bulkSelectAll.addEventListener('click', function () {
            const checkboxes = clipList.querySelectorAll('.dataset-clip-checkbox');
            checkboxes.forEach(function (cb) {
                cb.checked = true;
                const id = parseInt(cb.dataset.id, 10);
                state.selectedIds.add(id);
                const clipEl = cb.closest('.dataset-clip');
                if (clipEl) clipEl.classList.add('selected');
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
                    bulkLabelClips(custom.trim());
                }
                return;
            }
            bulkLabelClips(value);
        });
    }

    if (bulkDelete) {
        bulkDelete.addEventListener('click', bulkDeleteClips);
    }

    // ── Guild selector change ────────────────────────────────────────
    if (guildSelector) {
        guildSelector.addEventListener('change', function () {
            state.selectedUserId = null;
            state.page = 1;
            state.selectedIds.clear();
            updateBulkUI();
            datasetTitle.textContent = 'All clips';
            loadUsers();
            loadStorage();
            loadClips();
        });
    }

    // ── Init ─────────────────────────────────────────────────────────
    loadUsers();
    loadStorage();
    loadClips();
    // Start passive refresh chain after a brief initial delay
    scheduleNextPassiveRefresh();

})();
