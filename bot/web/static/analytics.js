(() => {
        const analyticsConfigElement = document.getElementById('analytics-config');
        const analyticsConfig = analyticsConfigElement ? JSON.parse(analyticsConfigElement.textContent || '{}') : {};
        const discordUser = analyticsConfig.discord_user || null;
        const discordLoginUrl = analyticsConfig.discord_login_url || '/login';
        const themeToggle = document.querySelector('.theme-toggle');
        let currentDays = 7;
        let timelineChart = null;

        function getCssVar(name) {
            return getComputedStyle(document.documentElement).getPropertyValue(name).trim();
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
                if (timelineChart) {
                    loadTimeline();
                }
            });
        }

        document.addEventListener('DOMContentLoaded', () => {
            loadAllData();
            setupTimeSelector();
            setInterval(loadRecentActivity, 30000);
        });

        function setupTimeSelector() {
            document.querySelectorAll('.time-btn').forEach(btn => {
                btn.addEventListener('click', () => {
                    document.querySelectorAll('.time-btn').forEach(b => b.classList.remove('active'));
                    btn.classList.add('active');
                    currentDays = parseInt(btn.dataset.days);
                    loadAllData();
                });
            });
        }

        function loadAllData() {
            loadSummary();
            loadTopUsers();
            loadTopSounds();
            loadHeatmap();
            loadTimeline();
            loadRecentActivity();
        }

        function applyPlayButtonState(button) {
            if (discordUser) {
                button.disabled = false;
                button.classList.remove('login-required');
                button.textContent = '▶';
                button.title = 'Play sound';
                button.setAttribute('aria-label', 'Play sound');
                return;
            }

            button.disabled = false;
            button.classList.add('login-required');
            button.textContent = '🔒';
            button.title = 'Login with Discord to play';
            button.setAttribute('aria-label', 'Login with Discord to play');
        }

        async function loadSummary() {
            try {
                const res = await fetch(`/api/analytics/summary?days=${currentDays}`);
                const data = await res.json();

                animateNumber('totalSounds', data.total_sounds);
                animateNumber('totalPlays', data.total_plays);
                animateNumber('activeUsers', data.active_users);
                animateNumber('soundsThisWeek', data.sounds_this_week);
            } catch (err) {
                console.error('Error loading summary:', err);
            }
        }

        async function loadTopUsers() {
            try {
                const res = await fetch(`/api/analytics/top_users?days=${currentDays}&limit=8`);
                const data = await res.json();

                const container = document.getElementById('topUsers');
                if (!data.users || data.users.length === 0) {
                    container.innerHTML = '<p class="empty-state">No data available</p>';
                    return;
                }

                const maxCount = Math.max(...data.users.map(u => u.count));
                container.innerHTML = data.users.map((user, i) => `
                    <div class="leaderboard-item">
                        <div class="rank ${i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : ''}">${i + 1}</div>
                        <div class="item-info">
                            <div class="item-name">${escapeHtml(user.display_username || '')}</div>
                            <div class="item-bar">
                                <div class="item-bar-fill" style="width: ${(user.count / maxCount) * 100}%"></div>
                            </div>
                        </div>
                        <div class="item-count">${user.count}</div>
                    </div>
                `).join('');
            } catch (err) {
                console.error('Error loading top users:', err);
            }
        }

        async function loadTopSounds() {
            try {
                const res = await fetch(`/api/analytics/top_sounds?days=${currentDays}&limit=8`);
                const data = await res.json();

                const container = document.getElementById('topSounds');
                if (!data.sounds || data.sounds.length === 0) {
                    container.innerHTML = '<p class="empty-state">No data available</p>';
                    return;
                }

                const maxCount = Math.max(...data.sounds.map(s => s.count));
                container.innerHTML = data.sounds.map((sound, i) => `
                    <div class="leaderboard-item">
                        <div class="rank ${i === 0 ? 'gold' : i === 1 ? 'silver' : i === 2 ? 'bronze' : ''}">${i + 1}</div>
                        <div class="item-info">
                            <div class="item-name" title="${escapeHtml(sound.display_filename || '')}">${escapeHtml((sound.display_filename || '').replace('.mp3', ''))}</div>
                            <div class="item-bar">
                                <div class="item-bar-fill" style="width: ${(sound.count / maxCount) * 100}%"></div>
                            </div>
                        </div>
                        <div class="item-count">${sound.count}</div>
                        <button class="play-btn ${discordUser ? '' : 'login-required'}" data-sound-id="${sound.sound_id}" title="${discordUser ? 'Play sound' : 'Login with Discord to play'}">${discordUser ? '▶' : '🔒'}</button>
                    </div>
                `).join('');

                container.querySelectorAll('.play-btn').forEach(btn => {
                    applyPlayButtonState(btn);
                    btn.addEventListener('click', () => {
                        playSound(btn.dataset.soundId || '', btn);
                    });
                });
            } catch (err) {
                console.error('Error loading top sounds:', err);
            }
        }

        async function loadHeatmap() {
            try {
                const res = await fetch(`/api/analytics/activity_heatmap?days=${currentDays}`);
                const data = await res.json();

                const container = document.getElementById('heatmap');
                const days = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

                const countMap = {};
                let maxCount = 1;
                data.heatmap.forEach(item => {
                    const key = `${item.day}-${item.hour}`;
                    countMap[key] = item.count;
                    maxCount = Math.max(maxCount, item.count);
                });

                let html = '<div class="heatmap-header"></div>';
                for (let d = 0; d < 7; d++) {
                    html += `<div class="heatmap-header">${days[d]}</div>`;
                }

                for (let h = 0; h < 24; h++) {
                    html += `<div class="heatmap-row-label">${String(h).padStart(2, '0')}</div>`;
                    for (let d = 0; d < 7; d++) {
                        const count = countMap[`${d}-${h}`] || 0;
                        const level = count === 0 ? 0 : Math.min(5, Math.ceil((count / maxCount) * 5));
                        html += `
                            <div class="heatmap-cell" data-count="${count}" data-level="${level}" data-row="${d}">
                                <div class="heatmap-tooltip">${days[d]} ${h}:00 - ${count} plays</div>
                            </div>
                        `;
                    }
                }

                container.innerHTML = html;
            } catch (err) {
                console.error('Error loading heatmap:', err);
            }
        }

        async function loadTimeline() {
            try {
                const res = await fetch(`/api/analytics/activity_timeline?days=${currentDays}`);
                const data = await res.json();
                const ctx = document.getElementById('timelineChart').getContext('2d');
                const chartAccent = getCssVar('--accent');
                const chartFill = getCssVar('--accent-soft');
                const chartPaper = getCssVar('--paper');
                const chartTicks = getCssVar('--ink-muted');
                const chartGrid = getCssVar('--chart-grid');

                if (timelineChart) {
                    timelineChart.destroy();
                }

                const labels = data.timeline.map(t => {
                    const date = new Date(t.date);
                    if (currentDays === 0) {
                        return date.toLocaleDateString('en-US', { year: 'numeric', month: 'short', day: 'numeric' });
                    }
                    return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
                });
                const values = data.timeline.map(t => t.count);

                timelineChart = new Chart(ctx, {
                    type: 'line',
                    data: {
                        labels: labels,
                        datasets: [{
                            label: 'Plays',
                            data: values,
                            borderColor: chartAccent,
                            backgroundColor: chartFill,
                            fill: true,
                            tension: 0.35,
                            pointRadius: 2,
                            pointHoverRadius: 6,
                            pointBackgroundColor: chartAccent,
                            pointBorderColor: chartPaper,
                            pointBorderWidth: 2
                        }]
                    },
                    options: {
                        responsive: true,
                        maintainAspectRatio: false,
                        plugins: {
                            legend: { display: false }
                        },
                        scales: {
                            x: {
                                grid: { color: chartGrid },
                                ticks: { color: chartTicks, maxTicksLimit: 10 }
                            },
                            y: {
                                grid: { color: chartGrid },
                                ticks: { color: chartTicks },
                                beginAtZero: true
                            }
                        }
                    }
                });
            } catch (err) {
                console.error('Error loading timeline:', err);
            }
        }

        async function loadRecentActivity() {
            try {
                const res = await fetch('/api/analytics/recent_activity?limit=15');
                const data = await res.json();

                const container = document.getElementById('activityFeed');
                if (!data.activities || data.activities.length === 0) {
                    container.innerHTML = '<p class="empty-state">No recent activity</p>';
                    return;
                }

                container.innerHTML = data.activities.map(activity => {
                    const icon = getActivityIcon(activity.action);
                    const text = formatActivityText(activity);
                    const time = formatTime(activity.timestamp);

                    return `
                        <div class="activity-item">
                            <div class="activity-icon ${icon.class}">${icon.emoji}</div>
                            <div class="activity-content">
                                <div class="activity-text">${text}</div>
                                <div class="activity-time">${time}</div>
                            </div>
                        </div>
                    `;
                }).join('');
            } catch (err) {
                console.error('Error loading activity:', err);
            }
        }

        function animateNumber(elementId, target) {
            const el = document.getElementById(elementId);
            const start = parseInt(el.textContent) || 0;
            const duration = 500;
            const startTime = performance.now();

            function update(currentTime) {
                const elapsed = currentTime - startTime;
                const progress = Math.min(elapsed / duration, 1);
                const easeOut = 1 - Math.pow(1 - progress, 3);
                const current = Math.round(start + (target - start) * easeOut);
                el.textContent = current.toLocaleString();

                if (progress < 1) {
                    requestAnimationFrame(update);
                }
            }

            requestAnimationFrame(update);
        }

        function escapeHtml(text) {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        }

        function getActivityIcon(action) {
            const icons = {
                'play_random_sound': { emoji: '🎲', class: 'play' },
                'play_request': { emoji: '▶', class: 'play' },
                'replay_sound': { emoji: '↻', class: 'play' },
                'play_from_list': { emoji: '≡', class: 'play' },
                'play_similar_sound': { emoji: '⇄', class: 'play' },
                'play_sound_periodically': { emoji: '⏰', class: 'play' },
                'play_random_favorite_sound': { emoji: '★', class: 'play' },
                'favorite_sound': { emoji: '♥', class: 'favorite' },
                'unfavorite_sound': { emoji: '♡', class: 'favorite' },
                'join': { emoji: '↘', class: 'join' },
                'leave': { emoji: '↗', class: 'leave' }
            };
            return icons[action] || { emoji: '♪', class: 'play' };
        }

        function formatActivityText(activity) {
            const user = `<strong>${escapeHtml(activity.display_username || '')}</strong>`;
            const sound = activity.display_sound ? `<strong>${escapeHtml(activity.display_sound.replace('.mp3', ''))}</strong>` : '';

            switch (activity.action) {
                case 'play_random_sound': return `${user} played random ${sound}`;
                case 'play_request': return `${user} played ${sound}`;
                case 'replay_sound': return `${user} replayed ${sound}`;
                case 'play_from_list': return `${user} played from list: ${sound}`;
                case 'play_similar_sound': return `${user} played similar: ${sound}`;
                case 'play_sound_periodically': return `Bot auto-played ${sound}`;
                case 'play_random_favorite_sound': return `${user} played favorite ${sound}`;
                case 'favorite_sound': return `${user} favorited ${sound}`;
                case 'unfavorite_sound': return `${user} unfavorited ${sound}`;
                case 'join': return `${user} joined voice`;
                case 'leave': return `${user} left voice`;
                default: return `${user} ${activity.action}`;
            }
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

        function formatTime(timestamp) {
            const date = parseServerTimestamp(timestamp);
            if (Number.isNaN(date.getTime())) {
                return timestamp || '';
            }
            const now = new Date();
            const diffMs = now - date;
            const diffMins = Math.floor(diffMs / 60000);
            const diffHours = Math.floor(diffMs / 3600000);
            const diffDays = Math.floor(diffMs / 86400000);

            if (diffMins < 1) return 'Just now';
            if (diffMins < 60) return `${diffMins}m ago`;
            if (diffHours < 24) return `${diffHours}h ago`;
            if (diffDays < 30) return `${diffDays}d ago`;
            return date.toLocaleDateString();
        }

        async function playSound(soundId, button) {
            if (!soundId || !button) return;
            if (!discordUser) {
                window.location.href = discordLoginUrl;
                return;
            }

            button.disabled = true;
            button.classList.remove('sent', 'error');
            button.textContent = '⏳';

            try {
                const res = await fetch('/api/play_sound', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sound_id: soundId })
                });

                if (!res.ok) {
                    const payload = await res.json().catch(() => ({}));
                    if (res.status === 401 && payload.login_url) {
                        window.location.href = payload.login_url;
                        return;
                    }
                    button.textContent = '✗';
                    button.classList.add('error');
                } else {
                    button.textContent = '✓';
                    button.classList.add('sent');
                }
            } catch (err) {
                console.error('Error playing sound:', err);
                button.textContent = '✗';
                button.classList.add('error');
            } finally {
                setTimeout(() => {
                    button.classList.remove('sent', 'error');
                    button.style.background = '';
                    applyPlayButtonState(button);
                }, 1000);
            }
        }
})();
