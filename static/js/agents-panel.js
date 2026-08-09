/**
 * AgentForge — Agent Activity Panel Controller
 * Manages real-time visualization of agent activity via SSE streaming.
 * Shows animated agent cards, activity timeline, and status transitions.
 */

const AgentsPanel = (() => {
    // Agent configuration map — matches backend AGENT_DISPLAY
    const AGENTS = {
        'Research Strategist': {
            id: 'agent-strategist',
            icon: '🔍',
            color: '#3b82f6',
            order: 1,
        },
        'Web Research Specialist': {
            id: 'agent-scraper',
            icon: '🌐',
            color: '#10b981',
            order: 2,
        },
        'Data Analyst': {
            id: 'agent-analyst',
            icon: '📊',
            color: '#f59e0b',
            order: 3,
        },
        'Report Writer': {
            id: 'agent-writer',
            icon: '📝',
            color: '#8b5cf6',
            order: 4,
        },
        'System': {
            id: null,
            icon: '⚡',
            color: '#94a3b8',
            order: 0,
        },
    };

    let activityCount = 0;
    let currentActiveAgent = null;

    /**
     * Show the agents panel and reset all agent states.
     */
    function show() {
        const panel = document.getElementById('agents-panel');
        if (panel) {
            panel.hidden = false;
            panel.style.display = 'block';
        }
        resetAgents();
        clearTimeline();
        activityCount = 0;
        updateActivityCount();
    }

    /**
     * Hide the agents panel.
     */
    function hide() {
        const panel = document.getElementById('agents-panel');
        if (panel) {
            panel.hidden = true;
            panel.style.display = 'none';
        }
    }

    /**
     * Reset all agent cards to their waiting state.
     */
    function resetAgents() {
        Object.values(AGENTS).forEach(agent => {
            if (!agent.id) return;
            const card = document.getElementById(agent.id);
            if (card) {
                card.classList.remove('active', 'completed');
                const statusText = card.querySelector('.agent-status-text');
                if (statusText) statusText.textContent = 'Waiting...';
            }
        });
        currentActiveAgent = null;
    }

    const AGENT_COMPLETED_MSG = {
        'Research Strategist': 'Scope Defined ✓',
        'Web Research Specialist': 'Sources Gathered ✓',
        'Data Analyst': 'Logic Analyzed ✓',
        'Report Writer': 'Guide Compiled ✓',
    };

    /**
     * Set an agent's state (active, completed, waiting).
     */
    function setAgentState(agentName, state, statusMessage = '') {
        const agent = AGENTS[agentName];
        if (!agent || !agent.id) return;

        const card = document.getElementById(agent.id);
        if (!card) return;

        // Clear previous states
        card.classList.remove('active', 'completed');

        switch (state) {
            case 'active':
                card.classList.add('active');
                // Mark previous active agent as completed with its distinct badge
                if (currentActiveAgent && currentActiveAgent !== agentName) {
                    const prevMsg = AGENT_COMPLETED_MSG[currentActiveAgent] || 'Task completed ✓';
                    setAgentState(currentActiveAgent, 'completed', prevMsg);
                }
                currentActiveAgent = agentName;
                break;
            case 'completed':
                card.classList.add('completed');
                break;
        }

        const statusText = card.querySelector('.agent-status-text');
        if (statusText && statusMessage) {
            statusText.textContent = statusMessage;
        }
    }

    /**
     * Add a new entry to the activity timeline.
     */
    function addTimelineEntry(activity) {
        const timeline = document.getElementById('activity-timeline');
        if (!timeline) return;

        const agent = AGENTS[activity.agent] || AGENTS['System'];

        const item = document.createElement('div');
        item.className = 'timeline-item';

        // Format timestamp
        const time = new Date(activity.timestamp);
        const timeStr = time.toLocaleTimeString('en-US', {
            hour: '2-digit',
            minute: '2-digit',
            second: '2-digit',
        });

        // Truncate content for display
        let displayContent = activity.content || activity.action;
        if (displayContent.length > 150) {
            displayContent = displayContent.substring(0, 147) + '...';
        }

        item.innerHTML = `
            <div class="timeline-dot" style="background: ${agent.color};"></div>
            <div class="timeline-content">
                <div class="timeline-agent" style="color: ${agent.color};">
                    ${agent.icon} ${activity.agent}
                </div>
                <div class="timeline-action">${escapeHtml(displayContent)}</div>
                <div class="timeline-time">${timeStr}</div>
            </div>
        `;

        timeline.appendChild(item);

        // Auto-scroll to bottom
        timeline.scrollTop = timeline.scrollHeight;

        // Update counter
        activityCount++;
        updateActivityCount();
    }

    /**
     * Process an agent activity event (from SSE stream).
     */
    function processActivity(activity) {
        const agentName = activity.agent;
        const action = activity.action || '';

        // Determine agent state based on action
        if (action === 'starting' || action === 'processing' ||
            action === 'thinking' || action === 'searching the web' ||
            action === 'scraping website content') {
            setAgentState(agentName, 'active', getStatusMessage(action));
        } else if (action === 'completed task') {
            const doneMsg = AGENT_COMPLETED_MSG[agentName] || 'Task completed ✓';
            setAgentState(agentName, 'completed', doneMsg);
        } else if (action === 'queued') {
            // Keep as waiting
        } else if (agentName !== 'System') {
            setAgentState(agentName, 'active', getStatusMessage(action));
        }

        // Add to timeline
        addTimelineEntry(activity);
    }

    /**
     * Mark participating agents as completed when research finishes.
     */
    function markAllCompleted() {
        Object.keys(AGENTS).forEach(name => {
            if (name !== 'System') {
                const agent = AGENTS[name];
                if (agent && agent.id) {
                    const card = document.getElementById(agent.id);
                    if (card) {
                        card.classList.remove('active');
                        card.classList.add('completed');
                        const statusText = card.querySelector('.agent-status-text');
                        if (statusText) {
                            statusText.textContent = AGENT_COMPLETED_MSG[name] || 'Done ✓';
                        }
                    }
                }
            }
        });
    }

    /**
     * Simulate agent workflow from an activity log (used on Vercel where SSE is unavailable).
     * Animates agents one-by-one, replaying the real activity log with delays.
     * Returns a Promise that resolves when the animation is complete.
     */
    function simulateWorkflow(activityLog) {
        return new Promise((resolve) => {
            const DEFAULT_WORKFLOW = [
                { agent: 'Research Strategist', action: 'starting', content: 'Formulating technical research plan & scope...' },
                { agent: 'Research Strategist', action: 'completed task', content: 'Scope & analysis structure defined.' },
                { agent: 'Web Research Specialist', action: 'searching the web', content: 'Querying technical documentation & search engines...' },
                { agent: 'Web Research Specialist', action: 'completed task', content: 'Syntax patterns & reference sources gathered.' },
                { agent: 'Data Analyst', action: 'processing', content: 'Analyzing core concepts, code logic & complexity...' },
                { agent: 'Data Analyst', action: 'completed task', content: 'Logic & theoretical definitions verified.' },
                { agent: 'Report Writer', action: 'processing', content: 'Drafting theory-first guide, code examples & walkthrough...' },
                { agent: 'Report Writer', action: 'completed task', content: 'Finalized complete response document.' },
            ];

            const events = (activityLog && activityLog.length > 0) ? activityLog : DEFAULT_WORKFLOW;

            const now = Date.now();
            const eventsWithTime = events.map((e, i) => ({
                ...e,
                timestamp: e.timestamp || new Date(now + i * 500).toISOString(),
            }));

            let i = 0;
            const stepDelay = 600;

            function step() {
                if (i >= eventsWithTime.length) {
                    markAllCompleted();
                    resolve();
                    return;
                }
                const activity = eventsWithTime[i++];
                processActivity(activity);
                window.setTimeout(step, stepDelay);
            }

            step();
        });
    }

    /**
     * Clear the activity timeline.
     */
    function clearTimeline() {
        const timeline = document.getElementById('activity-timeline');
        if (timeline) {
            timeline.innerHTML = '';
        }
    }

    /**
     * Update the activity count badge.
     */
    function updateActivityCount() {
        const badge = document.getElementById('activity-count');
        if (badge) {
            badge.textContent = `${activityCount} action${activityCount !== 1 ? 's' : ''}`;
        }
    }

    /**
     * Get a user-friendly status message for an action.
     */
    function getStatusMessage(action) {
        const messages = {
            'starting': 'Starting...',
            'processing': 'Processing...',
            'thinking': 'Thinking... 🤔',
            'searching the web': 'Searching web... 🔎',
            'scraping website content': 'Reading page... 📖',
            'creating agents': 'Initializing...',
            'creating tasks': 'Setting up tasks...',
            'assembling crew': 'All agents ready!',
            'initializing': 'Preparing...',
            'completed': 'Done ✓',
            'error': 'Error ⚠️',
        };
        return messages[action] || `${action}...`;
    }

    /**
     * Escape HTML entities to prevent XSS.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Public API
    return {
        show,
        hide,
        resetAgents,
        setAgentState,
        addTimelineEntry,
        processActivity,
        markAllCompleted,
        simulateWorkflow,
        clearTimeline,
    };
})();
