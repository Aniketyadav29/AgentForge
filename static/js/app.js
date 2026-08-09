/**
 * AgentForge main application controller.
 * Powers research streaming, document RAG, image generation, history, and health widgets.
 */

// ─── LocalSessionCache ───────────────────────────────────────────────────────
// Stores research sessions in localStorage so that Vercel deployments (which
// use an ephemeral /tmp SQLite that resets between invocations) can still show
// history and reload results after a page refresh.
const LocalSessionCache = (() => {
    const KEY = 'agentforge_sessions';
    const MAX = 50;

    function _load() {
        try { return JSON.parse(localStorage.getItem(KEY) || '[]'); }
        catch (e) { return []; }
    }

    function _save(sessions) {
        try { localStorage.setItem(KEY, JSON.stringify(sessions)); } catch (e) {}
    }

    /** Save or update a full session record. */
    function put(session) {
        const sessions = _load();
        const idx = sessions.findIndex((s) => s.task_id === session.task_id);
        if (idx >= 0) sessions[idx] = session;
        else sessions.unshift(session);
        _save(sessions.slice(0, MAX));
    }

    /** Get one session by task_id. Returns null if not found. */
    function get(taskId) {
        return _load().find((s) => s.task_id === taskId) || null;
    }

    /** Get all cached sessions (newest first). */
    function getAll() {
        return _load();
    }

    /** Merge localStorage sessions with API sessions, API wins on duplicates. */
    function mergeWithApi(apiSessions) {
        const cached = _load();
        const apiIds = new Set(apiSessions.map((s) => s.task_id));
        // Add cached sessions that the API doesn't know about
        const localOnly = cached.filter((s) => !apiIds.has(s.task_id));
        return [...apiSessions, ...localOnly];
    }

    return { put, get, getAll, mergeWithApi };
})();
// ─────────────────────────────────────────────────────────────────────────────

const App = (() => {
    let currentTaskId = null;
    let currentDocId = null;
    let currentImageUrl = '';
    let currentFlowchartSvg = '';
    let eventSource = null;
    let isResearching = false;
    let healthTimer = null;
    const documentsById = new Map();
    const API_BASE = window.location.port === '8010' ? 'http://127.0.0.1:8000' : '';

    function init() {
        bindResearchControls();
        loadHistory();
        loadDocuments();
        refreshHealth();
        healthTimer = window.setInterval(refreshHealth, 30000);
        showWelcomeState();
        window.addEventListener('beforeunload', cleanup);
    }

    function bindResearchControls() {
        const form = document.getElementById('research-form');
        if (form) form.addEventListener('submit', handleFormSubmit);

        const copyBtn = document.getElementById('btn-copy-report');
        if (copyBtn) copyBtn.addEventListener('click', handleCopyReport);

        const readmeDownloadBtn = document.getElementById('btn-download-readme');
        if (readmeDownloadBtn) readmeDownloadBtn.addEventListener('click', handleDownloadReadme);

        const pdfDownloadBtn = document.getElementById('btn-download-pdf');
        if (pdfDownloadBtn) pdfDownloadBtn.addEventListener('click', handleDownloadPdf);
    }

    function cleanup() {
        if (eventSource) eventSource.close();
        if (healthTimer) window.clearInterval(healthTimer);
    }

    function switchMode(mode) {
        ['research', 'document', 'image'].forEach((name) => {
            const tab = document.getElementById(`mode-${name}`);
            const view = document.getElementById(`${name}-mode`);
            if (tab) tab.classList.toggle('active', name === mode);
            if (view) view.hidden = name !== mode;
        });

        if (mode === 'document') loadDocuments();
        if (mode === 'research') loadHistory();
    }

    function fillPrompt(text) {
        const input = document.getElementById('topic-input');
        if (!input) return;
        input.value = text;
        input.focus();
        showToast('Prompt filled. Launch when ready.', 'info');
    }

    function fillImagePrompt(text) {
        const input = document.getElementById('image-prompt');
        if (!input) return;
        input.value = text;
        input.focus();
    }

    function syncResearchPrompt(text) {
        const input = document.getElementById('topic-input');
        if (input) input.value = text;
    }

    function setDepth(depth) {
        const input = document.querySelector(`input[name="depth"][value="${depth}"]`);
        if (input) input.checked = true;

        document.querySelectorAll('.depth-orbits button, .depth-label').forEach((button) => {
            button.classList.toggle('selected', button.textContent.toLowerCase().includes(depth.replace('-', ' ')));
        });
    }

    async function launchFromVisualCommand() {
        const visualInput = document.getElementById('visual-command-input');
        const topicInput = document.getElementById('topic-input');
        const topic = (visualInput?.value || topicInput?.value || '').trim();
        const depth = document.querySelector('input[name="depth"]:checked')?.value || 'detailed';

        if (topicInput && topic) topicInput.value = topic;
        if (!topic) {
            showToast('Enter a research command first.', 'error');
            visualInput?.focus();
            return;
        }

        await startResearch(topic, depth);
    }

    async function attachFileToTextarea(event, textareaId, badgeId) {
        const file = event.target.files?.[0];
        if (!file) return;

        const textarea = document.getElementById(textareaId);
        const badge = document.getElementById(badgeId);
        const maxBytes = 350000;

        if (file.size > maxBytes) {
            showToast('Attached context file is too large. Use a smaller text file.', 'error');
            event.target.value = '';
            return;
        }

        try {
            const text = await file.text();
            textarea.value = `${textarea.value.trim()}\n\nAttached file context (${file.name}):\n${text}`.trim();
            if (badge) {
                badge.hidden = false;
                badge.textContent = `Attached ${file.name}`;
            }
            showToast('File context added to the research prompt.', 'success');
        } catch (error) {
            showToast(`Could not attach file: ${error.message}`, 'error');
        }
    }

    async function handleFormSubmit(event) {
        event.preventDefault();
        if (isResearching) return;

        const topic = document.getElementById('topic-input')?.value.trim() || '';
        const depth = document.querySelector('input[name="depth"]:checked')?.value || 'detailed';

        if (!topic) {
            showToast('Enter a research topic first.', 'error');
            return;
        }

        await startResearch(topic, depth);
    }

    async function startResearch(topic, depth) {
        setLoadingState(true);
        hideWelcomeState();

        try {
            const response = await fetch(apiUrl('/api/research'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ topic, depth }),
            });

            const data = await readJsonResponse(response);
            currentTaskId = data.task_id;

            AgentsPanel.show();
            ReportViewer.hideReport();

            // On Vercel serverless, the POST returns status='completed' immediately
            // because the research ran synchronously. The full report is embedded in
            // the response — save it to localStorage for offline history access.
            if (data.status === 'completed') {
                showToast('Research crew launched.', 'success');
                setSystemStatus('running', `Researching: ${truncate(topic, 44)}`);

                // Persist the full session to localStorage immediately
                LocalSessionCache.put({
                    task_id: data.task_id,
                    topic: data.topic,
                    depth: data.depth,
                    status: 'completed',
                    report: data.report || '',
                    activity_log: data.activity_log || [],
                    agents_used: data.agents_used || [],
                    duration_seconds: data.duration_seconds || null,
                    activity_count: data.activity_count || 0,
                    created_at: data.timestamp,
                    completed_at: data.timestamp,
                });

                // Animate agents working one-by-one using the real activity log
                await AgentsPanel.simulateWorkflow(data.activity_log || []);
                await fetchAndShowResult(currentTaskId);
                setSystemStatus('idle', 'Research completed');
                showToast('Report is ready.', 'success');
                setLoadingState(false);
                loadHistory();
                refreshHealth();
            } else {
                setSystemStatus('running', `Researching: ${truncate(topic, 44)}`);
                showToast('Research crew launched.', 'success');
                connectSSE(currentTaskId);
                loadHistory();
            }
        } catch (error) {
            showToast(`Failed to start research: ${error.message}`, 'error');
            setSystemStatus('error', 'Research failed to start');
            setLoadingState(false);
            showWelcomeState();
        }
    }

    function connectSSE(taskId) {
        if (eventSource) eventSource.close();
        eventSource = new EventSource(apiUrl(`/api/research/${taskId}/stream`));

        eventSource.addEventListener('agent_activity', (event) => {
            try {
                AgentsPanel.processActivity(JSON.parse(event.data));
            } catch (error) {
                console.error('SSE parse error:', error);
            }
        });

        eventSource.addEventListener('research_complete', async (event) => {
            try {
                const data = JSON.parse(event.data);
                eventSource.close();
                eventSource = null;

                if (data.status === 'completed') {
                    await fetchAndShowResult(taskId);
                    AgentsPanel.markAllCompleted();
                    setSystemStatus('idle', 'Research completed');
                    showToast('Report is ready.', 'success');
                } else {
                    setSystemStatus('error', 'Research failed');
                    showToast(data.error || 'Research failed.', 'error');
                }
            } catch (error) {
                console.error('SSE completion error:', error);
            } finally {
                setLoadingState(false);
                loadHistory();
                refreshHealth();
            }
        });

        eventSource.onerror = () => {
            if (eventSource && eventSource.readyState === EventSource.CLOSED) {
                eventSource = null;
                setLoadingState(false);
                fetchAndShowResult(taskId);
                loadHistory();
            }
        };
    }

    async function fetchAndShowResult(taskId) {
        // Check localStorage cache first (needed on Vercel where /tmp DB is ephemeral)
        const cached = LocalSessionCache.get(taskId);
        if (cached && cached.report) {
            ReportViewer.showReport({
                task_id: cached.task_id,
                topic: cached.topic,
                depth: cached.depth,
                status: cached.status,
                report: cached.report,
                duration_seconds: cached.duration_seconds,
                agents_used: cached.agents_used || [],
                activity_count: cached.activity_count || (cached.activity_log || []).length,
                activities: cached.activity_log || [],
                timestamp: cached.completed_at || cached.created_at,
            });
            return;
        }
        // Fall back to API (works on local / hosted deployments with persistent DB)
        try {
            const response = await fetch(apiUrl(`/api/research/${taskId}/result`));
            const data = await readJsonResponse(response);
            // Cache for future use
            LocalSessionCache.put({
                task_id: data.task_id || taskId,
                topic: data.topic || '',
                depth: data.depth || 'detailed',
                status: data.status || 'completed',
                report: data.report || '',
                activity_log: data.activities || data.activity_log || [],
                agents_used: data.agents_used || [],
                duration_seconds: data.duration_seconds || null,
                activity_count: data.activity_count || 0,
                created_at: data.timestamp || new Date().toISOString(),
                completed_at: data.timestamp || new Date().toISOString(),
            });
            ReportViewer.showReport(data);
        } catch (error) {
            showToast(`Could not fetch report: ${error.message}`, 'error');
        }
    }

    async function loadHistory() {
        try {
            const response = await fetch(apiUrl('/api/history'));
            const data = await readJsonResponse(response);
            // Merge API sessions with localStorage cache (Vercel: DB may be empty)
            const merged = LocalSessionCache.mergeWithApi(data.sessions || []);
            renderHistory(merged);
        } catch (error) {
            // API unavailable — fall back to localStorage only
            renderHistory(LocalSessionCache.getAll());
        }
    }

    function renderHistory(sessions) {
        const container = document.getElementById('history-list');
        if (!container) return;

        if (!sessions.length) {
            container.innerHTML = `
                <div class="history-empty">
                    <strong>No research sessions yet.</strong>
                    <span>Launch your first report to build the archive.</span>
                </div>
            `;
            return;
        }

        container.innerHTML = sessions.map((session) => {
            const created = formatDateTime(session.created_at);
            const duration = session.duration_seconds ? `${Math.round(session.duration_seconds)}s` : 'pending';
            const status = session.status || 'completed';
            return `
                <button class="history-item ${session.task_id === currentTaskId ? 'active' : ''}" type="button" onclick="App.loadHistoryItem('${escapeAttr(session.task_id)}')" title="${escapeAttr(session.topic)}">
                    <span class="history-topic">${escapeHtml(session.topic)}</span>
                    <span class="history-meta">
                        <span class="history-status"><span class="history-status-dot ${escapeAttr(status)}"></span>${escapeHtml(status)}</span>
                        <span>${created} · ${duration}</span>
                    </span>
                </button>
            `;
        }).join('');
    }

    async function loadHistoryItem(taskId) {
        // Check localStorage cache first (needed on Vercel where /tmp DB is ephemeral)
        const cached = LocalSessionCache.get(taskId);
        if (cached && cached.report) {
            currentTaskId = taskId;
            switchMode('research');
            hideWelcomeState();
            ReportViewer.showReport({
                report: cached.report || 'No report available for this session.',
                task_id: taskId,
                duration_seconds: cached.duration_seconds,
                agents_used: cached.agents_used || [],
                activity_count: cached.activity_count || (cached.activity_log || []).length,
                depth: cached.depth,
            });
            loadHistory();
            return;
        }
        // Fall back to API
        try {
            const response = await fetch(apiUrl(`/api/history/${taskId}`));
            const data = await readJsonResponse(response);
            const activityLog = parseJsonIfNeeded(data.activity_log);
            const agentsUsed = parseJsonIfNeeded(data.agents_used);

            // Save to localStorage for next time
            LocalSessionCache.put({
                task_id: taskId,
                topic: data.topic || '',
                depth: data.depth || 'detailed',
                status: data.status || 'completed',
                report: data.report || '',
                activity_log: activityLog,
                agents_used: agentsUsed,
                duration_seconds: data.duration_seconds || null,
                activity_count: activityLog.length,
                created_at: data.created_at || new Date().toISOString(),
                completed_at: data.completed_at || new Date().toISOString(),
            });

            currentTaskId = taskId;
            switchMode('research');
            hideWelcomeState();
            ReportViewer.showReport({
                report: data.report || data.error_message || 'No report available for this session.',
                task_id: taskId,
                duration_seconds: data.duration_seconds,
                agents_used: agentsUsed,
                activity_count: activityLog.length,
                depth: data.depth,
            });
            loadHistory();
        } catch (error) {
            showToast(`Could not load history item: ${error.message}`, 'error');
        }
    }

    async function refreshHealth() {
        try {
            const response = await fetch(apiUrl('/health'));
            const data = await readJsonResponse(response);
            setText('health-status', data.status || 'healthy');
            setText('health-version', data.version || '-');
            setText('health-sessions', String(data.active_sessions ?? '-'));
        } catch (error) {
            setText('health-status', 'offline');
            setText('health-version', '-');
            setText('health-sessions', '-');
        }
    }

    function triggerFileInput(event) {
        if (event.target?.id === 'file-input') return;
        document.getElementById('file-input')?.click();
    }

    function handleDragOver(event) {
        event.preventDefault();
        document.getElementById('upload-zone')?.classList.add('drag-over');
    }

    function handleDragLeave(event) {
        event.preventDefault();
        document.getElementById('upload-zone')?.classList.remove('drag-over');
    }

    function handleFileDrop(event) {
        event.preventDefault();
        document.getElementById('upload-zone')?.classList.remove('drag-over');
        const file = event.dataTransfer?.files?.[0];
        if (file) uploadDocument(file);
    }

    function handleFileSelect(event) {
        const file = event.target.files?.[0];
        if (file) uploadDocument(file);
        event.target.value = '';
    }

    async function uploadDocument(file) {
        const allowed = ['pdf', 'docx', 'csv', 'xlsx', 'xls', 'txt', 'md', 'json', 'html', 'htm', 'pptx', 'png', 'jpg', 'jpeg', 'webp', 'bmp', 'gif'];
        const ext = file.name.split('.').pop().toLowerCase();
        if (!allowed.includes(ext)) {
            showToast(`Unsupported file type .${ext}.`, 'error');
            return;
        }

        setText('selected-file-label', file.name);
        setUploadProgress(true, 18, 'Uploading file...');

        try {
            const formData = new FormData();
            formData.append('file', file);
            setUploadProgress(true, 42, 'Parsing and indexing document...');

            const response = await fetch(apiUrl('/api/documents/upload'), {
                method: 'POST',
                body: formData,
            });
            const data = await readJsonResponse(response);

            currentDocId = data.doc_id;
            renderCurrentDoc(data);
            resetDocChat();
            document.getElementById('doc-qa-section').hidden = false;
            setUploadProgress(false);
            showToast(`${data.filename} is indexed. Building report...`, 'success');
            loadDocuments();
            await generateDocumentReport(data.doc_id);
        } catch (error) {
            setUploadProgress(false);
            showToast(`Document upload failed: ${error.message}`, 'error');
        }
    }

    async function loadDocuments() {
        const container = document.getElementById('docs-list');
        if (!container) return;

        try {
            const response = await fetch(apiUrl('/api/documents'));
            const data = await readJsonResponse(response);
            const docs = data.documents || [];
            documentsById.clear();
            docs.forEach((doc) => documentsById.set(doc.doc_id, doc));

            if (!docs.length) {
                container.innerHTML = `
                    <div class="history-empty">
                        <strong>No documents loaded.</strong>
                        <span>Upload one in the Documents tab.</span>
                    </div>
                `;
                return;
            }

            container.innerHTML = docs.map((doc) => `
                <button class="doc-item ${doc.doc_id === currentDocId ? 'active' : ''}" type="button" onclick="App.selectDocumentById('${escapeAttr(doc.doc_id)}')">
                    <span class="doc-name">${escapeHtml(doc.filename)}</span>
                    <span class="doc-meta">
                        <span>${escapeHtml(String(doc.file_type || '').toUpperCase())} · ${formatBytes(doc.file_size || 0)}</span>
                        <span>${Number(doc.chunk_count || 0)} chunks</span>
                    </span>
                </button>
            `).join('');
        } catch (error) {
            container.innerHTML = `
                <div class="history-empty">
                    <strong>Documents unavailable.</strong>
                    <span>${escapeHtml(error.message)}</span>
                </div>
            `;
        }
    }

    function selectDocumentById(docId) {
        const doc = documentsById.get(docId);
        if (!doc) {
            showToast('Could not find that document. Refreshing the list.', 'error');
            loadDocuments();
            return;
        }

        selectDocument(
            doc.doc_id,
            doc.filename,
            doc.file_type,
            Number(doc.file_size || 0),
            Number(doc.chunk_count || 0),
            Boolean(doc.has_tables)
        );
    }

    function selectDocument(docId, filename, fileType, fileSize, chunkCount, hasTables) {
        currentDocId = docId;
        switchMode('document');
        renderCurrentDoc({
            doc_id: docId,
            filename,
            file_type: fileType,
            file_size: fileSize,
            chunk_count: chunkCount,
            has_tables: Boolean(hasTables),
        });
        resetDocChat();
        document.getElementById('doc-qa-section').hidden = false;
        loadDocuments();
        showToast(`${filename} selected.`, 'info');
    }

    function renderCurrentDoc(doc) {
        const info = document.getElementById('doc-info-bar');
        if (!info) return;

        info.hidden = false;
        setText('doc-info-icon', String(doc.file_type || 'doc').toUpperCase().slice(0, 4));
        setText('doc-info-name', doc.filename || 'Uploaded document');
        setText(
            'doc-info-meta',
            `${String(doc.file_type || '').toUpperCase()} · ${formatBytes(doc.file_size || 0)} · ${doc.chunk_count || 0} chunks${doc.has_tables ? ' · tables detected' : ''}`
        );
    }

    function resetDocChat() {
        const history = document.getElementById('doc-chat-history');
        if (!history) return;
        history.innerHTML = `
            <div class="doc-chat-welcome">
                <strong>Document ready.</strong>
                <span>Ask a question or request a calculation grounded in the uploaded file.</span>
            </div>
        `;
    }

    async function deleteCurrentDoc() {
        if (!currentDocId) {
            showToast('No document selected.', 'error');
            return;
        }

        try {
            const response = await fetch(apiUrl(`/api/documents/${currentDocId}`), { method: 'DELETE' });
            await readJsonResponse(response);
            currentDocId = null;
            setText('selected-file-label', 'No file chosen');
            document.getElementById('doc-info-bar').hidden = true;
            document.getElementById('doc-qa-section').hidden = true;
            resetDocChat();
            showToast('Document removed.', 'success');
            loadDocuments();
        } catch (error) {
            showToast(`Could not remove document: ${error.message}`, 'error');
        }
    }

    async function generateCurrentDocReport() {
        if (!currentDocId) {
            showToast('Upload or select a document first.', 'error');
            return;
        }
        await generateDocumentReport(currentDocId);
    }

    async function generateDocumentReport(docId) {
        try {
            setSystemStatus('running', 'Generating document report');
            const response = await fetch(apiUrl(`/api/documents/${docId}/report`));
            const data = await readJsonResponse(response);
            switchMode('document');
            ReportViewer.showReport({
                report: data.report,
                task_id: data.doc_id,
                depth: 'document',
                activity_count: data.sources?.length || 0,
                agents_used: ['Document Analyzer'],
            });
            appendChatBubble('assistant', data.report, data.sources || []);
            setSystemStatus('idle', 'Document report ready');
            showToast('Complete document report generated.', 'success');
        } catch (error) {
            setSystemStatus('error', 'Document report failed');
            showToast(`Could not generate report: ${error.message}`, 'error');
        }
    }

    function askQuickDocQuestion(questionText) {
        const input = document.getElementById('doc-question-input');
        const form = document.getElementById('doc-question-form');
        if (!input || !form) return;
        input.value = questionText;
        form.dispatchEvent(new Event('submit', { cancelable: true, bubbles: true }));
    }

    async function submitDocQuestion(event) {
        event.preventDefault();
        if (!currentDocId) {
            showToast('Upload or select a document first.', 'error');
            return;
        }

        const input = document.getElementById('doc-question-input');
        const question = input?.value.trim() || '';
        if (!question) return;

        appendChatBubble('user', question);
        input.value = '';
        setDocLoading(true);

        try {
            const response = await fetch(apiUrl(`/api/documents/${currentDocId}/query`), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ question }),
            });
            const data = await readJsonResponse(response);
            appendChatBubble('assistant', data.answer || 'No answer returned.', data.sources || [], data.computation_steps);
        } catch (error) {
            appendChatBubble('assistant', `Error: ${error.message}`);
            showToast('Document question failed.', 'error');
        } finally {
            setDocLoading(false);
        }
    }

    function appendChatBubble(role, content, sources = [], computationSteps = null) {
        const history = document.getElementById('doc-chat-history');
        if (!history) return;

        const bubble = document.createElement('div');
        bubble.className = `chat-bubble chat-bubble-${role === 'user' ? 'user' : 'assistant'}`;

        const rendered = role === 'assistant' ? renderMarkdown(content) : escapeHtml(content);
        const sourceHtml = sources.length ? `
            <div class="source-chips">
                ${sources.slice(0, 5).map((source, index) => `<span class="source-chip" title="${escapeAttr(source.chunk || '')}">Source ${index + 1} · ${Math.round((source.score || 0) * 100)}%</span>`).join('')}
            </div>
        ` : '';
        const mathHtml = computationSteps ? `
            <div class="computation-steps">
                <strong>Computation steps</strong>
                <pre>${escapeHtml(computationSteps)}</pre>
            </div>
        ` : '';

        bubble.innerHTML = `
            <span class="bubble-role">${role === 'user' ? 'You' : 'AgentForge'}</span>
            <div class="bubble-content">${rendered}${sourceHtml}${mathHtml}</div>
        `;
        history.appendChild(bubble);
        history.scrollTop = history.scrollHeight;
    }

    async function handleImageGenSubmit(event) {
        event.preventDefault();
        const prompt = document.getElementById('image-prompt')?.value.trim() || '';
        if (!prompt) {
            showToast('Describe the image you want first.', 'error');
            return;
        }

        // Read visual type selector
        const visualType = document.querySelector('input[name="visual-type"]:checked')?.value || 'auto';

        const box = document.getElementById('image-result-box');
        const loader = document.getElementById('image-loading-spinner');
        const preview = document.getElementById('generated-image-preview');
        const flowchart = document.getElementById('generated-flowchart-preview');
        const actions = document.getElementById('image-actions');
        const flowchartDownload = document.getElementById('btn-download-flowchart');
        const imageLink = document.getElementById('image-download-link');
        const generateBtn = document.getElementById('btn-generate-visual');

        if (box) box.hidden = false;
        if (loader) loader.hidden = false;
        if (preview) preview.hidden = true;
        if (flowchart) {
            flowchart.hidden = true;
            flowchart.innerHTML = '';
        }
        if (actions) actions.hidden = true;
        if (flowchartDownload) flowchartDownload.hidden = true;
        if (imageLink) imageLink.hidden = false;
        if (generateBtn) {
            generateBtn.disabled = true;
            generateBtn.classList.add('loading');
        }
        currentFlowchartSvg = '';

        try {
            const response = await fetch(apiUrl('/api/tools/image'), {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ prompt, type: visualType }),
            });
            const data = await readJsonResponse(response);

            if (data.type === 'flowchart' && data.flowchart_svg) {
                currentFlowchartSvg = data.flowchart_svg;
                if (loader) loader.hidden = true;
                if (flowchart) {
                    flowchart.innerHTML = '';

                    // ── Definition card ──────────────────────────────
                    if (data.definition) {
                        const defCard = document.createElement('div');
                        defCard.className = 'flowchart-def-card';
                        defCard.innerHTML = `
                            <span class="def-icon">📖</span>
                            <div class="def-body">
                                <strong class="def-label">Definition</strong>
                                <p class="def-text">${data.definition.replace(/</g,'&lt;').replace(/>/g,'&gt;')}</p>
                            </div>`;
                        flowchart.appendChild(defCard);
                    }

                    // ── SVG wrapper ──────────────────────────────────
                    const svgWrap = document.createElement('div');
                    svgWrap.className = 'flowchart-svg-wrap';
                    svgWrap.innerHTML = data.flowchart_svg;
                    flowchart.appendChild(svgWrap);

                    flowchart.hidden = false;
                }
                if (actions) actions.hidden = false;
                if (flowchartDownload) flowchartDownload.hidden = false;
                if (imageLink) imageLink.hidden = true;
                currentImageUrl = '';
                showToast('Flowchart generated.', 'success');
                return;
            }

            currentImageUrl = data.image_url;

            preview.src = currentImageUrl;
            preview.onload = () => {
                if (loader) loader.hidden = true;
                preview.hidden = false;
                if (actions) actions.hidden = false;
            };
            preview.onerror = () => {
                if (loader) loader.hidden = true;
                showToast('The image service returned a URL, but preview loading failed.', 'error');
            };

            const link = document.getElementById('image-download-link');
            if (link) link.href = currentImageUrl;
            showToast('Image request sent.', 'success');
        } catch (error) {
            if (loader) loader.hidden = true;
            showToast(`Image generation failed: ${error.message}`, 'error');
        } finally {
            if (generateBtn) {
                generateBtn.disabled = false;
                generateBtn.classList.remove('loading');
            }
        }
    }

    async function copyImageUrl() {
        if (!currentImageUrl && !currentFlowchartSvg) return;
        try {
            await navigator.clipboard.writeText(currentImageUrl || currentFlowchartSvg);
            showToast(currentImageUrl ? 'Image URL copied.' : 'Flowchart SVG copied.', 'success');
        } catch (error) {
            showToast('Could not copy visual output.', 'error');
        }
    }

    function downloadFlowchart() {
        if (!currentFlowchartSvg) return;
        const blob = new Blob([currentFlowchartSvg], { type: 'image/svg+xml' });
        const url = URL.createObjectURL(blob);
        const anchor = document.createElement('a');
        anchor.href = url;
        anchor.download = 'agentforge-flowchart.svg';
        anchor.click();
        URL.revokeObjectURL(url);
    }

    async function handleCopyReport() {
        const success = await ReportViewer.copyReport();
        showToast(success ? 'Report copied.' : 'No report to copy.', success ? 'success' : 'error');
    }

    function handleDownloadReadme() {
        ReportViewer.downloadReadme();
        showToast('README.md downloaded.', 'success');
    }

    async function handleDownloadPdf() {
        try {
            const downloaded = await ReportViewer.downloadPdf(apiUrl('/api/research/export/pdf'));
            showToast(downloaded ? 'PDF downloaded.' : 'No report to download.', downloaded ? 'success' : 'error');
        } catch (error) {
            showToast(error.message || 'Could not create the PDF export.', 'error');
        }
    }

    function setLoadingState(loading) {
        isResearching = loading;
        const button = document.getElementById('submit-btn');
        if (!button) return;
        button.disabled = loading;
        button.classList.toggle('loading', loading);
    }

    function setDocLoading(loading) {
        const button = document.getElementById('btn-doc-ask');
        const spinner = document.getElementById('doc-spinner');
        const text = document.getElementById('doc-ask-text');
        if (button) button.disabled = loading;
        if (spinner) spinner.classList.toggle('visible', loading);
        if (text) text.textContent = loading ? 'Thinking' : 'Ask';
    }

    function setUploadProgress(visible, percent = 0, label = '') {
        const container = document.getElementById('upload-progress');
        const fill = document.getElementById('progress-fill');
        const labelEl = document.getElementById('progress-label');
        if (container) container.hidden = !visible;
        if (fill) fill.style.width = visible ? `${percent}%` : '0%';
        if (labelEl && label) labelEl.textContent = label;

        if (visible && fill) {
            window.setTimeout(() => {
                if (!container.hidden) fill.style.width = '82%';
            }, 350);
        }
    }

    function setSystemStatus(state, message) {
        const dot = document.getElementById('status-dot');
        const text = document.getElementById('status-text');
        if (dot) {
            dot.className = 'status-dot';
            dot.classList.add(state === 'running' ? 'running' : state === 'error' ? 'error' : 'idle');
        }
        if (text) text.textContent = message || 'System ready';
    }

    function showWelcomeState() {
        const welcome = document.getElementById('welcome-state');
        if (welcome) welcome.hidden = false;
    }

    function hideWelcomeState() {
        const welcome = document.getElementById('welcome-state');
        if (welcome) welcome.hidden = true;
    }

    function showToast(message, type = 'info') {
        const container = document.getElementById('toast-container');
        if (!container) return;

        const icons = { success: 'OK', error: '!', info: 'i' };
        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.innerHTML = `
            <span class="toast-icon">${icons[type] || icons.info}</span>
            <span class="toast-message">${escapeHtml(message)}</span>
            <button class="toast-close" type="button" aria-label="Dismiss" onclick="this.parentElement.remove()">x</button>
        `;
        container.appendChild(toast);
        window.setTimeout(() => toast.remove(), 5200);
    }

    async function readJsonResponse(response) {
        const data = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(data.detail || data.message || `Request failed with ${response.status}`);
        }
        return data;
    }

    function apiUrl(path) {
        return `${API_BASE}${path}`;
    }

    function renderMarkdown(markdown) {
        if (typeof marked === 'undefined') return escapeHtml(markdown);
        try {
            return marked.parse(markdown || '');
        } catch (error) {
            return escapeHtml(markdown || '');
        }
    }

    function parseJsonIfNeeded(value) {
        if (!value) return [];
        if (Array.isArray(value)) return value;
        try {
            return JSON.parse(value);
        } catch (error) {
            return [];
        }
    }

    function setText(id, value) {
        const el = document.getElementById(id);
        if (el) el.textContent = value;
    }

    function truncate(value, maxLen) {
        return value.length > maxLen ? `${value.slice(0, maxLen - 3)}...` : value;
    }

    function formatDateTime(value) {
        if (!value) return '-';
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) return '-';
        return date.toLocaleDateString('en-US', { month: 'short', day: 'numeric' });
    }

    function formatBytes(bytes) {
        const size = Number(bytes || 0);
        if (size < 1024) return `${size} B`;
        if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
        return `${(size / (1024 * 1024)).toFixed(1)} MB`;
    }

    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = String(text ?? '');
        return div.innerHTML;
    }

    function escapeAttr(text) {
        return String(text ?? '')
            .replace(/&/g, '&amp;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');
    }

    document.addEventListener('DOMContentLoaded', init);

    return {
        attachFileToTextarea,
        askQuickDocQuestion,
        copyImageUrl,
        deleteCurrentDoc,
        fillImagePrompt,
        fillPrompt,
        handleDragLeave,
        handleDragOver,
        handleFileDrop,
        handleFileSelect,
        handleImageGenSubmit,
        downloadFlowchart,
        generateCurrentDocReport,
        loadDocuments,
        loadHistoryItem,
        launchFromVisualCommand,
        selectDocumentById,
        selectDocument,
        setDepth,
        showToast,
        startResearch,
        submitDocQuestion,
        syncResearchPrompt,
        switchMode,
        triggerFileInput,
    };
})();

window.switchMode = App.switchMode;
window.fillPrompt = App.fillPrompt;
window.fillImagePrompt = App.fillImagePrompt;
window.syncResearchPrompt = App.syncResearchPrompt;
window.setDepth = App.setDepth;
window.launchFromVisualCommand = App.launchFromVisualCommand;
window.attachFileToTextarea = App.attachFileToTextarea;
window.triggerFileInput = App.triggerFileInput;
window.handleDragOver = App.handleDragOver;
window.handleDragLeave = App.handleDragLeave;
window.handleFileDrop = App.handleFileDrop;
window.handleFileSelect = App.handleFileSelect;
window.deleteCurrentDoc = App.deleteCurrentDoc;
window.askQuickDocQuestion = App.askQuickDocQuestion;
window.submitDocQuestion = App.submitDocQuestion;
window.handleImageGenSubmit = App.handleImageGenSubmit;
window.copyImageUrl = App.copyImageUrl;
window.downloadFlowchart = App.downloadFlowchart;
window.generateCurrentDocReport = App.generateCurrentDocReport;
window.loadDocuments = App.loadDocuments;
