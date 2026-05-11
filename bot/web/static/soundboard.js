(() => {
        const soundboardConfigElement = document.getElementById('soundboard-config');
        const soundboardConfig = soundboardConfigElement ? JSON.parse(soundboardConfigElement.textContent || '{}') : {};
        const discordUser = soundboardConfig.discord_user || null;
        const webUserIsAdmin = Boolean(soundboardConfig.web_user_is_admin);
        const discordLoginUrl = soundboardConfig.discord_login_url || '/login';
        const initialSoundboardData = soundboardConfig.initial_soundboard_data || {};
        const initialGuildOptions = soundboardConfig.initial_guild_options || [];
        const initialSelectedGuildId = soundboardConfig.initial_selected_guild_id || null;
        const ttsProfileOptions = soundboardConfig.tts_profile_options || [];
        const themeToggle = document.querySelector('.theme-toggle');
        const guildSelector = document.getElementById('guildSelector');
        let webControlMuteIsMuted = false;
        let webControlStateRequestInFlight = false;
        let controlRoomRequestInFlight = false;
        let latestControlRoomStatus = {};
        let currentPageActions = 1;
        let currentPageFavorites = 1;
        let currentPageAllSounds = 1;
        const endpointMaxItemsPerPage = {
            actions: 7,
            favorites: 7,
            all_sounds: 7
        };
        const endpointItemsPerPage = {
            ...endpointMaxItemsPerPage
        };
        const endpointTableBodyIds = {
            actions: 'actionsTableBody',
            favorites: 'favoritesTableBody',
            all_sounds: 'allSoundsTableBody'
        };
        const endpointResultMetaIds = {
            actions: 'actionsResultMeta',
            favorites: 'favoritesResultMeta',
            all_sounds: 'allSoundsResultMeta'
        };
        const endpointLabels = {
            actions: 'actions',
            favorites: 'favorites',
            all_sounds: 'sounds'
        };
        const endpointStableItemsPerPageCeilings = {
            ...endpointMaxItemsPerPage
        };
        const filterColumnKeysByEndpoint = {
            actions: ['action', 'user'],
            favorites: ['user'],
            all_sounds: ['list']
        };

        function getInitialFetchedItems(endpoint) {
            return (initialSoundboardData?.[endpoint]?.items || []).map(item => {
                const copy = { ...item };
                delete copy.display_time_ago;
                return copy;
            });
        }

        function getRenderableFilterSnapshot(endpoint, filters) {
            const keys = filterColumnKeysByEndpoint[endpoint] || [];
            return keys.reduce((snapshot, key) => {
                snapshot[key] = filters?.[key] || [];
                return snapshot;
            }, {});
        }

        const lastFetchedData = {
            actions: getInitialFetchedItems('actions'),
            favorites: getInitialFetchedItems('favorites'),
            all_sounds: getInitialFetchedItems('all_sounds')
        };

        const lastRenderedFilters = {
            actions: JSON.stringify(getRenderableFilterSnapshot('actions', initialSoundboardData?.actions?.filters)),
            favorites: JSON.stringify(getRenderableFilterSnapshot('favorites', initialSoundboardData?.favorites?.filters)),
            all_sounds: JSON.stringify(getRenderableFilterSnapshot('all_sounds', initialSoundboardData?.all_sounds?.filters))
        };

        const filterState = {
            actions: {},
            favorites: {},
            all_sounds: {}
        };

        const filterConfigs = {
            actions: {
                containerId: 'filtersActions',
                columns: [
                    { key: 'action', label: 'Action', formatOption: formatAction, hideLabel: true, ariaLabel: 'Filter recent actions by action' },
                    { key: 'user', label: 'User', hideLabel: true, ariaLabel: 'Filter recent actions by user' }
                ]
            },
            favorites: {
                containerId: 'filtersFavorites',
                columns: [
                    { key: 'user', label: 'User', allLabel: 'All Users', hideLabel: true, ariaLabel: 'Filter favorites by user' }
                ]
            },
            all_sounds: {
                containerId: 'filtersAllSounds',
                columns: [
                    { key: 'list', label: 'List', allLabel: 'All Lists', hideLabel: true, ariaLabel: 'Filter all sounds by list' }
                ]
            }
        };

        function getSelectedGuildId() {
            const selected = guildSelector?.value || initialSelectedGuildId || '';
            return selected ? String(selected) : '';
        }

        function appendGuildParam(params) {
            const guildId = getSelectedGuildId();
            if (guildId) {
                params.set('guild_id', guildId);
            }
        }

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

        function parseServerTimestamp(timestamp) {
            if (!timestamp) return new Date(NaN);
            if (timestamp instanceof Date) return timestamp;
            const normalized = String(timestamp).trim().replace(' ', 'T');
            if (/([zZ]|[+-]\d{2}:\d{2})$/.test(normalized)) {
                return new Date(normalized);
            }
            return new Date(`${normalized}Z`);
        }

        function formatTimeAgo(timestamp) {
            const date = parseServerTimestamp(timestamp);
            if (Number.isNaN(date.getTime())) {
                return timestamp || '';
            }
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return 'now';
            if (diffMins < 60) return `${diffMins}m`;
            if (diffHours < 24) return `${diffHours}h`;
            if (diffDays < 30) return `${diffDays}d`;
            return date.toLocaleDateString();
        }

        function applyPlayButtonState(button) {
            button.disabled = false;
            button.classList.toggle('login-required', !discordUser);
            button.textContent = discordUser ? '▶' : '🔒';
            const readiness = getPlaybackReadinessLabel();
            button.title = discordUser
                ? (readiness ? `Play sound. ${readiness}` : 'Play sound')
                : 'Login with Discord to play';
            button.setAttribute('aria-label', button.title);
        }

        function buildSoundPlayButton(item) {
            const playButton = document.createElement('button');
            playButton.className = 'play-button';
            playButton.setAttribute('data-sound-id', item.sound_id);
            applyPlayButtonState(playButton);
            return playButton;
        }

        function buildSoundOptionsButton(item) {
            const optionsButton = document.createElement('button');
            optionsButton.type = 'button';
            optionsButton.className = 'sound-options-button';
            optionsButton.dataset.soundId = item.sound_id;
            optionsButton.textContent = '⋯';
            optionsButton.title = 'Sound options';
            optionsButton.setAttribute('aria-label', 'Show sound options');
            return optionsButton;
        }

        function applyWebControlButtonState(button) {
            button.disabled = false;
            button.classList.toggle('login-required', !discordUser);
            if (!discordUser) {
                button.textContent = '🔒';
                button.title = 'Login with Discord to use bot controls';
                button.setAttribute('aria-label', button.title);
                return;
            }
            const action = button.dataset.controlAction;
            if (action === 'slap') {
                button.textContent = '👋';
                button.title = 'Slap';
            } else if (action === 'tts') {
                button.textContent = '💬';
                button.title = 'Text to speech';
            } else {
                button.textContent = webControlMuteIsMuted ? '🔊' : '🔇';
                button.title = webControlMuteIsMuted ? 'Unmute' : 'Mute for 30 minutes';
            }
            button.setAttribute('aria-label', button.title);
        }

        function updateWebControlMuteState(isMuted) {
            webControlMuteIsMuted = Boolean(isMuted);
            document
                .querySelectorAll('.web-control-button[data-control-action="toggle_mute"]')
                .forEach(button => {
                    if (!button.classList.contains('sent') && !button.classList.contains('error')) {
                        applyWebControlButtonState(button);
                    }
                });
        }

        async function refreshWebControlState() {
            if (!discordUser || webControlStateRequestInFlight) {
                return;
            }

            webControlStateRequestInFlight = true;
            try {
                const params = new URLSearchParams();
                appendGuildParam(params);
                const response = await fetch(`/api/web_control_state?${params.toString()}`);
                if (!response.ok) {
                    return;
                }
                const payload = await response.json();
                updateWebControlMuteState(payload?.mute?.is_muted);
            } catch (error) {
                console.error('Error loading web control state:', error);
            } finally {
                webControlStateRequestInFlight = false;
            }
        }

        function cleanSoundLabel(filename) {
            return String(filename || '').replace(/\.mp3$/i, '') || 'Nothing playing';
        }

        function formatDurationSeconds(seconds) {
            const numericSeconds = Number(seconds);
            if (!Number.isFinite(numericSeconds) || numericSeconds < 0) {
                return '';
            }
            const totalSeconds = Math.round(numericSeconds);
            const hours = Math.floor(totalSeconds / 3600);
            const minutes = Math.floor((totalSeconds % 3600) / 60);
            const secs = totalSeconds % 60;
            if (hours > 0) {
                return `${hours}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')}`;
            }
            return `${minutes}:${String(secs).padStart(2, '0')}`;
        }

        function setControlRoomText(id, value) {
            const element = document.getElementById(id);
            if (element) {
                element.textContent = value;
            }
        }

        function renderControlRoomSubtitleText(value) {
            const element = document.getElementById('controlRoomRequester');
            if (!element) {
                return;
            }
            element.classList.remove('has-progress');
            element.replaceChildren(document.createTextNode(value));
        }

        function renderControlRoomProgress(status, requester) {
            const element = document.getElementById('controlRoomRequester');
            if (!element) {
                return;
            }

            const elapsedSeconds = Number(status.current_elapsed_seconds);
            const durationSeconds = Number(status.current_duration_seconds);
            const hasElapsed = Number.isFinite(elapsedSeconds) && elapsedSeconds >= 0;
            const hasDuration = Number.isFinite(durationSeconds) && durationSeconds > 0;
            const elapsed = hasElapsed ? formatDurationSeconds(elapsedSeconds) : '';
            const total = hasDuration ? formatDurationSeconds(durationSeconds) : '';
            const progressPercent = hasElapsed && hasDuration
                ? Math.max(0, Math.min(100, (elapsedSeconds / durationSeconds) * 100))
                : 0;

            element.classList.add('has-progress');

            const requesterLabel = document.createElement('span');
            requesterLabel.className = 'control-room-requester-label';
            requesterLabel.textContent = requester;

            const progressShell = document.createElement('span');
            progressShell.className = 'control-room-progress';
            progressShell.setAttribute(
                'aria-label',
                elapsed && total ? `Playback progress ${elapsed} of ${total}` : 'Playback progress'
            );

            const progressTrack = document.createElement('span');
            progressTrack.className = 'control-room-progress-track';

            const progressFill = document.createElement('span');
            progressFill.className = 'control-room-progress-fill';
            progressFill.style.width = `${progressPercent}%`;

            const progressTime = document.createElement('span');
            progressTime.className = 'control-room-progress-time';
            progressTime.textContent = elapsed && total ? `${elapsed} / ${total}` : (total || elapsed);

            progressTrack.appendChild(progressFill);
            progressShell.append(progressTrack, progressTime);
            element.replaceChildren(requesterLabel, progressShell);
        }

        function getVoiceMembersInitials(name) {
            return String(name || '?').trim().slice(0, 1).toUpperCase() || '?';
        }

        function renderVoiceMembersInto(titleEl, listEl) {
            if (!titleEl || !listEl) return;

            const status = latestControlRoomStatus || {};
            titleEl.textContent = status.voice_connected
                ? (status.voice_channel_name || 'Voice')
                : 'Disconnected';

            const members = Array.isArray(status.voice_members) ? status.voice_members : [];
            if (!status.voice_connected) {
                listEl.innerHTML = '<p class="voice-members-empty">Bot is not connected to a voice channel.</p>';
                return;
            }
            if (!members.length) {
                listEl.innerHTML = '<p class="voice-members-empty">No users are in this voice channel.</p>';
                return;
            }

            listEl.replaceChildren(...members.map((member) => {
                const row = document.createElement('div');
                row.className = 'voice-member-row';

                const avatar = document.createElement('div');
                avatar.className = 'voice-member-avatar';
                if (member.avatar_url) {
                    const image = document.createElement('img');
                    image.src = member.avatar_url;
                    image.alt = '';
                    avatar.appendChild(image);
                } else {
                    avatar.textContent = getVoiceMembersInitials(member.name);
                }

                const name = document.createElement('strong');
                name.className = 'voice-member-name';
                name.textContent = member.name || 'Unknown';

                row.append(avatar, name);
                return row;
            }));
        }

        function renderVoiceMembersModal() {
            renderVoiceMembersInto(
                document.getElementById('voiceMembersModalTitle'),
                document.getElementById('voiceMembersList')
            );
        }

        function renderVoiceMembersDropdown() {
            renderVoiceMembersInto(
                document.getElementById('voiceMembersDropdownTitle'),
                document.getElementById('voiceMembersDropdownList')
            );
        }

        function openVoiceMembersDropdown() {
            const dropdown = document.getElementById('voiceMembersDropdown');
            if (!dropdown) return;
            renderVoiceMembersDropdown();
            dropdown.classList.add('open');
            dropdown.setAttribute('aria-hidden', 'false');
        }

        function closeVoiceMembersDropdown() {
            const dropdown = document.getElementById('voiceMembersDropdown');
            if (!dropdown) return;
            dropdown.classList.remove('open');
            dropdown.setAttribute('aria-hidden', 'true');
        }

        function openVoiceMembersModal() {
            const modal = document.getElementById('voiceMembersModal');
            if (!modal) return;
            closeVoiceMembersDropdown();
            renderVoiceMembersModal();
            modal.classList.add('open');
            modal.setAttribute('aria-hidden', 'false');
        }

        function closeVoiceMembersModal() {
            const modal = document.getElementById('voiceMembersModal');
            if (!modal) return;
            modal.classList.remove('open');
            modal.setAttribute('aria-hidden', 'true');
        }

        function updateControlRoomStatus(payload) {
            const status = payload?.status || {};
            latestControlRoomStatus = status;
            const mute = payload?.mute || {};
            const dot = document.getElementById('controlRoomStateDot');
            const isPlaying = Boolean(status.is_playing || status.is_paused);
            const currentSound = cleanSoundLabel(status.current_sound);
            const requester = status.current_requester ? `Requested by ${status.current_requester}` : 'No active requester';

            if (dot) {
                dot.classList.toggle('playing', isPlaying);
                dot.classList.toggle('idle', !isPlaying);
                dot.classList.toggle('offline', !status.online);
            }

            setControlRoomText(
                'controlRoomNowPlaying',
                isPlaying ? currentSound : (status.online ? 'Idle' : 'Bot status unavailable')
            );
            if (isPlaying) {
                renderControlRoomProgress(status, requester);
            } else {
                renderControlRoomSubtitleText(
                    status.voice_connected ? 'Ready in voice' : 'Waiting outside voice'
                );
            }

            const voiceLabel = status.voice_connected
                ? `${status.voice_channel_name || 'Voice'} (${status.voice_member_count || 0})`
                : 'Disconnected';
            setControlRoomText('controlRoomVoice', voiceLabel);
            const voiceButton = document.getElementById('controlRoomVoiceButton');
            if (voiceButton) {
                voiceButton.disabled = !status.voice_connected;
                voiceButton.setAttribute(
                    'aria-label',
                    status.voice_connected
                        ? `Show ${status.voice_member_count || 0} voice channel members`
                        : 'Voice channel disconnected'
                );
            }

            const muted = Boolean(mute.is_muted);
            updateWebControlMuteState(muted);
            document.querySelectorAll('.play-button').forEach(applyPlayButtonState);
        }

        function getPlaybackReadinessLabel() {
            const status = latestControlRoomStatus || {};
            if (typeof status.online === 'undefined') {
                return '';
            }
            if (!status.online) {
                return 'Bot status is unavailable.';
            }
            if (!status.voice_connected) {
                return 'Bot is not connected to voice.';
            }
            return `Ready in ${status.voice_channel_name || 'voice'}.`;
        }

        async function refreshControlRoomStatus() {
            if (controlRoomRequestInFlight) {
                return;
            }

            controlRoomRequestInFlight = true;
            try {
                const params = new URLSearchParams();
                appendGuildParam(params);
                const response = await fetch(`/api/control_room/status?${params.toString()}`);
                if (!response.ok) {
                    return;
                }
                const payload = await response.json();
                updateControlRoomStatus(payload);
            } catch (error) {
                console.error('Error loading control room status:', error);
            } finally {
                controlRoomRequestInFlight = false;
            }
        }

        function getBaseTableRowHeight() {
            const rootStyles = getComputedStyle(document.documentElement);
            const rowHeight = parseFloat(rootStyles.getPropertyValue('--table-row-height'));
            return Number.isFinite(rowHeight) && rowHeight > 0 ? rowHeight : 54;
        }

        function getTableHeaderHeight() {
            const rootStyles = getComputedStyle(document.documentElement);
            const headerHeight = parseFloat(rootStyles.getPropertyValue('--table-header-height'));
            return Number.isFinite(headerHeight) && headerHeight > 0 ? headerHeight : 54;
        }

        function getTableHeaderFootprint(tableHead) {
            const measuredHeight = tableHead ? Math.ceil(tableHead.getBoundingClientRect().height) : 0;
            return measuredHeight > 0 ? measuredHeight : getTableHeaderHeight() + 1;
        }

        function getTableRowBorderAllowance(rowCount) {
            return Math.max(0, rowCount - 1);
        }

        function getTableBottomInset(container) {
            const containerStyles = getComputedStyle(container);
            const inset = parseFloat(containerStyles.getPropertyValue('--table-bottom-inset'));
            return Number.isFinite(inset) && inset >= 0 ? inset : 0;
        }

        function getMeasuredTableRowFootprint(tableBody) {
            const firstRow = tableBody?.querySelector('tr');
            const measuredHeight = firstRow ? Math.ceil(firstRow.getBoundingClientRect().height) : 0;
            const baseRowHeight = getBaseTableRowHeight();
            if (measuredHeight > 0) {
                return Math.min(measuredHeight, baseRowHeight) + 1;
            }

            return baseRowHeight + 1;
        }

        function getEndpointForTableBodyId(tableBodyId) {
            return Object.entries(endpointTableBodyIds)
                .find(([, bodyId]) => bodyId === tableBodyId)?.[0] || null;
        }

        function getTableFitSafetyBuffer() {
            return 0;
        }

        function isLastTableRowClipped(container, tableBody) {
            const lastRow = tableBody?.lastElementChild;
            if (!container || !lastRow) {
                return false;
            }

            const containerRect = container.getBoundingClientRect();
            const lastRowRect = lastRow.getBoundingClientRect();
            return lastRowRect.bottom > (containerRect.bottom - 2);
        }

        function isCardOverflowingViewport(container) {
            const card = container ? container.closest('.card') : null;
            if (!card) {
                return false;
            }

            return card.getBoundingClientRect().bottom > (window.innerHeight - 12);
        }

        function calculateItemsPerPage(tableBodyId) {
            const endpoint = getEndpointForTableBodyId(tableBodyId);
            return endpoint ? endpointStableItemsPerPageCeilings[endpoint] : null;
        }

        function applyTableGeometry(endpoint) {
            const tableBody = document.getElementById(endpointTableBodyIds[endpoint]);
            const container = tableBody ? tableBody.closest('.table-container') : null;
            const table = container ? container.querySelector('table') : null;
            if (!tableBody || !container || !table) {
                return;
            }

            const visibleRows = Math.max(1, endpointItemsPerPage[endpoint] || endpointMaxItemsPerPage[endpoint]);
            const targetHeight = Math.ceil(
                getTableHeaderHeight()
                + (getBaseTableRowHeight() * visibleRows)
                + getTableBottomInset(container)
                + 2
            );
            container.style.setProperty('--soundboard-table-height', `${targetHeight}px`);
            table.style.removeProperty('--table-row-height');
        }

        function getEndpointColumnCount(endpoint) {
            return {
                actions: 4,
                favorites: 3,
                all_sounds: 4
            }[endpoint] || 1;
        }

        function getEndpointSearchInputId(endpoint) {
            return {
                actions: 'searchActions',
                favorites: 'searchFavorites',
                all_sounds: 'searchAllSounds'
            }[endpoint] || '';
        }

        function getEndpointSearchQuery(endpoint) {
            const inputId = getEndpointSearchInputId(endpoint);
            const input = inputId ? document.getElementById(inputId) : null;
            return input ? input.value.trim() : '';
        }

        function updateResultMeta(endpoint, data, page) {
            const element = document.getElementById(endpointResultMetaIds[endpoint]);
            if (!element) {
                return;
            }
            const totalCount = Number(data?.total_count);
            const items = Array.isArray(data?.items) ? data.items : [];
            const searchQuery = getEndpointSearchQuery(endpoint);
            const label = endpointLabels[endpoint] || 'items';
            if (!Number.isFinite(totalCount)) {
                element.textContent = searchQuery ? `Search: ${searchQuery}` : '';
                return;
            }
            if (totalCount === 0) {
                element.textContent = searchQuery ? `No ${label} found for "${searchQuery}".` : `No ${label} found.`;
                return;
            }
            const pageStart = ((Math.max(1, page) - 1) * (endpointItemsPerPage[endpoint] || items.length)) + 1;
            const pageEnd = Math.min(totalCount, pageStart + items.length - 1);
            element.textContent = searchQuery
                ? `${totalCount} ${label} match "${searchQuery}". Showing ${pageStart}-${pageEnd}.`
                : `${totalCount} ${label}. Showing ${pageStart}-${pageEnd}.`;
        }

        function renderNoResultsRow(endpoint, tableBody) {
            const row = document.createElement('tr');
            row.className = 'empty-row';
            const cell = document.createElement('td');
            cell.colSpan = getEndpointColumnCount(endpoint);
            cell.className = 'empty-state';
            const searchQuery = getEndpointSearchQuery(endpoint);
            const label = endpointLabels[endpoint] || 'items';
            cell.textContent = searchQuery ? `No ${label} match "${searchQuery}".` : `No ${label} found.`;
            row.appendChild(cell);
            tableBody.appendChild(row);
        }

        function renderInitialTablePlaceholders(endpoint) {
            const tableBody = document.getElementById(endpointTableBodyIds[endpoint]);
            if (!tableBody || tableBody.children.length) {
                return;
            }

            const fragment = document.createDocumentFragment();
            const columnCount = getEndpointColumnCount(endpoint);
            const rowCount = endpointItemsPerPage[endpoint] || endpointMaxItemsPerPage[endpoint];

            for (let rowIndex = 0; rowIndex < rowCount; rowIndex++) {
                const row = document.createElement('tr');
                row.className = 'placeholder-row';
                for (let columnIndex = 0; columnIndex < columnCount; columnIndex++) {
                    row.appendChild(document.createElement('td'));
                }
                fragment.appendChild(row);
            }

            tableBody.replaceChildren(fragment);
            applyTableGeometry(endpoint);
        }

        function renderInitialTablePlaceholdersForAllEndpoints() {
            Object.keys(endpointTableBodyIds).forEach(renderInitialTablePlaceholders);
        }

        const pendingInitialRenderEndpoints = new Set();
        const deferredInitialRenders = {};

        function flushInitialRendersIfReady() {
            if (pendingInitialRenderEndpoints.size > 0) {
                return;
            }

            Object.keys(endpointTableBodyIds).forEach(endpoint => {
                if (deferredInitialRenders[endpoint]) {
                    deferredInitialRenders[endpoint]();
                    delete deferredInitialRenders[endpoint];
                }
            });
        }

        function deferOrRunEndpointRender(endpoint, renderCallback) {
            if (!pendingInitialRenderEndpoints.has(endpoint)) {
                renderCallback();
                return;
            }

            deferredInitialRenders[endpoint] = renderCallback;
            pendingInitialRenderEndpoints.delete(endpoint);
            flushInitialRendersIfReady();
        }

        function markInitialEndpointDone(endpoint) {
            if (!pendingInitialRenderEndpoints.has(endpoint)) {
                return;
            }

            pendingInitialRenderEndpoints.delete(endpoint);
            flushInitialRendersIfReady();
        }

        function updateItemsPerPage(endpoint) {
            const fittedItemsPerPage = calculateItemsPerPage(endpointTableBodyIds[endpoint]);
            if (!fittedItemsPerPage || fittedItemsPerPage === endpointItemsPerPage[endpoint]) {
                return false;
            }

            endpointItemsPerPage[endpoint] = fittedItemsPerPage;
            return true;
        }

        function getActionClass(action) {
            if (action.includes('play')) return 'play';
            if (action.includes('favorite')) return 'favorite';
            if (action === 'join') return 'join';
            if (action === 'leave') return 'leave';
            if (action.startsWith('keyword')) return 'keyword';
            if (action.includes('startup') || action.includes('periodic') || action.includes('scheduler') || action.includes('auto')) return 'system';
            return 'other';
        }

        function formatAction(action) {
            const actionMap = {
                'play_random_sound': 'Random',
                'play_request': 'Played',
                'replay_sound': 'Replayed',
                'play_from_list': 'List',
                'play_similar_sound': 'Similar',
                'play_sound_periodically': 'Auto',
                'play_random_favorite_sound': 'Favorite',
                'play_slap': 'Slap',
                'mute_30_minutes': 'Muted',
                'unmute': 'Unmuted',
                'favorite_sound': 'Favorited',
                'unfavorite_sound': 'Unfavorited',
                'join': 'Joined',
                'leave': 'Left',
                'rlstore_daily_notification_sent': 'RL Store'
            };
            return actionMap[action] || action.replace(/_/g, ' ');
        }

        function fitActionBadges(scope = document) {
            const badges = scope.querySelectorAll('.action-badge');
            const baseRem = 0.52;
            const minRem = 0.38;
            const step = 0.02;
            badges.forEach((badge) => {
                badge.style.fontSize = '';
                let size = baseRem;
                badge.style.fontSize = size + 'rem';
                while (size > minRem) {
                    const overflows = badge.scrollWidth > badge.clientWidth + 1 || badge.scrollHeight > badge.clientHeight + 1;
                    if (!overflows) break;
                    size -= step;
                    badge.style.fontSize = size + 'rem';
                }
            });
        }

        function buildSoundLabel(item) {
            const wrapper = document.createElement('span');
            wrapper.className = 'sound-label';

            const title = document.createElement('span');
            title.className = 'sound-title';
            title.textContent = (item.display_filename || '').replace('.mp3', '');
            wrapper.appendChild(title);

            if (item.display_duration) {
                const duration = document.createElement('span');
                duration.className = 'sound-duration';
                duration.textContent = item.display_duration;
                wrapper.appendChild(duration);
            }

            return wrapper;
        }

        function buildFilterQuery(endpoint) {
            const params = new URLSearchParams();
            const filters = filterState[endpoint] || {};

            Object.entries(filters).forEach(([key, values]) => {
                values.forEach(value => params.append(key, value));
            });

            return params.toString();
        }

        function renderFilterControls(endpoint, filters, fetchFunction) {
            const config = filterConfigs[endpoint];
            if (!config) return;

            const container = document.getElementById(config.containerId);
            if (!container) return;

            const serializedFilters = JSON.stringify(getRenderableFilterSnapshot(endpoint, filters));
            if (lastRenderedFilters[endpoint] === serializedFilters) {
                return;
            }

            const activeElement = document.activeElement;
            if (activeElement && container.contains(activeElement)) {
                return;
            }

            const currentSelections = filterState[endpoint] || {};
            const fragment = document.createDocumentFragment();

            config.columns.forEach(column => {
                const wrapper = document.createElement('div');
                wrapper.className = 'filter-group';

                if (!column.hideLabel) {
                    const label = document.createElement('label');
                    label.className = 'filter-label';
                    label.textContent = column.label;
                    label.setAttribute('for', `${endpoint}-${column.key}-filter`);
                    wrapper.appendChild(label);
                }

                const select = document.createElement('select');
                select.id = `${endpoint}-${column.key}-filter`;
                select.className = 'filter-select';
                select.dataset.endpoint = endpoint;
                select.dataset.filterKey = column.key;
                if (column.ariaLabel) {
                    select.setAttribute('aria-label', column.ariaLabel);
                }

                const options = filters[column.key] || [];
                const selectedValue = (currentSelections[column.key] || [])[0] || '';
                const formatter = column.formatOption || (value => value);

                const allOption = document.createElement('option');
                allOption.value = '';
                allOption.textContent = column.allLabel || `All ${column.label}`;
                allOption.selected = selectedValue === '';
                select.appendChild(allOption);

                options.forEach(rawOption => {
                    const value = getFilterOptionValue(rawOption);
                    const option = document.createElement('option');
                    option.value = value;
                    option.textContent = getFilterOptionLabel(rawOption, formatter);
                    option.selected = selectedValue === value;
                    select.appendChild(option);
                });

                const shell = document.createElement('div');
                shell.className = 'select-shell';
                shell.appendChild(select);
                wrapper.appendChild(shell);
                fragment.appendChild(wrapper);
            });

            container.replaceChildren(fragment);
            lastRenderedFilters[endpoint] = serializedFilters;
        }

        function getFilterOptionValue(option) {
            if (option && typeof option === 'object') {
                return String(option.value ?? '');
            }

            return String(option ?? '');
        }

        function getFilterOptionLabel(option, formatter) {
            if (option && typeof option === 'object') {
                return String(option.label ?? formatter(getFilterOptionValue(option)));
            }

            return String(formatter(getFilterOptionValue(option)));
        }

        function hasRenderableFilterPayload(endpoint, filters) {
            const keys = filterColumnKeysByEndpoint[endpoint] || [];
            return keys.length > 0 && keys.every(key => Array.isArray(filters?.[key]));
        }

        function updatePaginationControls(page, totalPages, totalPagesId, prevButtonId, nextButtonId, pageInputId) {
            const totalPageCount = Number.isFinite(totalPages) ? totalPages : 0;
            const pageInput = document.getElementById(pageInputId);
            const prevButton = document.getElementById(prevButtonId);
            const nextButton = document.getElementById(nextButtonId);

            document.getElementById(totalPagesId).textContent = totalPageCount;
            if (pageInput) {
                pageInput.value = page;
                pageInput.max = Math.max(1, totalPageCount);
            }

            prevButton.disabled = (page <= 1);
            nextButton.disabled = (page >= totalPageCount);
        }

        function setEndpointLoading(endpoint, isLoading) {
            const config = filterConfigs[endpoint];
            const container = config ? document.getElementById(config.containerId) : null;
            const tableBody = document.getElementById(endpointTableBodyIds[endpoint]);
            const tableContainer = tableBody ? tableBody.closest('.table-container') : null;

            if (container) {
                container.querySelectorAll('.filter-select').forEach(select => {
                    select.disabled = isLoading;
                });
            }

            if (tableContainer) {
                tableContainer.classList.toggle('is-loading', isLoading);
                tableContainer.setAttribute('aria-busy', isLoading ? 'true' : 'false');
            }
        }

        function fetchData(endpoint, page, tableBodyId, totalPagesId, prevButtonId, nextButtonId, pageInputId, searchInputId, showLoading = false) {
            const tableBody = document.getElementById(tableBodyId);
            const container = tableBody ? tableBody.closest('.table-container') : null;
            const searchInput = document.getElementById(searchInputId);
            const searchQuery = searchInput ? searchInput.value.trim() : '';

            const filterQuery = buildFilterQuery(endpoint);
            const includeFiltersQuery = '&include_filters=0';
            const guildId = getSelectedGuildId();
            const guildQuery = guildId ? `&guild_id=${encodeURIComponent(guildId)}` : '';
            const apiUrl = `/api/${endpoint}?page=${page}&per_page=${endpointItemsPerPage[endpoint]}&search=${encodeURIComponent(searchQuery)}${guildQuery}${includeFiltersQuery}${filterQuery ? `&${filterQuery}` : ''}`;

            if (showLoading) {
                setEndpointLoading(endpoint, true);
            }
            return fetch(apiUrl)
                .then(response => response.json())
                .then(data => {
                    if (hasRenderableFilterPayload(endpoint, data.filters) && !pendingInitialRenderEndpoints.has(endpoint)) {
                        renderFilterControls(endpoint, data.filters || {}, fetchersByEndpoint[endpoint]);
                    }

                    const hasNewEntries = JSON.stringify(data.items) !== JSON.stringify(lastFetchedData[endpoint]);
                    updatePaginationControls(page, data.total_pages, totalPagesId, prevButtonId, nextButtonId, pageInputId);
                    updateResultMeta(endpoint, data, page);

                    if (hasNewEntries || showLoading) {
                        lastFetchedData[endpoint] = data.items;

                        const renderFetchedData = () => {
                            if (hasRenderableFilterPayload(endpoint, data.filters)) {
                                renderFilterControls(endpoint, data.filters || {}, fetchersByEndpoint[endpoint]);
                            }

                            tableBody.innerHTML = '';

                            if (!data.items.length) {
                                renderNoResultsRow(endpoint, tableBody);
                            }

                            data.items.forEach((item, index) => {
                                const row = document.createElement('tr');

                                if (endpoint === 'actions') {
                                    const actionCell = document.createElement('td');
                                    const badge = document.createElement('span');
                                    badge.className = `action-badge ${getActionClass(item.action)}`;
                                    badge.textContent = formatAction(item.action);
                                    actionCell.appendChild(badge);
                                    row.appendChild(actionCell);

                                    const filenameCell = document.createElement('td');
                                    filenameCell.className = 'filename';
                                    filenameCell.textContent = (item.display_filename || '-').replace('.mp3', '');
                                    filenameCell.title = item.display_filename || '';
                                    row.appendChild(filenameCell);

                                    const usernameCell = document.createElement('td');
                                    usernameCell.textContent = item.display_username || '';
                                    row.appendChild(usernameCell);

                                    const timestampCell = document.createElement('td');
                                    timestampCell.textContent = formatTimeAgo(item.timestamp);
                                    timestampCell.title = item.timestamp;
                                    row.appendChild(timestampCell);
                                } else if (endpoint === 'favorites') {
                                    row.className = 'sound-options-row';
                                    row.dataset.soundId = item.sound_id;
                                    row.dataset.favorite = 'true';
                                    row.dataset.slap = item.slap ? 'true' : 'false';

                                    const filenameCell = document.createElement('td');
                                    filenameCell.className = 'filename';
                                    filenameCell.title = item.display_filename || '';
                                    filenameCell.appendChild(buildSoundLabel(item));
                                    row.appendChild(filenameCell);

                                    const playCell = document.createElement('td');
                                    playCell.appendChild(buildSoundPlayButton(item));
                                    row.appendChild(playCell);

                                    const optionsCell = document.createElement('td');
                                    optionsCell.appendChild(buildSoundOptionsButton(item));
                                    row.appendChild(optionsCell);
                                } else if (endpoint === 'all_sounds') {
                                    row.className = 'sound-options-row';
                                    row.dataset.soundId = item.sound_id;
                                    row.dataset.favorite = item.favorite ? 'true' : 'false';
                                    row.dataset.slap = item.slap ? 'true' : 'false';

                                    const filenameCell = document.createElement('td');
                                    filenameCell.className = 'filename';
                                    filenameCell.title = item.display_filename || '';
                                    filenameCell.appendChild(buildSoundLabel(item));
                                    row.appendChild(filenameCell);

                                    const dateCell = document.createElement('td');
                                    dateCell.textContent = formatTimeAgo(item.timestamp);
                                    dateCell.title = item.timestamp;
                                    row.appendChild(dateCell);

                                    const playCell = document.createElement('td');
                                    playCell.appendChild(buildSoundPlayButton(item));
                                    row.appendChild(playCell);

                                    const optionsCell = document.createElement('td');
                                    optionsCell.appendChild(buildSoundOptionsButton(item));
                                    row.appendChild(optionsCell);
                                }

                                tableBody.appendChild(row);
                            });

                            applyTableGeometry(endpoint);
                            fitActionBadges(tableBody);

                            const pageSizeChanged = updateItemsPerPage(endpoint);
                            if (pageSizeChanged) {
                                fetchersByEndpoint[endpoint](null, true);
                            }
                        };

                        deferOrRunEndpointRender(endpoint, renderFetchedData);
                    }

                    return hasNewEntries;
                })
                .catch(error => {
                    console.error('Error:', error);
                    markInitialEndpointDone(endpoint);
                    return false;
                })
                .finally(() => {
                    if (showLoading) {
                        setEndpointLoading(endpoint, false);
                    }
                });
        }

        function setupPagination(prevButtonId, nextButtonId, fetchFunction) {
            const prevButton = document.getElementById(prevButtonId);
            const nextButton = document.getElementById(nextButtonId);
            let requestInFlight = false;
            let lastTouchHandledAt = 0;

            async function handleButtonClick(button, increment, event) {
                if (event) {
                    event.preventDefault();
                    event.stopPropagation();
                }

                if (requestInFlight || button.disabled) {
                    return;
                }

                if (event?.type === 'touchend') {
                    lastTouchHandledAt = Date.now();
                } else if (event?.type === 'click' && Date.now() - lastTouchHandledAt < 700) {
                    return;
                }

                requestInFlight = true;
                try {
                    await fetchFunction(increment);
                } finally {
                    requestInFlight = false;
                }
            }

            prevButton.addEventListener('click', event => handleButtonClick(prevButton, false, event));
            nextButton.addEventListener('click', event => handleButtonClick(nextButton, true, event));
            prevButton.addEventListener('touchend', event => handleButtonClick(prevButton, false, event), { passive: false });
            nextButton.addEventListener('touchend', event => handleButtonClick(nextButton, true, event), { passive: false });
        }

        function setupPageInput(pageInputId, fetchFunction) {
            const pageInput = document.getElementById(pageInputId);
            if (!pageInput) {
                return;
            }

            let requestInFlight = false;

            pageInput.addEventListener('change', async () => {
                if (requestInFlight) {
                    return;
                }

                const requestedPage = Number.parseInt(pageInput.value, 10);
                const maxPage = Number.parseInt(pageInput.max, 10) || 1;
                const page = Math.min(Math.max(1, requestedPage || 1), maxPage);

                requestInFlight = true;
                pageInput.disabled = true;
                try {
                    await fetchFunction(page);
                } finally {
                    pageInput.disabled = false;
                    requestInFlight = false;
                }
            });
        }

        function resolveRequestedPage(currentPage, increment, forcePageOne) {
            if (forcePageOne) {
                return 1;
            }

            if (Number.isInteger(increment)) {
                return Math.max(1, increment);
            }

            if (increment === true) {
                return currentPage + 1;
            }

            if (increment === false && currentPage > 1) {
                return currentPage - 1;
            }

            return currentPage;
        }

        function fetchActions(increment = null, forcePageOne = false, showLoading = false) {
            currentPageActions = resolveRequestedPage(currentPageActions, increment, forcePageOne);
            return fetchData('actions', currentPageActions, 'actionsTableBody', 'totalPagesActions', 'prevPageActions', 'nextPageActions', 'pageInputActions', 'searchActions', showLoading);
        }

        function fetchFavorites(increment = null, forcePageOne = false, showLoading = false) {
            currentPageFavorites = resolveRequestedPage(currentPageFavorites, increment, forcePageOne);
            return fetchData('favorites', currentPageFavorites, 'favoritesTableBody', 'totalPagesFavorites', 'prevPageFavorites', 'nextPageFavorites', 'pageInputFavorites', 'searchFavorites', showLoading);
        }

        function fetchAllSounds(increment = null, forcePageOne = false, showLoading = false) {
            currentPageAllSounds = resolveRequestedPage(currentPageAllSounds, increment, forcePageOne);
            return fetchData('all_sounds', currentPageAllSounds, 'allSoundsTableBody', 'totalPagesAllSounds', 'prevPageAllSounds', 'nextPageAllSounds', 'pageInputAllSounds', 'searchAllSounds', showLoading);
        }

        const fetchersByEndpoint = {
            actions: fetchActions,
            favorites: fetchFavorites,
            all_sounds: fetchAllSounds
        };

        function setupFilterControlDelegation() {
            Object.values(filterConfigs).forEach(config => {
                const container = document.getElementById(config.containerId);
                if (!container) {
                    return;
                }

                container.addEventListener('change', event => {
                    const select = event.target.closest('.filter-select');
                    if (!select) {
                        return;
                    }

                    const endpoint = select.dataset.endpoint;
                    const filterKey = select.dataset.filterKey;
                    if (!endpoint || !filterKey || !fetchersByEndpoint[endpoint]) {
                        return;
                    }

                    filterState[endpoint][filterKey] = select.value ? [select.value] : [];
                    const shouldShowLoading = (
                        (endpoint === 'all_sounds' && filterKey === 'list')
                        || (endpoint === 'favorites' && filterKey === 'user')
                    );
                    fetchersByEndpoint[endpoint](null, true, shouldShowLoading);
                });
            });
        }

        setupFilterControlDelegation();
        setupPagination('prevPageActions', 'nextPageActions', fetchActions);
        setupPagination('prevPageFavorites', 'nextPageFavorites', fetchFavorites);
        setupPagination('prevPageAllSounds', 'nextPageAllSounds', fetchAllSounds);
        setupPageInput('pageInputActions', fetchActions);
        setupPageInput('pageInputFavorites', fetchFavorites);
        setupPageInput('pageInputAllSounds', fetchAllSounds);

        const loginModal = document.getElementById('loginModal');
        const loginModalClose = document.getElementById('loginModalClose');
        const voiceMembersModal = document.getElementById('voiceMembersModal');
        const voiceMembersModalClose = document.getElementById('voiceMembersModalClose');
        const controlRoomVoiceButton = document.getElementById('controlRoomVoiceButton');

        function openLoginModal() {
            if (!loginModal) return;
            loginModal.classList.add('open');
            loginModal.setAttribute('aria-hidden', 'false');
        }

        function closeLoginModal() {
            if (!loginModal) return;
            loginModal.classList.remove('open');
            loginModal.setAttribute('aria-hidden', 'true');
        }

        if (loginModal && loginModalClose) {
            loginModalClose.addEventListener('click', closeLoginModal);
            loginModal.addEventListener('click', (event) => {
                if (event.target === loginModal) {
                    closeLoginModal();
                }
            });
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    closeLoginModal();
                }
            });
        }

        if (controlRoomVoiceButton) {
            controlRoomVoiceButton.addEventListener('click', openVoiceMembersModal);
        }

        const controlRoomVoiceMetric = document.getElementById('controlRoomVoiceMetric');
        const voiceMembersDropdown = document.getElementById('voiceMembersDropdown');
        let voiceDropdownHideTimer = null;

        function showVoiceDropdown() {
            if (voiceDropdownHideTimer) {
                clearTimeout(voiceDropdownHideTimer);
                voiceDropdownHideTimer = null;
            }
            const status = latestControlRoomStatus || {};
            if (!status.voice_connected) {
                return;
            }
            openVoiceMembersDropdown();
        }

        function hideVoiceDropdown() {
            if (voiceDropdownHideTimer) {
                clearTimeout(voiceDropdownHideTimer);
            }
            voiceDropdownHideTimer = window.setTimeout(() => {
                voiceDropdownHideTimer = null;
                closeVoiceMembersDropdown();
            }, 180);
        }

        if (controlRoomVoiceMetric && voiceMembersDropdown) {
            controlRoomVoiceMetric.addEventListener('mouseenter', showVoiceDropdown);
            controlRoomVoiceMetric.addEventListener('mouseleave', hideVoiceDropdown);
            voiceMembersDropdown.addEventListener('mouseenter', showVoiceDropdown);
            voiceMembersDropdown.addEventListener('mouseleave', hideVoiceDropdown);
        }

        if (voiceMembersModal && voiceMembersModalClose) {
            voiceMembersModalClose.addEventListener('click', closeVoiceMembersModal);
            voiceMembersModal.addEventListener('click', (event) => {
                if (event.target === voiceMembersModal) {
                    closeVoiceMembersModal();
                }
            });
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    closeVoiceMembersModal();
                }
            });
        }

        let lastPlayTouchHandledAt = 0;
        let lastWebControlTouchHandledAt = 0;
        let soundOptionsLongPressTimer = null;
        let suppressNextPlayActivationUntil = 0;
        let activeSoundId = null;
        let activeSoundEvents = [];
        let contextMenuSoundId = null;
        let contextMenuSoundIsFavorite = false;
        let contextMenuSoundIsSlap = false;

        function handleSoundOptionsPressStart(event) {
            if (event.pointerType === 'mouse' || event.button === 2) {
                return;
            }
            const row = event.target.closest('.sound-options-row');
            if (!row || !document.querySelector('.tables-grid')?.contains(row)) {
                return;
            }
            const soundId = row.dataset.soundId || row.querySelector('.play-button')?.dataset.soundId;
            if (!soundId || row.querySelector('.play-button')?.disabled) {
                return;
            }
            const touch = event.touches?.[0] || event.changedTouches?.[0];
            const rowRect = row.getBoundingClientRect();
            const clientX = touch?.clientX ?? event.clientX ?? rowRect.left + Math.min(rowRect.width / 2, 180);
            const clientY = touch?.clientY ?? event.clientY ?? rowRect.top + Math.min(rowRect.height / 2, 28);
            clearSoundOptionsLongPress();
            soundOptionsLongPressTimer = window.setTimeout(() => {
                soundOptionsLongPressTimer = null;
                suppressNextPlayActivationUntil = Date.now() + 900;
                openSoundRowContextMenuForRow(row, clientX, clientY, event);
            }, 650);
        }

        function clearSoundOptionsLongPress() {
            if (soundOptionsLongPressTimer) {
                window.clearTimeout(soundOptionsLongPressTimer);
                soundOptionsLongPressTimer = null;
            }
        }

        function setSoundRenameStatus(message, kind = '') {
            if (!soundRenameStatus) return;
            soundRenameStatus.textContent = message;
            soundRenameStatus.dataset.kind = kind;
        }

        function resizeSoundRenameInput() {
            if (!soundRenameInput) return;
            const textLength = (soundRenameInput.value || soundRenameInput.placeholder || '').length;
            const widthCh = Math.max(14, Math.min(textLength + 2, 36));
            soundRenameInput.style.width = `${widthCh}ch`;
        }

        function setSoundListStatus(message, kind = '') {
            if (!soundListStatus) return;
            soundListStatus.textContent = message;
            soundListStatus.dataset.kind = kind;
        }

        function setSoundSimilarStatus(message, kind = '') {
            if (!soundSimilarStatus) return;
            soundSimilarStatus.textContent = message;
            soundSimilarStatus.dataset.kind = kind;
        }

        function setSoundEventStatus(message, kind = '') {
            if (!soundEventStatus) return;
            soundEventStatus.textContent = message;
            soundEventStatus.dataset.kind = kind;
        }

        function normalizeSoundEventTarget(value) {
            return String(value || '').trim().toLocaleLowerCase();
        }

        function getSelectedSoundEvent() {
            return {
                event: soundEventTypeSelect?.value || 'join',
                targetUser: soundEventUserInput?.value || discordUser?.username || ''
            };
        }

        function findMatchingSoundEvent() {
            const selected = getSelectedSoundEvent();
            const normalizedTarget = normalizeSoundEventTarget(selected.targetUser);
            return activeSoundEvents.some(eventAssignment => (
                eventAssignment.event === selected.event
                && normalizeSoundEventTarget(eventAssignment.target_user) === normalizedTarget
            ));
        }

        function formatSoundEventSummary() {
            if (!activeSoundEvents.length) {
                return 'No events are currently set for this sound.';
            }

            return `Existing events: ${activeSoundEvents
                .map(eventAssignment => `${eventAssignment.target_user} ${eventAssignment.event}`)
                .join(', ')}.`;
        }

        function updateSoundEventActionState() {
            if (!soundEventSubmitButton) return;
            const hasExistingEvent = findMatchingSoundEvent();
            soundEventSubmitButton.textContent = hasExistingEvent ? 'Remove Event' : 'Add Event';
            soundEventSubmitButton.dataset.action = hasExistingEvent ? 'remove' : 'add';
        }

        function renderSoundEventUsers(users) {
            if (!soundEventUserInput) return;
            const selectedValue = soundEventUserInput.value || discordUser?.username || '';
            soundEventUserInput.innerHTML = '';

            const userOptions = Array.isArray(users) ? users : [];
            if (!userOptions.length) {
                const option = document.createElement('option');
                option.value = '';
                option.textContent = 'No users available';
                soundEventUserInput.appendChild(option);
                return;
            }

            userOptions.forEach(userOption => {
                const value = userOption.value || userOption.label || '';
                if (!value) return;
                const option = document.createElement('option');
                option.value = value;
                option.textContent = userOption.label || value;
                option.selected = value === selectedValue;
                soundEventUserInput.appendChild(option);
            });

            if (selectedValue && soundEventUserInput.value !== selectedValue) {
                const option = document.createElement('option');
                option.value = selectedValue;
                option.textContent = selectedValue;
                option.selected = true;
                soundEventUserInput.insertBefore(option, soundEventUserInput.firstChild);
            }
        }

        function openDialog(dialog) {
            if (typeof dialog?.showModal === 'function') {
                dialog.showModal();
            } else if (dialog) {
                dialog.setAttribute('open', '');
            }
        }

        function closeDialog(dialog) {
            if (typeof dialog?.close === 'function') {
                dialog.close();
            } else if (dialog) {
                dialog.removeAttribute('open');
            }
        }

        function closeSoundRenameModal() {
            closeDialog(soundRenameDialog);
        }

        function closeSoundListModal() {
            closeDialog(soundListDialog);
        }

        function closeSoundSimilarModal() {
            closeDialog(soundSimilarDialog);
        }

        function closeSoundEventModal() {
            closeDialog(soundEventDialog);
            activeSoundEvents = [];
        }

        async function loadSoundOptions(soundId) {
            const params = new URLSearchParams();
            appendGuildParam(params);
            const response = await fetch(`/api/sounds/${encodeURIComponent(soundId)}/options?${params.toString()}`);
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                if (response.status === 401 && payload.login_url) {
                    window.location.href = payload.login_url;
                    return null;
                }
                throw new Error(payload.error || 'Could not load sound options.');
            }
            return payload;
        }

        async function openSoundRenameModal(soundId) {
            activeSoundId = soundId;
            setSoundRenameStatus('Loading sound...', 'loading');
            if (soundRenameInput) {
                soundRenameInput.value = '';
                resizeSoundRenameInput();
            }
            openDialog(soundRenameDialog);

            try {
                const payload = await loadSoundOptions(soundId);
                if (!payload) return;
                const filename = payload.sound?.display_filename || '';
                const bareName = filename.replace(/\.mp3$/i, '');
                if (soundRenameTitle) {
                    soundRenameTitle.textContent = bareName || 'Rename sound';
                }
                if (soundRenameInput) {
                    soundRenameInput.value = bareName;
                    resizeSoundRenameInput();
                    soundRenameInput.focus();
                    soundRenameInput.select();
                }
                setSoundRenameStatus('Choose a new name for this sound.');
            } catch (error) {
                console.error('Sound rename options failed:', error);
                setSoundRenameStatus(error.message || 'Network error while loading sound.', 'error');
            }
        }

        async function openSoundListModal(soundId) {
            activeSoundId = soundId;
            setSoundListStatus('Loading lists...', 'loading');
            renderSoundLists([]);
            openDialog(soundListDialog);

            try {
                const payload = await loadSoundOptions(soundId);
                if (!payload) return;
                const filename = payload.sound?.display_filename || '';
                const bareName = filename.replace(/\.mp3$/i, '');
                if (soundListTitle) {
                    soundListTitle.textContent = bareName || 'Add to list';
                }
                renderSoundLists(payload.lists || []);
                setSoundListStatus(
                    soundListSelect?.value
                        ? 'This sound is already in the selected list.'
                        : 'Choose which list should include this sound.'
                );
            } catch (error) {
                console.error('Sound list options failed:', error);
                setSoundListStatus(error.message || 'Network error while loading lists.', 'error');
            }
        }

        function renderSoundLists(lists) {
            if (!soundListSelect) return;
            soundListSelect.innerHTML = '';
            const placeholder = document.createElement('option');
            placeholder.value = '';
            placeholder.textContent = lists.length ? 'Choose a list' : 'No lists available';
            soundListSelect.appendChild(placeholder);
            let selectedExistingList = false;
            lists.forEach(list => {
                const option = document.createElement('option');
                option.value = list.id;
                option.textContent = list.label || list.name;
                if (list.contains_sound && !selectedExistingList) {
                    option.selected = true;
                    selectedExistingList = true;
                }
                soundListSelect.appendChild(option);
            });
        }

        async function openSoundSimilarModal(soundId) {
            activeSoundId = soundId;
            setSoundSimilarStatus('Loading similar sounds...', 'loading');
            renderSimilarSounds([]);
            openDialog(soundSimilarDialog);

            try {
                const payload = await loadSoundOptions(soundId);
                if (!payload) return;
                const filename = payload.sound?.display_filename || '';
                const bareName = filename.replace(/\.mp3$/i, '');
                if (soundSimilarTitle) {
                    soundSimilarTitle.textContent = bareName || 'Play similar';
                }
                renderSimilarSounds(payload.similar_sounds || []);
                setSoundSimilarStatus(
                    payload.similar_sounds?.length
                        ? 'Choose a related sound to send to voice chat.'
                        : 'No similar sounds found.'
                );
            } catch (error) {
                console.error('Similar sound options failed:', error);
                renderSimilarSounds([]);
                setSoundSimilarStatus(error.message || 'Network error while loading similar sounds.', 'error');
            }
        }

        function renderSimilarSounds(similarSounds) {
            if (!soundSimilarList) return;
            if (!similarSounds.length) {
                soundSimilarList.innerHTML = '<p class="web-upload-empty">No similar sounds available.</p>';
                updateSimilarScrollbar();
                return;
            }

            const buttons = similarSounds.map(sound => {
                const button = document.createElement('button');
                button.type = 'button';
                button.className = 'sound-options-similar-button';
                button.dataset.soundId = sound.sound_id;

                const name = document.createElement('span');
                name.className = 'sound-options-similar-name';
                name.textContent = String(sound.display_filename || '').replace(/\.mp3$/i, '');

                const score = document.createElement('span');
                score.className = 'sound-options-score';
                score.textContent = `${Number(sound.score || 0)}%`;

                button.append(name, score);
                return button;
            });
            soundSimilarList.replaceChildren(...buttons);
            updateSimilarScrollbar();
        }

        function updateSimilarScrollbar() {
            const section = soundSimilarList?.closest('.sound-options-section');
            const scrollbar = section?.querySelector('.sound-options-similar-scrollbar');
            const thumb = scrollbar?.querySelector('.sound-options-similar-scrollbar-thumb');
            if (!soundSimilarList || !section || !thumb) return;

            const scrollHeight = soundSimilarList.scrollHeight;
            const clientHeight = soundSimilarList.clientHeight;
            const canScroll = scrollHeight > clientHeight + 1;
            section.classList.toggle('has-scrollbar', canScroll);
            if (!canScroll) {
                thumb.style.height = '0px';
                thumb.style.transform = 'translateY(0)';
                return;
            }

            const ratio = clientHeight / scrollHeight;
            const thumbHeight = Math.max(30, clientHeight * ratio);
            const maxThumbOffset = clientHeight - thumbHeight;
            const maxScrollTop = scrollHeight - clientHeight;
            const offset = maxScrollTop > 0
                ? (soundSimilarList.scrollTop / maxScrollTop) * maxThumbOffset
                : 0;
            thumb.style.height = `${thumbHeight}px`;
            thumb.style.transform = `translateY(${offset}px)`;
        }

        async function openSoundEventModal(soundId) {
            activeSoundId = soundId;
            setSoundEventStatus('Loading sound...', 'loading');
            openDialog(soundEventDialog);

            try {
                const payload = await loadSoundOptions(soundId);
                if (!payload) return;
                const filename = payload.sound?.display_filename || '';
                const bareName = filename.replace(/\.mp3$/i, '');
                if (soundEventTitle) {
                    soundEventTitle.textContent = bareName || 'Set event';
                }
                if (soundEventTypeSelect) {
                    soundEventTypeSelect.value = 'join';
                }
                renderSoundEventUsers(payload.users || []);
                activeSoundEvents = Array.isArray(payload.events) ? payload.events : [];
                updateSoundEventActionState();
                setSoundEventStatus(formatSoundEventSummary());
            } catch (error) {
                console.error('Sound event options failed:', error);
                activeSoundEvents = [];
                updateSoundEventActionState();
                setSoundEventStatus(error.message || 'Network error while loading sound.', 'error');
            }
        }

        async function postSoundOption(path, body = {}) {
            const response = await fetch(path, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    ...body,
                    guild_id: getSelectedGuildId() || undefined
                })
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                if (response.status === 401 && payload.login_url) {
                    window.location.href = payload.login_url;
                    return null;
                }
                throw new Error(payload.error || 'Request failed.');
            }
            return payload;
        }

        async function postPlaySound(soundId, playAction = 'play_request') {
            const response = await fetch('/api/play_sound', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    sound_id: soundId,
                    play_action: playAction,
                    guild_id: getSelectedGuildId() || undefined
                })
            });
            const payload = await response.json().catch(() => ({}));
            if (!response.ok) {
                if (response.status === 401 && payload.login_url) {
                    window.location.href = payload.login_url;
                    return null;
                }
                throw new Error(payload.error || 'Playback request failed.');
            }
            return payload;
        }

        async function handleSoundRename() {
            if (!activeSoundId || !soundRenameInput) return;
            const newName = soundRenameInput.value.trim();
            if (!newName) {
                setSoundRenameStatus('Enter a new sound name.', 'error');
                return;
            }
            soundRenameButton.disabled = true;
            try {
                const payload = await postSoundOption(`/api/sounds/${encodeURIComponent(activeSoundId)}/rename`, { new_name: newName });
                if (!payload) return;
                setSoundRenameStatus('Sound renamed.', 'success');
                fetchFavorites(null, true, true);
                fetchAllSounds(null, true, true);
                window.setTimeout(closeSoundRenameModal, 350);
            } catch (error) {
                setSoundRenameStatus(error.message, 'error');
            } finally {
                soundRenameButton.disabled = false;
            }
        }

        async function handleSoundAddToList() {
            if (!activeSoundId || !soundListSelect?.value) {
                setSoundListStatus('Choose a list first.', 'error');
                return;
            }
            soundAddToListButton.disabled = true;
            try {
                const payload = await postSoundOption(`/api/sounds/${encodeURIComponent(activeSoundId)}/lists`, {
                    list_id: soundListSelect.value
                });
                if (!payload) return;
                setSoundListStatus(payload.message || 'List updated.', payload.added ? 'success' : '');
                fetchAllSounds(null, false, true);
                window.setTimeout(closeSoundListModal, 500);
            } catch (error) {
                setSoundListStatus(error.message, 'error');
            } finally {
                soundAddToListButton.disabled = false;
            }
        }

        async function handleSoundEventSubmit() {
            if (!activeSoundId || !soundEventTypeSelect) return;
            const targetUser = soundEventUserInput?.value || '';
            if (!targetUser) {
                setSoundEventStatus('Choose a Discord user.', 'error');
                return;
            }
            soundEventSubmitButton.disabled = true;
            try {
                const payload = await postSoundOption(`/api/sounds/${encodeURIComponent(activeSoundId)}/events`, {
                    event: soundEventTypeSelect.value,
                    target_user: targetUser
                });
                if (!payload) return;
                setSoundEventStatus(payload.message || 'Event updated.', payload.added ? 'success' : '');
                const normalizedTarget = normalizeSoundEventTarget(payload.target_user);
                activeSoundEvents = activeSoundEvents.filter(eventAssignment => !(
                    eventAssignment.event === payload.event
                    && normalizeSoundEventTarget(eventAssignment.target_user) === normalizedTarget
                ));
                if (payload.added) {
                    activeSoundEvents.push({
                        target_user: payload.target_user,
                        event: payload.event
                    });
                }
                updateSoundEventActionState();
                window.setTimeout(closeSoundEventModal, 650);
            } catch (error) {
                setSoundEventStatus(error.message, 'error');
            } finally {
                soundEventSubmitButton.disabled = false;
            }
        }

        function closeSoundRowContextMenu() {
            if (!soundRowContextMenu) return;
            soundRowContextMenu.classList.remove('open');
            soundRowContextMenu.setAttribute('aria-hidden', 'true');
            contextMenuSoundId = null;
            contextMenuSoundIsFavorite = false;
            contextMenuSoundIsSlap = false;
        }

        function openSoundRowContextMenu(event) {
            const row = event.target.closest('.sound-options-row');
            if (!row || !document.querySelector('.tables-grid')?.contains(row)) {
                closeSoundRowContextMenu();
                return;
            }

            openSoundRowContextMenuForRow(row, event.clientX, event.clientY, event);
        }

        function openSoundRowContextMenuForRow(row, clientX, clientY, event = null) {
            const soundId = row.dataset.soundId || row.querySelector('.play-button')?.dataset.soundId;
            if (!soundId) {
                return;
            }

            event?.preventDefault?.();
            event?.stopPropagation?.();
            clearSoundOptionsLongPress();
            contextMenuSoundId = soundId;
            contextMenuSoundIsFavorite = row.dataset.favorite === 'true';
            contextMenuSoundIsSlap = row.dataset.slap === 'true';
            if (soundRowFavoriteOption) {
                soundRowFavoriteOption.textContent = contextMenuSoundIsFavorite ? 'Unfavorite' : 'Favorite';
            }
            if (soundRowSlapOption) {
                soundRowSlapOption.textContent = contextMenuSoundIsSlap ? 'Unmake slap' : 'Make slap';
            }

            if (!soundRowContextMenu) {
                if (!discordUser) {
                    openLoginModal();
                    return;
                }
                openSoundRenameModal(soundId);
                return;
            }

            const menuWidth = soundRowContextMenu.offsetWidth || 132;
            const menuHeight = soundRowContextMenu.offsetHeight || 176;
            const rowRect = row.getBoundingClientRect();
            const fallbackX = rowRect.left + Math.min(rowRect.width / 2, 180);
            const fallbackY = rowRect.top + Math.min(rowRect.height / 2, 28);
            const left = Math.min(clientX ?? fallbackX, window.innerWidth - menuWidth - 8);
            const top = Math.min(clientY ?? fallbackY, window.innerHeight - menuHeight - 8);

            soundRowContextMenu.style.left = `${Math.max(8, left)}px`;
            soundRowContextMenu.style.top = `${Math.max(8, top)}px`;
            soundRowContextMenu.classList.add('open');
            soundRowContextMenu.setAttribute('aria-hidden', 'false');
        }

        function handleSoundOptionsButtonActivation(event) {
            const button = event.target.closest('.sound-options-button');
            if (!button || !document.querySelector('.tables-grid')?.contains(button)) {
                return;
            }
            const row = button.closest('.sound-options-row');
            if (!row) {
                return;
            }
            const rect = button.getBoundingClientRect();
            openSoundRowContextMenuForRow(row, rect.left, rect.bottom + 6, event);
        }

        function handleSoundRowRenameOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }
            openSoundRenameModal(soundId);
        }

        function handleSoundRowAddToListOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }
            openSoundListModal(soundId);
        }

        function handleSoundRowSimilarOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }
            openSoundSimilarModal(soundId);
        }

        function handleSoundRowEventOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }
            openSoundEventModal(soundId);
        }

        async function handleSoundRowFavoriteOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }

            try {
                await postSoundOption(`/api/sounds/${encodeURIComponent(soundId)}/favorite`);
                fetchFavorites(null, true, true);
                fetchAllSounds(null, false, true);
            } catch (error) {
                console.error('Favorite failed:', error);
            }
        }

        async function handleSoundRowSlapOption() {
            const soundId = contextMenuSoundId;
            closeSoundRowContextMenu();
            if (!soundId) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }

            try {
                await postSoundOption(`/api/sounds/${encodeURIComponent(soundId)}/slap`);
                fetchFavorites(null, true, true);
                fetchAllSounds(null, false, true);
            } catch (error) {
                console.error('Slap toggle failed:', error);
            }
        }

        async function handleSimilarSoundPlay(event) {
            const button = event.target.closest('.sound-options-similar-button');
            if (!button || !soundSimilarList?.contains(button)) {
                return;
            }
            const soundId = button.dataset.soundId;
            if (!soundId || button.disabled) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }

            button.disabled = true;
            const originalNodes = Array.from(button.childNodes).map(node => node.cloneNode(true));
            const restoreButton = () => {
                button.disabled = false;
                button.replaceChildren(...originalNodes.map(node => node.cloneNode(true)));
            };
            try {
                await postPlaySound(soundId, 'play_similar_sound');
                button.textContent = 'Sent';
                setSoundSimilarStatus('Similar sound sent.', 'success');
                window.setTimeout(restoreButton, 1400);
            } catch (error) {
                button.textContent = 'Error';
                setSoundSimilarStatus(error.message || 'Could not send similar sound.', 'error');
                window.setTimeout(restoreButton, 1800);
            }
        }

        async function handlePlayButtonActivation(event) {
            clearSoundOptionsLongPress();
            const button = event.target.closest('.play-button');
            if (!button || !document.querySelector('.tables-grid')?.contains(button)) {
                return;
            }

            if (Date.now() < suppressNextPlayActivationUntil) {
                event.preventDefault();
                event.stopPropagation();
                return;
            }

            if (event.type === 'touchend') {
                event.preventDefault();
                lastPlayTouchHandledAt = Date.now();
            } else if (event.type === 'click' && Date.now() - lastPlayTouchHandledAt < 700) {
                return;
            }

            const soundId = button.getAttribute('data-sound-id');
            if (!soundId || button.disabled) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }

            button.disabled = true;
            button.textContent = '⏳';

            try {
                await postPlaySound(soundId);
                const readiness = getPlaybackReadinessLabel();
                const isReady = !readiness || (latestControlRoomStatus?.online && latestControlRoomStatus?.voice_connected);
                button.textContent = isReady ? '✓' : '!';
                button.title = isReady ? 'Sent' : `Sent, but ${readiness}`;
                button.classList.add(isReady ? 'sent' : 'warn');
                setTimeout(() => {
                    applyPlayButtonState(button);
                    button.classList.remove('sent');
                    button.classList.remove('warn');
                }, 2000);
            } catch (error) {
                console.error('Network error:', error);
                button.textContent = '✗';
                button.title = 'Error';
                button.classList.add('error');
                setTimeout(() => {
                    applyPlayButtonState(button);
                    button.classList.remove('error');
                }, 2000);
            }
        }

        async function handleWebControlActivation(event) {
            const button = event.target.closest('.web-control-button');
            if (!button) {
                return;
            }

            if (event.type === 'touchend') {
                event.preventDefault();
                lastWebControlTouchHandledAt = Date.now();
            } else if (event.type === 'click' && Date.now() - lastWebControlTouchHandledAt < 700) {
                return;
            }

            const action = button.getAttribute('data-control-action');
            if (!action || button.disabled) return;
            if (!discordUser) {
                openLoginModal();
                return;
            }
            if (action === 'tts') {
                openTtsModal();
                return;
            }

            button.disabled = true;
            button.textContent = '⏳';

            try {
                const response = await fetch('/api/web_control', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        action,
                        guild_id: getSelectedGuildId() || undefined
                    })
                });

                if (response.ok) {
                    button.textContent = '✓';
                    button.title = 'Sent';
                    button.classList.add('sent');
                    if (action === 'toggle_mute') {
                        updateWebControlMuteState(!webControlMuteIsMuted);
                    }
                    setTimeout(() => {
                        applyWebControlButtonState(button);
                        button.classList.remove('sent');
                    }, 2000);
                } else {
                    const payload = await response.json().catch(() => ({}));
                    if (response.status === 401 && payload.login_url) {
                        window.location.href = payload.login_url;
                        return;
                    }
                    button.textContent = '✗';
                    button.title = 'Error';
                    button.classList.add('error');
                    setTimeout(() => {
                        applyWebControlButtonState(button);
                        button.classList.remove('error');
                    }, 2000);
                }
            } catch (error) {
                console.error('Network error:', error);
                button.textContent = '✗';
                button.title = 'Error';
                button.classList.add('error');
                setTimeout(() => {
                    applyWebControlButtonState(button);
                    button.classList.remove('error');
                }, 2000);
            }
        }

        const tablesGrid = document.querySelector('.tables-grid');
        tablesGrid.addEventListener('click', handleSoundOptionsButtonActivation);
        tablesGrid.addEventListener('click', handlePlayButtonActivation);
        tablesGrid.addEventListener('touchend', handlePlayButtonActivation, { passive: false });
        tablesGrid.addEventListener('contextmenu', openSoundRowContextMenu);
        tablesGrid.addEventListener('touchstart', handleSoundOptionsPressStart, { passive: true });
        tablesGrid.addEventListener('mouseup', clearSoundOptionsLongPress);
        tablesGrid.addEventListener('mouseleave', clearSoundOptionsLongPress);
        tablesGrid.addEventListener('touchmove', clearSoundOptionsLongPress, { passive: true });
        tablesGrid.addEventListener('touchcancel', clearSoundOptionsLongPress);
        document.addEventListener('click', handleWebControlActivation);
        document.addEventListener('touchend', handleWebControlActivation, { passive: false });

        const webUploadForm = document.getElementById('webUploadForm');
        const webUploadDialog = document.getElementById('webUploadDialog');
        const webUploadOpenButton = document.getElementById('webUploadOpenButton');
        const webUploadCloseButton = document.getElementById('webUploadCloseButton');
        const webUploadCancelButton = document.getElementById('webUploadCancelButton');
        const webUploadStatus = document.getElementById('webUploadStatus');
        const webUploadSubmit = document.getElementById('webUploadSubmit');
        const webUploadInboxDialog = document.getElementById('webUploadInboxDialog');
        const webUploadInboxOpenButton = document.getElementById('webUploadInboxOpenButton');
        const webUploadInboxCloseButton = document.getElementById('webUploadInboxCloseButton');
        const webUploadInbox = document.getElementById('webUploadInbox');
        const webUploadFile = document.getElementById('webUploadFile');
        const webUploadFileName = document.getElementById('webUploadFileName');
        const webUploadInboxPagination = document.getElementById('webUploadInboxPagination');
        const webUploadInboxPrev = document.getElementById('webUploadInboxPrev');
        const webUploadInboxNext = document.getElementById('webUploadInboxNext');
        const webUploadInboxPage = document.getElementById('webUploadInboxPage');
        const webUploadQueueList = document.getElementById('webUploadQueueList');
        const webUploadQueueCount = document.getElementById('webUploadQueueCount');
        const webTtsForm = document.getElementById('webTtsForm');
        const webTtsDialog = document.getElementById('webTtsDialog');
        const webTtsCloseButton = document.getElementById('webTtsCloseButton');
        const webTtsCancelButton = document.getElementById('webTtsCancelButton');
        const webTtsStatus = document.getElementById('webTtsStatus');
        const webTtsSubmit = document.getElementById('webTtsSubmit');
        const webTtsMessage = document.getElementById('webTtsMessage');
        const webTtsProfile = document.getElementById('webTtsProfile');
        const webTtsEnhanceButton = document.getElementById('webTtsEnhanceButton');
        const soundRenameDialog = document.getElementById('soundRenameDialog');
        const soundRenameForm = document.getElementById('soundRenameForm');
        const soundRenameTitle = document.getElementById('soundRenameTitle');
        const soundRenameStatus = document.getElementById('soundRenameStatus');
        const soundRenameCloseButton = document.getElementById('soundRenameCloseButton');
        const soundRenameInput = document.getElementById('soundRenameInput');
        const soundRenameButton = document.getElementById('soundRenameButton');
        const soundListDialog = document.getElementById('soundListDialog');
        const soundListForm = document.getElementById('soundListForm');
        const soundListTitle = document.getElementById('soundListTitle');
        const soundListStatus = document.getElementById('soundListStatus');
        const soundListCloseButton = document.getElementById('soundListCloseButton');
        const soundListSelect = document.getElementById('soundListSelect');
        const soundAddToListButton = document.getElementById('soundAddToListButton');
        const soundSimilarDialog = document.getElementById('soundSimilarDialog');
        const soundSimilarForm = document.getElementById('soundSimilarForm');
        const soundSimilarTitle = document.getElementById('soundSimilarTitle');
        const soundSimilarStatus = document.getElementById('soundSimilarStatus');
        const soundSimilarCloseButton = document.getElementById('soundSimilarCloseButton');
        const soundSimilarList = document.getElementById('soundSimilarList');
        const soundEventDialog = document.getElementById('soundEventDialog');
        const soundEventForm = document.getElementById('soundEventForm');
        const soundEventTitle = document.getElementById('soundEventTitle');
        const soundEventStatus = document.getElementById('soundEventStatus');
        const soundEventCloseButton = document.getElementById('soundEventCloseButton');
        const soundEventCancelButton = document.getElementById('soundEventCancelButton');
        const soundEventTypeSelect = document.getElementById('soundEventTypeSelect');
        const soundEventUserInput = document.getElementById('soundEventUserInput');
        const soundEventSubmitButton = document.getElementById('soundEventSubmitButton');
        const soundRowContextMenu = document.getElementById('soundRowContextMenu');
        const soundRowRenameOption = document.getElementById('soundRowRenameOption');
        const soundRowAddToListOption = document.getElementById('soundRowAddToListOption');
        const soundRowSimilarOption = document.getElementById('soundRowSimilarOption');
        const soundRowEventOption = document.getElementById('soundRowEventOption');
        const soundRowFavoriteOption = document.getElementById('soundRowFavoriteOption');
        const soundRowSlapOption = document.getElementById('soundRowSlapOption');
        const uploadQueueItems = new Map();
        let uploadInboxPage = 1;
        let uploadInboxTotalPages = 1;
        let lastUploadOpenTouchHandledAt = 0;
        let ttsEnhancedMessageValue = '';

        function setUploadStatus(message, kind = '') {
            if (!webUploadStatus) return;
            webUploadStatus.textContent = message;
            webUploadStatus.dataset.kind = kind;
        }

        function setTtsStatus(message, kind = '') {
            if (!webTtsStatus) return;
            webTtsStatus.textContent = message;
            webTtsStatus.dataset.kind = kind;
        }

        function updateTtsEnhanceButtonState() {
            if (!webTtsEnhanceButton) return;
            const currentMessage = webTtsMessage?.value?.trim() || '';
            const alreadyEnhanced = Boolean(currentMessage && currentMessage === ttsEnhancedMessageValue);
            webTtsEnhanceButton.disabled = alreadyEnhanced;
            webTtsEnhanceButton.textContent = alreadyEnhanced ? 'Enhanced' : 'Enhance';
        }

        function openTtsModal() {
            if (!discordUser) {
                openLoginModal();
                return;
            }
            updateTtsEnhanceButtonState();
            setTtsStatus('Pick a voice or language, then send the message to the bot.');
            if (typeof webTtsDialog?.showModal === 'function') {
                webTtsDialog.showModal();
            } else if (webTtsDialog) {
                webTtsDialog.setAttribute('open', '');
            }
            webTtsMessage?.focus();
        }

        function closeTtsModal() {
            if (typeof webTtsDialog?.close === 'function') {
                webTtsDialog.close();
            } else if (webTtsDialog) {
                webTtsDialog.removeAttribute('open');
            }
        }

        async function handleWebTtsSubmit(event) {
            event.preventDefault();
            if (!discordUser) {
                openLoginModal();
                return;
            }

            const message = webTtsMessage?.value?.trim() || '';
            const profile = webTtsProfile?.value || 'ventura';
            if (!message) {
                setTtsStatus('Please enter a message.', 'error');
                webTtsMessage?.focus();
                return;
            }

            if (webTtsSubmit) {
                webTtsSubmit.disabled = true;
                webTtsSubmit.textContent = 'Sending...';
            }
            setTtsStatus('Sending TTS request...', 'loading');

            try {
                const response = await fetch('/api/web_control', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        action: 'tts',
                        message: message.slice(0, 500),
                        profile,
                        guild_id: getSelectedGuildId() || undefined
                    })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (response.status === 401 && payload.login_url) {
                        window.location.href = payload.login_url;
                        return;
                    }
                    setTtsStatus(payload.error || 'TTS request failed.', 'error');
                    return;
                }

                setTtsStatus('TTS request sent.', 'success');
                webTtsForm?.reset();
                ttsEnhancedMessageValue = '';
                updateTtsEnhanceButtonState();
                setTimeout(closeTtsModal, 650);
            } catch (error) {
                console.error('TTS request failed:', error);
                setTtsStatus('Network error while sending TTS.', 'error');
            } finally {
                if (webTtsSubmit) {
                    webTtsSubmit.disabled = false;
                    webTtsSubmit.textContent = 'Send';
                }
            }
        }

        async function handleWebTtsEnhance() {
            if (!discordUser) {
                openLoginModal();
                return;
            }

            const message = webTtsMessage?.value?.trim() || '';
            if (!message) {
                setTtsStatus('Please enter a message to enhance.', 'error');
                webTtsMessage?.focus();
                return;
            }
            if (message === ttsEnhancedMessageValue) {
                setTtsStatus('This message has already been enhanced. Edit it to enhance again.', 'error');
                webTtsMessage?.focus();
                updateTtsEnhanceButtonState();
                return;
            }

            if (webTtsEnhanceButton) {
                webTtsEnhanceButton.disabled = true;
                webTtsEnhanceButton.textContent = 'Enhancing...';
            }
            setTtsStatus('Adding ElevenLabs style tags...', 'loading');

            try {
                const response = await fetch('/api/tts/enhance', {
                    method: 'POST',
                    headers: {
                        'Content-Type': 'application/json',
                    },
                    body: JSON.stringify({
                        message: message.slice(0, 500)
                    })
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (response.status === 401 && payload.login_url) {
                        window.location.href = payload.login_url;
                        return;
                    }
                    setTtsStatus(payload.error || 'TTS enhancement failed.', 'error');
                    return;
                }
                if (webTtsMessage && payload.message) {
                    webTtsMessage.value = payload.message.slice(0, 500);
                    ttsEnhancedMessageValue = webTtsMessage.value.trim();
                    webTtsMessage.focus();
                }
                updateTtsEnhanceButtonState();
                setTtsStatus('Message enhanced. Review it, then send.', 'success');
            } catch (error) {
                console.error('TTS enhancement failed:', error);
                setTtsStatus('Network error while enhancing TTS.', 'error');
            } finally {
                if (webTtsEnhanceButton) {
                    updateTtsEnhanceButtonState();
                }
            }
        }

        function openUploadModal() {
            if (!discordUser) {
                openLoginModal();
                return;
            }
            if (typeof webUploadDialog?.showModal === 'function') {
                webUploadDialog.showModal();
            } else if (webUploadDialog) {
                webUploadDialog.setAttribute('open', '');
            }
        }

        function handleUploadOpenActivation(event) {
            if (event.type === 'touchend') {
                event.preventDefault();
                lastUploadOpenTouchHandledAt = Date.now();
            } else if (event.type === 'click' && Date.now() - lastUploadOpenTouchHandledAt < 700) {
                return;
            }
            openUploadModal();
        }

        function closeUploadModal() {
            if (typeof webUploadDialog?.close === 'function') {
                webUploadDialog.close();
            } else if (webUploadDialog) {
                webUploadDialog.removeAttribute('open');
            }
        }

        function openUploadInboxModal() {
            if (!discordUser) {
                openLoginModal();
                return;
            }
            if (!webUserIsAdmin) {
                return;
            }
            openDialog(webUploadInboxDialog);
            loadUploadInbox();
        }

        function closeUploadInboxModal() {
            closeDialog(webUploadInboxDialog);
        }

        async function handleWebUploadSubmit(event) {
            event.preventDefault();
            if (!discordUser) {
                openLoginModal();
                return;
            }

            const fileInput = document.getElementById('webUploadFile');
            const urlInput = document.getElementById('webUploadUrl');
            if (!fileInput?.files?.length && !urlInput?.value?.trim()) {
                setUploadStatus('Please provide a URL or upload an MP3 file.', 'error');
                return;
            }

            const formData = new FormData(webUploadForm);
            const queueId = `pending-${Date.now()}-${Math.random().toString(16).slice(2)}`;
            const queueLabel = getUploadQueueLabel(formData, fileInput, urlInput);
            addUploadQueueItem(queueId, queueLabel, 'sending', 'Sending');
            webUploadForm.reset();
            updateUploadFileLabel();
            const guildId = getSelectedGuildId();
            if (guildId) {
                formData.set('guild_id', guildId);
            }

            if (webUploadSubmit) {
                webUploadSubmit.disabled = true;
                webUploadSubmit.textContent = 'Queueing...';
            }
            setUploadStatus('Added to processing queue. You can add another sound now.', 'loading');

            try {
                const response = await fetch('/api/upload_sound', {
                    method: 'POST',
                    body: formData
                });
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    if (response.status === 401 && payload.login_url) {
                        window.location.href = payload.login_url;
                        return;
                    }
                    updateUploadQueueItem(queueId, 'error', payload.error || 'Upload failed.');
                    setUploadStatus(payload.error || 'Upload failed.', 'error');
                    return;
                }

                if (payload.job_id) {
                    replaceUploadQueueId(queueId, payload.job_id);
                    updateUploadQueueItem(payload.job_id, 'processing', 'Processing');
                    setUploadStatus('Processing in the background. You can add another sound.', 'loading');
                    pollUploadJob(payload.job_id);
                } else {
                    handleCompletedUpload(payload, queueId);
                }
            } catch (error) {
                console.error('Upload failed:', error);
                updateUploadQueueItem(queueId, 'error', 'Network error');
                setUploadStatus('Network error while uploading.', 'error');
            } finally {
                if (webUploadSubmit) {
                    webUploadSubmit.disabled = false;
                    webUploadSubmit.textContent = 'Upload';
                }
            }
        }

        async function pollUploadJob(jobId) {
            try {
                const response = await fetch(`/api/upload_sound/${encodeURIComponent(jobId)}`);
                const payload = await response.json().catch(() => ({}));
                if (!response.ok) {
                    updateUploadQueueItem(jobId, 'error', payload.error || 'Could not check upload status.');
                    setUploadStatus(payload.error || 'Could not check upload status.', 'error');
                    return;
                }
                if (payload.status === 'approved') {
                    handleCompletedUpload(payload, jobId);
                    return;
                }
                if (payload.status === 'error') {
                    updateUploadQueueItem(jobId, 'error', payload.error || 'Upload failed.');
                    setUploadStatus(payload.error || 'Upload failed.', 'error');
                    return;
                }
                updateUploadQueueItem(jobId, 'processing', 'Processing');
                setUploadStatus('Processing audio in the background...', 'loading');
                window.setTimeout(() => pollUploadJob(jobId), 1200);
            } catch (error) {
                console.error('Upload status failed:', error);
                updateUploadQueueItem(jobId, 'error', 'Status check failed');
                setUploadStatus('Network error while checking upload status.', 'error');
            }
        }

        function handleCompletedUpload(payload, queueId = null) {
            if (queueId) {
                updateUploadQueueItem(queueId, 'approved', payload.filename || 'Approved');
            }
            setUploadStatus(`Approved: ${payload.filename}`, 'success');
            fetchAllSounds(null, true, true);
            if (webUserIsAdmin) {
                uploadInboxPage = 1;
                loadUploadInbox();
            }
        }

        function getUploadQueueLabel(formData, fileInput, urlInput) {
            const customName = String(formData.get('custom_name') || '').trim();
            if (customName) {
                return customName;
            }
            const fileName = fileInput?.files?.[0]?.name;
            if (fileName) {
                return fileName;
            }
            try {
                const parsedUrl = new URL(urlInput?.value?.trim() || '');
                return parsedUrl.pathname.split('/').filter(Boolean).pop() || parsedUrl.hostname;
            } catch (error) {
                return 'URL upload';
            }
        }

        function addUploadQueueItem(queueId, label, status, statusText) {
            uploadQueueItems.set(queueId, { label, status, statusText });
            renderUploadQueue();
        }

        function replaceUploadQueueId(oldQueueId, newQueueId) {
            if (!uploadQueueItems.has(oldQueueId)) return;
            uploadQueueItems.set(newQueueId, uploadQueueItems.get(oldQueueId));
            uploadQueueItems.delete(oldQueueId);
            renderUploadQueue();
        }

        function updateUploadQueueItem(queueId, status, statusText) {
            const existing = uploadQueueItems.get(queueId);
            if (!existing) return;
            uploadQueueItems.set(queueId, { ...existing, status, statusText });
            renderUploadQueue();
        }

        function renderUploadQueue() {
            if (!webUploadQueueList) return;
            const items = Array.from(uploadQueueItems.values()).reverse();
            if (webUploadQueueCount) {
                webUploadQueueCount.textContent = String(items.length);
            }
            if (!items.length) {
                webUploadQueueList.innerHTML = '<p class="web-upload-empty">No uploads processing.</p>';
                return;
            }

            const list = document.createElement('div');
            list.className = 'web-upload-queue-items';
            items.forEach(item => {
                const row = document.createElement('article');
                row.className = `web-upload-queue-item status-${item.status}`;

                const dot = document.createElement('span');
                dot.className = 'web-upload-queue-dot';
                dot.setAttribute('aria-hidden', 'true');

                const copy = document.createElement('div');
                copy.className = 'web-upload-queue-copy';
                const title = document.createElement('strong');
                title.textContent = item.label || 'Upload';
                const sub = document.createElement('span');
                sub.textContent = item.statusText || item.status;
                copy.appendChild(title);
                copy.appendChild(sub);

                row.appendChild(dot);
                row.appendChild(copy);
                list.appendChild(row);
            });
            webUploadQueueList.replaceChildren(list);
        }

        async function loadUploadInbox(page = uploadInboxPage) {
            if (!webUserIsAdmin || !webUploadInbox) {
                return;
            }
            const params = new URLSearchParams({ limit: '8', page: String(page) });
            appendGuildParam(params);
            try {
                const response = await fetch(`/api/uploads?${params.toString()}`);
                const payload = await response.json();
                if (!response.ok) {
                    webUploadInbox.innerHTML = '<p class="web-upload-empty">Could not load uploads.</p>';
                    return;
                }
                uploadInboxPage = payload.page || 1;
                uploadInboxTotalPages = payload.total_pages || 1;
                updateUploadInboxBadge(payload.unreviewed_count || 0);
                renderUploadInbox(payload.uploads || []);
                renderUploadInboxPagination();
            } catch (error) {
                console.error('Error loading uploads:', error);
                webUploadInbox.innerHTML = '<p class="web-upload-empty">Could not load uploads.</p>';
            }
        }

        function updateUploadInboxBadge(unreviewedCount) {
            if (!webUploadInboxOpenButton) return;
            const count = Number(unreviewedCount) || 0;
            const hasUnreviewed = count > 0;
            webUploadInboxOpenButton.classList.toggle('has-unreviewed', hasUnreviewed);
            webUploadInboxOpenButton.textContent = hasUnreviewed ? '!' : '\u2709\uFE0E';
            webUploadInboxOpenButton.setAttribute(
                'aria-label',
                hasUnreviewed
                    ? `Open moderation inbox, ${count} unreviewed upload${count === 1 ? '' : 's'}`
                    : 'Open moderation inbox'
            );
            webUploadInboxOpenButton.title = hasUnreviewed
                ? `${count} unreviewed upload${count === 1 ? '' : 's'}`
                : 'Moderation inbox';
        }

        function renderUploadInbox(uploads) {
            if (!webUploadInbox) return;
            if (!uploads.length) {
                webUploadInbox.innerHTML = '<p class="web-upload-empty">No web uploads yet.</p>';
                return;
            }

            const list = document.createElement('div');
            list.className = 'web-upload-list';
            uploads.forEach(upload => {
                const row = document.createElement('article');
                row.className = `web-upload-item status-${upload.status || 'approved'}`;
                const isReviewed = Boolean(upload.moderated_at || upload.moderator_username);

                const meta = document.createElement('div');
                meta.className = 'web-upload-item-meta';
                const title = document.createElement('strong');
                title.textContent = (upload.filename || '').replace('.mp3', '');
                const sub = document.createElement('span');
                const reviewLabel = isReviewed ? (upload.status || 'approved') : 'unreviewed';
                sub.textContent = `${reviewLabel} by ${upload.uploaded_by_username || 'unknown'} · ${formatTimeAgo(upload.created_at)}`;
                meta.appendChild(title);
                meta.appendChild(sub);

                const actions = document.createElement('div');
                actions.className = 'web-upload-item-actions';
                ['approved', 'rejected'].forEach(status => {
                    const button = document.createElement('button');
                    button.type = 'button';
                    button.className = 'web-upload-moderate';
                    button.textContent = status === 'approved' ? 'Approve' : 'Reject';
                    button.disabled = isReviewed && upload.status === status;
                    button.dataset.uploadId = upload.id;
                    button.dataset.status = status;
                    actions.appendChild(button);
                });

                row.appendChild(meta);
                row.appendChild(actions);
                list.appendChild(row);
            });
            webUploadInbox.replaceChildren(list);
        }

        function renderUploadInboxPagination() {
            if (!webUploadInboxPagination || !webUploadInboxPage) return;
            webUploadInboxPagination.hidden = uploadInboxTotalPages <= 1;
            webUploadInboxPage.textContent = `${uploadInboxPage} / ${uploadInboxTotalPages}`;
            if (webUploadInboxPrev) {
                webUploadInboxPrev.disabled = uploadInboxPage <= 1;
            }
            if (webUploadInboxNext) {
                webUploadInboxNext.disabled = uploadInboxPage >= uploadInboxTotalPages;
            }
        }

        function updateUploadFileLabel() {
            if (!webUploadFileName || !webUploadFile) return;
            webUploadFileName.textContent = webUploadFile.files?.[0]?.name || 'No file selected';
        }

        async function handleUploadModeration(event) {
            const button = event.target.closest('.web-upload-moderate');
            if (!button) return;
            const uploadId = button.dataset.uploadId;
            const status = button.dataset.status;
            if (!uploadId || !status) return;

            button.disabled = true;
            try {
                const response = await fetch(`/api/uploads/${uploadId}/moderation`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ status })
                });
                if (response.ok) {
                    await loadUploadInbox(uploadInboxPage);
                    fetchAllSounds(null, true, true);
                } else {
                    button.disabled = false;
                }
            } catch (error) {
                console.error('Moderation failed:', error);
                button.disabled = false;
            }
        }

        if (webUploadForm) {
            webUploadForm.addEventListener('submit', handleWebUploadSubmit);
        }
        if (webUploadOpenButton) {
            webUploadOpenButton.addEventListener('click', handleUploadOpenActivation);
            webUploadOpenButton.addEventListener('touchend', handleUploadOpenActivation, { passive: false });
        }
        if (webUploadInboxOpenButton) {
            webUploadInboxOpenButton.addEventListener('click', openUploadInboxModal);
        }
        if (webUploadInboxCloseButton) {
            webUploadInboxCloseButton.addEventListener('click', closeUploadInboxModal);
        }
        if (webUploadCloseButton) {
            webUploadCloseButton.addEventListener('click', closeUploadModal);
        }
        if (webUploadCancelButton) {
            webUploadCancelButton.addEventListener('click', closeUploadModal);
        }
        if (webTtsForm) {
            webTtsForm.addEventListener('submit', handleWebTtsSubmit);
        }
        if (webTtsCloseButton) {
            webTtsCloseButton.addEventListener('click', closeTtsModal);
        }
        if (webTtsCancelButton) {
            webTtsCancelButton.addEventListener('click', closeTtsModal);
        }
        if (webTtsMessage) {
            webTtsMessage.addEventListener('input', () => {
                updateTtsEnhanceButtonState();
            });
        }
        if (webTtsEnhanceButton) {
            webTtsEnhanceButton.addEventListener('click', handleWebTtsEnhance);
        }
        if (soundRenameCloseButton) {
            soundRenameCloseButton.addEventListener('click', closeSoundRenameModal);
        }
        if (soundRenameButton) {
            soundRenameButton.addEventListener('click', handleSoundRename);
        }
        if (soundRenameInput) {
            soundRenameInput.addEventListener('input', resizeSoundRenameInput);
            resizeSoundRenameInput();
        }
        if (soundListCloseButton) {
            soundListCloseButton.addEventListener('click', closeSoundListModal);
        }
        if (soundAddToListButton) {
            soundAddToListButton.addEventListener('click', handleSoundAddToList);
        }
        if (soundSimilarCloseButton) {
            soundSimilarCloseButton.addEventListener('click', closeSoundSimilarModal);
        }
        if (soundSimilarList) {
            soundSimilarList.addEventListener('click', handleSimilarSoundPlay);
            soundSimilarList.addEventListener('scroll', updateSimilarScrollbar, { passive: true });
        }
        if (soundEventCloseButton) {
            soundEventCloseButton.addEventListener('click', closeSoundEventModal);
        }
        if (soundEventCancelButton) {
            soundEventCancelButton.addEventListener('click', closeSoundEventModal);
        }
        if (soundRowRenameOption) {
            soundRowRenameOption.addEventListener('click', handleSoundRowRenameOption);
        }
        if (soundRowAddToListOption) {
            soundRowAddToListOption.addEventListener('click', handleSoundRowAddToListOption);
        }
        if (soundRowSimilarOption) {
            soundRowSimilarOption.addEventListener('click', handleSoundRowSimilarOption);
        }
        if (soundRowEventOption) {
            soundRowEventOption.addEventListener('click', handleSoundRowEventOption);
        }
        if (soundRowFavoriteOption) {
            soundRowFavoriteOption.addEventListener('click', handleSoundRowFavoriteOption);
        }
        if (soundRowSlapOption) {
            soundRowSlapOption.addEventListener('click', handleSoundRowSlapOption);
        }
        if (soundRowContextMenu) {
            soundRowContextMenu.addEventListener('click', event => event.stopPropagation());
            document.addEventListener('click', closeSoundRowContextMenu);
            document.addEventListener('scroll', closeSoundRowContextMenu, true);
            document.addEventListener('keydown', (event) => {
                if (event.key === 'Escape') {
                    closeSoundRowContextMenu();
                }
            });
        }
        if (soundRenameForm) {
            soundRenameForm.addEventListener('submit', event => {
                event.preventDefault();
                handleSoundRename();
            });
        }
        if (soundListForm) {
            soundListForm.addEventListener('submit', event => {
                event.preventDefault();
                handleSoundAddToList();
            });
        }
        if (soundSimilarForm) {
            soundSimilarForm.addEventListener('submit', event => {
                event.preventDefault();
            });
        }
        if (soundEventForm) {
            soundEventForm.addEventListener('submit', event => {
                event.preventDefault();
                handleSoundEventSubmit();
            });
        }
        if (soundEventTypeSelect) {
            soundEventTypeSelect.addEventListener('change', () => {
                updateSoundEventActionState();
                setSoundEventStatus(formatSoundEventSummary());
            });
        }
        if (soundEventUserInput) {
            soundEventUserInput.addEventListener('change', () => {
                updateSoundEventActionState();
                setSoundEventStatus(formatSoundEventSummary());
            });
        }
        if (soundRenameDialog) {
            soundRenameDialog.addEventListener('click', (event) => {
                if (event.target === soundRenameDialog) {
                    closeSoundRenameModal();
                }
            });
        }
        if (soundListDialog) {
            soundListDialog.addEventListener('click', (event) => {
                if (event.target === soundListDialog) {
                    closeSoundListModal();
                }
            });
        }
        if (soundSimilarDialog) {
            soundSimilarDialog.addEventListener('click', (event) => {
                if (event.target === soundSimilarDialog) {
                    closeSoundSimilarModal();
                }
            });
        }
        if (soundEventDialog) {
            soundEventDialog.addEventListener('click', (event) => {
                if (event.target === soundEventDialog) {
                    closeSoundEventModal();
                }
            });
        }
        if (webTtsDialog) {
            webTtsDialog.addEventListener('click', (event) => {
                if (event.target === webTtsDialog) {
                    closeTtsModal();
                }
            });
        }
        if (webUploadDialog) {
            webUploadDialog.addEventListener('click', (event) => {
                if (event.target === webUploadDialog) {
                    closeUploadModal();
                }
            });
        }
        if (webUploadInboxDialog) {
            webUploadInboxDialog.addEventListener('click', (event) => {
                if (event.target === webUploadInboxDialog) {
                    closeUploadInboxModal();
                }
            });
        }
        if (webUploadInbox) {
            webUploadInbox.addEventListener('click', handleUploadModeration);
        }
        if (webUploadFile) {
            webUploadFile.addEventListener('change', updateUploadFileLabel);
        }
        if (webUploadInboxPrev) {
            webUploadInboxPrev.addEventListener('click', () => {
                if (uploadInboxPage > 1) {
                    loadUploadInbox(uploadInboxPage - 1);
                }
            });
        }
        if (webUploadInboxNext) {
            webUploadInboxNext.addEventListener('click', () => {
                if (uploadInboxPage < uploadInboxTotalPages) {
                    loadUploadInbox(uploadInboxPage + 1);
                }
            });
        }
        if (new URLSearchParams(window.location.search).get('upload') === '1') {
            openUploadModal();
        }

        if (guildSelector) {
            guildSelector.addEventListener('change', () => {
                currentPageActions = 1;
                currentPageFavorites = 1;
                currentPageAllSounds = 1;
                lastFetchedData.actions = [];
                lastFetchedData.favorites = [];
                lastFetchedData.all_sounds = [];
                fetchActions(null, true, true);
                fetchFavorites(null, true, true);
                fetchAllSounds(null, true, true);
                refreshWebControlState();
                refreshControlRoomStatus();
                loadUploadInbox();
            });
        }

        function setupBackendSearch(inputId, fetchFunction) {
            const searchInput = document.getElementById(inputId);
            if (!searchInput) {
                return;
            }
            const clearButton = document.querySelector(`[data-search-target="${inputId}"]`);
            let debounceTimer;
            const updateClearButton = () => {
                clearButton?.classList.toggle('visible', Boolean(searchInput.value.trim()));
            };

            searchInput.addEventListener('input', () => {
                clearTimeout(debounceTimer);
                updateClearButton();
                debounceTimer = setTimeout(() => {
                    fetchFunction(null, true, true);
                }, 350);
            });

            clearButton?.addEventListener('click', () => {
                if (!searchInput.value) {
                    return;
                }
                searchInput.value = '';
                updateClearButton();
                searchInput.focus();
                fetchFunction(null, true, true);
            });

            updateClearButton();
        }

        setupBackendSearch('searchActions', fetchActions);
        setupBackendSearch('searchFavorites', fetchFavorites);
        setupBackendSearch('searchAllSounds', fetchAllSounds);

        setInterval(() => {
            const isInteractingWithFilters = document.activeElement && document.activeElement.classList.contains('filter-select');
            const isEditingPageInput = document.activeElement && document.activeElement.classList.contains('pagination-page-input');
            if (isInteractingWithFilters || isEditingPageInput) {
                return;
            }
            Promise.all([fetchActions(), fetchFavorites(), fetchAllSounds(), refreshWebControlState(), refreshControlRoomStatus()]);
        }, 2000);

        Object.keys(fetchersByEndpoint).forEach(applyTableGeometry);
        Object.keys(fetchersByEndpoint).forEach(endpoint => {
            updateResultMeta(endpoint, initialSoundboardData?.[endpoint] || {}, 1);
            const tableBody = document.getElementById(endpointTableBodyIds[endpoint]);
            if (tableBody && !tableBody.children.length) {
                renderNoResultsRow(endpoint, tableBody);
            }
        });
        document.querySelectorAll('.play-button').forEach(applyPlayButtonState);
        document.querySelectorAll('.web-control-button').forEach(applyWebControlButtonState);
        refreshWebControlState();
        refreshControlRoomStatus();
        loadUploadInbox();
        fitActionBadges();

        window.addEventListener('resize', () => {
            let shouldRefetch = false;
            Object.keys(fetchersByEndpoint).forEach((endpoint) => {
                endpointStableItemsPerPageCeilings[endpoint] = endpointMaxItemsPerPage[endpoint];
                shouldRefetch = updateItemsPerPage(endpoint) || shouldRefetch;
                applyTableGeometry(endpoint);
            });
            if (shouldRefetch) {
                fetchActions(null, true);
                fetchFavorites(null, true);
                fetchAllSounds(null, true);
            }
            fitActionBadges();
        });
})();
