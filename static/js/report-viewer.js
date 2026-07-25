/**
 * AgentForge — Report Viewer Controller
 * Renders markdown reports, handles copy/download, and manages report metadata.
 */

const ReportViewer = (() => {

    let currentReport = null;
    let currentTaskId = null;

    /**
     * Show the report section and render the markdown content.
     */
    function showReport(data) {
        const section = document.getElementById('report-section');
        if (!section) return;

        currentReport = data.report || data.report_text || '';
        currentTaskId = data.task_id || '';

        // Render markdown
        const reportBody = document.getElementById('report-body');
        if (reportBody && currentReport) {
            reportBody.innerHTML = renderMarkdown(currentReport);
        }

        // Update metadata
        updateMeta(data);

        // Show the section
        section.classList.add('visible');

        // Smooth scroll to report
        section.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    /**
     * Hide the report section.
     */
    function hideReport() {
        const section = document.getElementById('report-section');
        if (section) {
            section.classList.remove('visible');
        }
        currentReport = null;
        currentTaskId = null;
    }

    /**
     * Update report metadata display.
     */
    function updateMeta(data) {
        const metaContainer = document.getElementById('report-meta');
        if (!metaContainer) return;

        const items = [];

        if (data.duration_seconds) {
            items.push(`<span class="report-meta-item">⏱️ ${data.duration_seconds}s</span>`);
        }

        if (data.agents_used) {
            const count = Array.isArray(data.agents_used) ? data.agents_used.length : 0;
            items.push(`<span class="report-meta-item">🤖 ${count} agents</span>`);
        }

        if (data.activity_count) {
            items.push(`<span class="report-meta-item">📡 ${data.activity_count} actions</span>`);
        }

        if (data.depth) {
            items.push(`<span class="report-meta-item">📏 ${data.depth}</span>`);
        }

        metaContainer.innerHTML = items.join('');
    }

    /**
     * Render markdown string to HTML using marked.js.
     */
    function renderMarkdown(markdown) {
        if (typeof marked === 'undefined') {
            // Fallback if marked.js isn't loaded
            return `<pre style="white-space: pre-wrap;">${escapeHtml(markdown)}</pre>`;
        }

        try {
            // Configure marked for safe rendering
            marked.setOptions({
                breaks: true,
                gfm: true,
                headerIds: true,
                mangle: false,
            });
            return marked.parse(markdown);
        } catch (e) {
            console.error('Markdown parsing error:', e);
            return `<pre style="white-space: pre-wrap;">${escapeHtml(markdown)}</pre>`;
        }
    }

    /**
     * Copy the raw markdown report to clipboard.
     */
    async function copyReport() {
        if (!currentReport) return;

        try {
            await navigator.clipboard.writeText(currentReport);
            return true;
        } catch (e) {
            // Fallback for older browsers
            const textarea = document.createElement('textarea');
            textarea.value = currentReport;
            textarea.style.position = 'fixed';
            textarea.style.opacity = '0';
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            return true;
        }
    }

    /**
     * Download the report as a markdown file.
     */
    function downloadReport() {
        if (!currentReport) return;

        const filename = `research_report_${currentTaskId || 'export'}.md`;
        const blob = new Blob([currentReport], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);

        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        a.click();

        URL.revokeObjectURL(url);
    }

    /**
     * Escape HTML entities.
     */
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }

    // Public API
    return {
        showReport,
        hideReport,
        copyReport,
        downloadReport,
        renderMarkdown,
    };
})();
