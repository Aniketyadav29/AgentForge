/**
 * AgentForge — Main Application Controller
 * Manages form submission, SSE connections, history, and overall app state.
 */

const App = (() => {
    // Application state
    let currentTaskId = null;
    let eventSource = null;
    let isResearching = false;

    /**
     * Initialize the application.
     */
    function init() {
        // Bind form submission
        const form = document.getElementById('research-form');
        if (form) {
            form.addEventListener('submit', handleFormSubmit);
        }

        // Bind report action buttons
        const copyBtn = document.getElementById('btn-copy-report');
        if (copyBtn) {
            copyBtn.addEventListener('click', handleCopyReport);
        }

        const downloadBtn = document.getElementById('btn-download-report');
        if (downloadBtn) {
            downloadBtn.addEventListener('click', handleDownloadReport);
        }

        // Load research history
        loadHistory();

        // Show welcome state
        showWelcomeState();

        console.log('⚡ AgentForge initialized');
    }

    /**
     * Handle research form submission.
     */
    async function handleFormSubmit(e) {
        e.preventDefault();

        if (isResearching) return;

        const topicInput = document.getElementById('topic-input');
        const topic = topicInput ? topicInput.value.trim() : '';

        if (!topic) {
            showToast('Please enter a research topic.', 'error');
            return;
        }

        // Get selected depth
        const depthRadio = document.querySelector('input[name="depth"]:checked');
        const depth = depthRadio ? depthRadio.value : 'detailed';

        // Start research
        await startResearch(topic, depth);
    }

    /**
     * Submit research request to the API.
     */
    async function startResearch(topic, depth) {
        setLoadingState(true);
        hideWelcomeState();

        try {
            const response = await fetch('/api/research', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic, depth }),
            });

            if (!response.ok) {
                const error = await response.json();
                throw new Error(error.detail || 'Failed to start research');
            }

            const data = await response.json();
            currentTaskId = data.task_id;

            // Show agent panel and start SSE stream
            AgentsPanel.show();
            ReportViewer.hideReport();
            setSystemStatus('running', `Researching: ${truncate(topic, 40)}`);
            showToast('Research crew launched! Watch the agents work below.', 'success');

            // Connect to SSE stream
            connectSSE(currentTaskId);

        } catch (error) {
            console.error('Research start error:', error);
            showToast(`Failed to start research: ${error.message}`, 'error');
            setLoadingState(false);
            showWelcomeState();
        }
    }

    /**
     * Connect to the SSE stream for real-time agent activity.
     */
    function connectSSE(taskId) {
        // Close any existing connection
        if (eventSource) {
            eventSource.close();
        }

        eventSource = new EventSource(`/api/research/${taskId}/stream`);

        eventSource.addEventListener('agent_activity', (event) => {
            try {
                const activity = JSON.parse(event.data);
                AgentsPanel.processActivity(activity);
            } catch (e) {
                console.error('SSE parse error:', e);
            }
        });

        eventSource.addEventListener('research_complete', async (event) => {
            try {
                const data = JSON.parse(event.data);
                eventSource.close();
                eventSource = null;

                if (data.status === 'completed') {
                    // Fetch the full result
                    await fetchAndShowResult(taskId);
                    AgentsPanel.markAllCompleted();
                    setSystemStatus('idle', 'Research completed ✓');
                    showToast('Research completed! Scroll down to see the report.', 'success');
                } else {
                    setSystemStatus('error', 'Research failed');
                    showToast(`Research failed: ${data.error || 'Unknown error'}`, 'error');
                }
            } catch (e) {
                console.error('SSE complete event error:', e);
            }

            setLoadingState(false);
            loadHistory(); // Refresh history
        });

        eventSource.onerror = (error) => {
            console.error('SSE error:', error);
            // Don't immediately show error — SSE auto-reconnects
            // Only handle if the connection is truly closed
            if (eventSource && eventSource.readyState === EventSource.CLOSED) {
                eventSource = null;
                setLoadingState(false);
                // Try to fetch result anyway (it may have completed)
                fetchAndShowResult(taskId);
            }
        };
    }

    /**
     * Fetch the final result and show the report.
     */
    async function fetchAndShowResult(taskId) {
        try {
            const response = await fetch(`/api/research/${taskId}/result`);
            if (!response.ok) {
                throw new Error('Failed to fetch result');
            }

            const data = await response.json();
            ReportViewer.showReport(data);
        } catch (error) {
            console.error('Fetch result error:', error);
        }
    }

    /**
     * Load research history from the API.
     */
    async function loadHistory() {
        try {
            const response = await fetch('/api/history');
            if (!response.ok) return;

            const data = await response.json();
            renderHistory(data.sessions || []);
        } catch (error) {
            console.error('History load error:', error);
        }
    }

    /**
     * Render the history sidebar.
     */
    function renderHistory(sessions) {
        const container = document.getElementById('history-list');
        if (!container) return;

        if (sessions.length === 0) {
            container.innerHTML = `
                <div class="history-empty">
                    <div class="empty-icon">📭</div>
                    <p>No research sessions yet.<br>Start your first research above!</p>
                </div>
            `;
            return;
        }

        container.innerHTML = sessions.map(session => {
            const date = new Date(session.created_at);
            const dateStr = date.toLocaleDateString('en-US', {
                month: 'short',
                day: 'numeric',
            });
            const timeStr = date.toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
            });

            const statusClass = session.status || 'completed';
            const isActive = session.task_id === currentTaskId;
            const duration = session.duration_seconds
                ? `${session.duration_seconds}s`
                : '—';

            return `
                <div class="history-item ${isActive ? 'active' : ''}"
                     onclick="App.loadHistoryItem('${session.task_id}')"
                     title="${escapeAttr(session.topic)}">
                    <div class="history-topic">${escapeHtml(session.topic)}</div>
                    <div class="history-meta">
                        <div class="history-status">
                            <span class="history-status-dot ${statusClass}"></span>
                            <span>${statusClass}</span>
                        </div>
                        <span>${dateStr} ${timeStr} · ${duration}</span>
                    </div>
                </div>
            `;
        }).join('');
    }

    /**
     * Load a specific history item and display its report.
     */
    async function loadHistoryItem(taskId) {
        try {
            const response = await fetch(`/api/history/${taskId}`);
            if (!response.ok) throw new Error('Not found');

            const data = await response.json();

            // Safe parsing helper function
            const parseJsonIfNeeded = (val) => {
                if (!val) return [];
                if (typeof val === 'string') {
                    try { return JSON.parse(val); } catch (e) { return []; }
                }
                return Array.isArray(val) ? val : [];
            };

            const agentsUsed = parseJsonIfNeeded(data.agents_used);
            const activityLog = parseJsonIfNeeded(data.activity_log);
            const reportContent = data.report || data.error_message || 'No report available for this session.';

            currentTaskId = taskId;
            hideWelcomeState();

            ReportViewer.showReport({
                report: reportContent,
                task_id: taskId,
                duration_seconds: data.duration_seconds,
                agents_used: agentsUsed,
                activity_count: activityLog.length,
                depth: data.depth,
            });

            // Update active state in sidebar
            document.querySelectorAll('.history-item').forEach(item => {
                item.classList.remove('active');
            });
            const clickedItems = document.querySelectorAll('.history-item');
            clickedItems.forEach(item => {
                if (item.getAttribute('onclick')?.includes(taskId)) {
                    item.classList.add('active');
                }
            });

        } catch (error) {
            console.error('Load history item error:', error);
            showToast('Failed to load research session.', 'error');
        }
    }

    /**
     * Handle copy report button click.
     */
    async function handleCopyReport() {
        const success = await ReportViewer.copyReport();
        if (success) {
            showToast('Report copied to clipboard!', 'success');
            // Visual feedback on button
            const btn = document.getElementById('btn-copy-report');
            if (btn) {
                const originalText = btn.innerHTML;
                btn.innerHTML = '✓ Copied!';
                setTimeout(() => { btn.innerHTML = originalText; }, 2000);
            }
        }
    }

    /**
     * Handle download report button click.
     */
    function handleDownloadReport() {
        ReportViewer.downloadReport();
        showToast('Report downloaded!', 'success');
    }

    /**
     * Set loading state for the submit button.
     */
    function setLoadingState(loading) {
        isResearching = loading;
        const btn = document.getElementById('submit-btn');
        if (btn) {
            btn.disabled = loading;
            btn.classList.toggle('loading', loading);
        }
    }

    /**
     * Update the system status indicator in the header.
     */
    function setSystemStatus(state, message) {
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');

        if (dot) {
            dot.className = 'status-dot';
            if (state === 'running') dot.classList.add('running');
            else if (state === 'error') dot.classList.add('error');
            else dot.classList.add('idle');
        }

        if (text) {
            text.textContent = message || 'System Ready';
        }
    }

    /**
     * Show the welcome/empty state.
     */
    function showWelcomeState() {
        const welcome = document.getElementById('welcome-state');
        if (welcome) welcome.style.display = 'flex';
    }

    /**
     * Hide the welcome/empty state.
     */
    function hideWelcomeState() {
        const welcome = document.getElementById('welcome-state');
        if (welcome) welcome.style.display = 'none';
    }

    /**
     * Show a toast notification.
     */
    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const icons = {
            success: '✅',
            error: '❌',
            info: 'ℹ️',
        };

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${escapeHtml(message)}</span>
            <button class="toast-close" onclick="this.parentElement.remove()">✕</button>
        `;

        container.appendChild(toast);

        // Auto-remove after 5 seconds
        setTimeout(() => {
            if (toast.parentElement) {
                toast.style.animation = 'slideOutRight 0.3s ease-out forwards';
                setTimeout(() => toast.remove(), 300);
            }
        }, 5000);
    }

    /**
     * Truncate a string to a maximum length.
     */
    function truncate(str, maxLen) {
        if (str.length <= maxLen) return str;
        return str.substring(0, maxLen - 3) + '...';
    }

    /**
     * Escape HTML entities for safe rendering.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    /**
     * Escape for HTML attributes.
     */
    function escapeAttr(text) {
        return text.replace(/"/g, '&quot;').replace(/'/g, '&#39;');
    }

    // Initialize on DOM load
    document.addEventListener('DOMContentLoaded', init);

    // Public API
    return {
        startResearch,
        loadHistoryItem,
        showToast,
    };
})();
