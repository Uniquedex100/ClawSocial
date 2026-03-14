/**
 * ClawSocial Frontend JS Logic
 */

const API_BASE = '/api';

// UI Elements
const form = document.getElementById('task-form');
const input = document.getElementById('task-instruction');
const submitBtn = document.getElementById('btn-submit');
const consoleOutput = document.getElementById('console-output');
const policySummary = document.getElementById('policy-summary');
const pipelineStatus = document.getElementById('pipeline-status');
const navItems = document.querySelectorAll('.nav-item[data-view]');
const appViews = {
    dashboard: document.getElementById('view-dashboard'),
    policy: document.getElementById('view-policy'),
    logs: document.getElementById('view-logs')
};

// Policy View Elements
const policyJson = document.getElementById('policy-json');
const policyStructured = document.getElementById('policy-structured');
const policyEditor = document.getElementById('policy-editor');
const policySaveStatus = document.getElementById('policy-save-status');
const policyRefreshBtn = document.getElementById('policy-refresh-btn');
const policySaveBtn = document.getElementById('policy-save-btn');

// Audit Logs View Elements
const auditLogsList = document.getElementById('audit-logs-list');
const auditLogsEmpty = document.getElementById('audit-logs-empty');
const logsRefreshBtn = document.getElementById('logs-refresh-btn');
const logsExportBtn = document.getElementById('logs-export-btn');
const logsClearBtn = document.getElementById('logs-clear-btn');

// Chat View Elements
const chatThread = document.getElementById('chat-thread');
const clearChatBtn = document.getElementById('clear-chat');

// Pipeline Stages
const stages = {
    intent: document.getElementById('stage-intent'),
    reasoning: document.getElementById('stage-reasoning'),
    policy: document.getElementById('stage-policy'),
    executor: document.getElementById('stage-executor')
};

function logToConsole(message, type = 'info') {
    const el = document.createElement('div');
    el.className = `log-entry ${type}`;
    
    const time = new Date().toLocaleTimeString('en-US', {hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit'});
    el.textContent = `[${time}] ${message}`;
    
    consoleOutput.appendChild(el);
    consoleOutput.scrollTop = consoleOutput.scrollHeight;
}

function escapeHtml(value) {
    return String(value || '')
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function addChatMessage(role, text, options = {}) {
    if (!chatThread) return;
    const wrapper = document.createElement('div');
    wrapper.className = `chat-message ${role}`;

    const head = document.createElement('div');
    head.className = 'chat-head';

    const avatar = document.createElement('div');
    avatar.className = 'chat-avatar';
    avatar.textContent = role === 'user' ? 'You' : 'OC';

    const meta = document.createElement('div');
    meta.className = 'chat-meta';

    const roleEl = document.createElement('div');
    roleEl.className = 'chat-role';
    roleEl.textContent = role === 'user' ? 'You' : 'OpenClaw';

    const timeEl = document.createElement('div');
    timeEl.className = 'chat-time';
    timeEl.textContent = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

    meta.appendChild(roleEl);
    meta.appendChild(timeEl);
    head.appendChild(avatar);
    head.appendChild(meta);

    const bubble = document.createElement('div');
    bubble.className = 'chat-bubble';
    if (options.html === true) {
        bubble.innerHTML = text;
    } else {
        bubble.textContent = text;
    }

    wrapper.appendChild(head);
    wrapper.appendChild(bubble);
    chatThread.appendChild(wrapper);
    chatThread.scrollTop = chatThread.scrollHeight;
}

function buildAssistantReply(data) {
    if (!data) return '<div class="chat-result">No response payload received.</div>';

    const blocked = (data.policy_results || []).filter(p => p.verdict === 'BLOCK');
    const executed = data.execution_results || [];
    const sections = [];

    if (blocked.length > 0) {
        const items = blocked
            .map(item => `<li>${escapeHtml(item.reason)}</li>`)
            .join('');
        sections.push(`
            <div class="chat-section">
                <div class="chat-section-title">Blocked by policy</div>
                <ul class="chat-list">${items}</ul>
            </div>
        `);
    }

    if (executed.length > 0) {
        const execItems = executed.map(item => {
            const detail = String(item.detail || '').split('\n').filter(Boolean);
            if (detail.length <= 1) {
                return `<li>${escapeHtml(item.detail || 'Executed')}</li>`;
            }
            const headline = escapeHtml(detail[0]);
            const sub = detail
                .slice(1)
                .map(line => `<li>${escapeHtml(line.replace(/^[-•]\s*/, ''))}</li>`)
                .join('');
            return `<li>${headline}${sub ? `<ul class="chat-sub-list">${sub}</ul>` : ''}</li>`;
        }).join('');

        sections.push(`
            <div class="chat-section">
                <div class="chat-section-title">Execution results</div>
                <ul class="chat-list">${execItems}</ul>
            </div>
        `);
    }

    if (sections.length === 0) {
        sections.push('<div class="chat-result">No action was executed.</div>');
    }

    const taskId = escapeHtml(data.task_id || 'N/A');
    return `
        <div class="chat-result">
            ${sections.join('')}
            <div class="chat-task-row">
                <span class="chat-task-pill">Task ID: ${taskId}</span>
            </div>
        </div>
    `;
}

document.getElementById('clear-logs').addEventListener('click', () => {
    consoleOutput.innerHTML = '';
    logToConsole('Console cleared.', 'sys');
});

function switchView(viewName) {
    Object.entries(appViews).forEach(([key, el]) => {
        if (!el) return;
        el.classList.toggle('active', key === viewName);
        el.hidden = key !== viewName;
        el.setAttribute('aria-hidden', key === viewName ? 'false' : 'true');
    });

    navItems.forEach(item => {
        item.classList.toggle('active', item.dataset.view === viewName);
    });

    if (viewName === 'policy') {
        loadPolicy();
    }
    if (viewName === 'logs') {
        loadAuditLogs();
    }
}

function resetPipeline() {
    Object.values(stages).forEach(el => {
        el.className = 'stage';
        el.querySelector('.stage-detail').textContent = 'Waiting...';
    });
    pipelineStatus.textContent = 'Running';
    pipelineStatus.className = 'badge active';
}

function updateStage(stageId, status, detail) {
    const el = stages[stageId];
    if (el) {
        el.className = `stage ${status}`;
        if (detail) {
            el.querySelector('.stage-detail').innerHTML = detail;
        }
    }
}

function renderPolicyChips(items, tone = 'neutral') {
    if (!Array.isArray(items) || items.length === 0) {
        return '<span class="policy-chip muted">none</span>';
    }

    const prettyLabel = (value) => {
        const text = String(value || '');
        return text
            .replace(/_/g, ' ')
            .replace(/\b\w/g, (ch) => ch.toUpperCase());
    };

    return items
        .map(item => `<span class="policy-chip ${tone}" title="${item}">${prettyLabel(item)}</span>`)
        .join('');
}

function renderPolicyStructured(policy) {
    if (!policyStructured) return;

    const platformCount = Array.isArray(policy.platform_restrictions) ? policy.platform_restrictions.length : 0;
    const allowedCount = Array.isArray(policy.allowed_actions) ? policy.allowed_actions.length : 0;
    const forbiddenCount = Array.isArray(policy.forbidden_actions) ? policy.forbidden_actions.length : 0;
    const blockedWordsCount = Array.isArray(policy.blocked_words) ? policy.blocked_words.length : 0;

    policyStructured.innerHTML = `
        <section class="policy-stat-strip">
            <article class="policy-stat-card">
                <span class="policy-stat-label">Platforms</span>
                <span class="policy-stat-value">${platformCount}</span>
            </article>
            <article class="policy-stat-card">
                <span class="policy-stat-label">Allowed Actions</span>
                <span class="policy-stat-value">${allowedCount}</span>
            </article>
            <article class="policy-stat-card">
                <span class="policy-stat-label">Forbidden Actions</span>
                <span class="policy-stat-value">${forbiddenCount}</span>
            </article>
            <article class="policy-stat-card">
                <span class="policy-stat-label">Blocked Words</span>
                <span class="policy-stat-value">${blockedWordsCount}</span>
            </article>
        </section>

        <section class="policy-block">
            <h4><i class="ri-global-line"></i> Platforms</h4>
            <div class="policy-chip-row">${renderPolicyChips(policy.platform_restrictions, 'info')}</div>
        </section>

        <section class="policy-block">
            <h4><i class="ri-check-double-line"></i> Allowed Actions</h4>
            <div class="policy-chip-row">${renderPolicyChips(policy.allowed_actions, 'good')}</div>
        </section>

        <section class="policy-block">
            <h4><i class="ri-close-circle-line"></i> Forbidden Actions</h4>
            <div class="policy-chip-row">${renderPolicyChips(policy.forbidden_actions, 'bad')}</div>
        </section>

        <section class="policy-block">
            <h4><i class="ri-forbid-line"></i> Blocked Words</h4>
            <div class="policy-chip-row">${renderPolicyChips(policy.blocked_words, 'warn')}</div>
        </section>

        <section class="policy-block rates">
            <h4><i class="ri-speed-up-line"></i> Rate Limits</h4>
            <div class="rate-grid">
                <div class="rate-card">
                    <span class="rate-label">Posts / day</span>
                    <span class="rate-value">${policy.max_posts_per_day}</span>
                </div>
                <div class="rate-card">
                    <span class="rate-label">Replies / hour</span>
                    <span class="rate-value">${policy.max_replies_per_hour}</span>
                </div>
                <div class="rate-card">
                    <span class="rate-label">Batch actions / request</span>
                    <span class="rate-value">${policy.max_batch_actions ?? 3}</span>
                </div>
            </div>
        </section>

        <section class="policy-legend">
            <span><i class="ri-checkbox-circle-line"></i> Allowed Scope</span>
            <span><i class="ri-close-circle-line"></i> Explicitly Blocked</span>
            <span><i class="ri-alert-line"></i> Sensitive Keywords</span>
        </section>
    `;
}

async function loadPolicy() {
    try {
        const res = await fetch(`${API_BASE}/policy`);
        if (!res.ok) {
            throw new Error(`Policy fetch failed (${res.status})`);
        }
        const data = await res.json();
        const pretty = JSON.stringify(data, null, 2);
        renderPolicyStructured(data);
        
        policySummary.innerHTML = `
            <li><i class="ri-global-line"></i><div><strong>Platforms</strong>${data.platform_restrictions.join(', ')}</div></li>
            <li><i class="ri-check-double-line"></i><div><strong>Allowed Actions</strong>${data.allowed_actions.join(', ')}</div></li>
            <li><i class="ri-close-circle-line"></i><div><strong>Forbidden</strong>${data.forbidden_actions.join(', ')}</div></li>
            <li><i class="ri-speed-up-line"></i><div><strong>Rates</strong>${data.max_posts_per_day} posts/day, ${data.max_replies_per_hour} replies/hr, ${data.max_batch_actions ?? 3} batch/request</div></li>
        `;

        if (policyJson) {
            policyJson.textContent = pretty;
        }
        if (policyEditor) {
            policyEditor.value = pretty;
        }
        if (policySaveStatus) {
            policySaveStatus.textContent = 'Policy loaded.';
            policySaveStatus.className = 'inline-status';
        }
    } catch (err) {
        policySummary.innerHTML = '<li>Error loading policy</li>';
        if (policyStructured) {
            policyStructured.innerHTML = `<div class="empty-state">Error loading policy: ${err.message}</div>`;
        }
        if (policyJson) {
            policyJson.textContent = `Error loading policy: ${err.message}`;
        }
        if (policySaveStatus) {
            policySaveStatus.textContent = `Error: ${err.message}`;
            policySaveStatus.className = 'inline-status error';
        }
    }
}

function renderAuditLogs(logs) {
    if (!auditLogsList || !auditLogsEmpty) return;

    if (!Array.isArray(logs) || logs.length === 0) {
        auditLogsList.innerHTML = '';
        auditLogsEmpty.style.display = 'block';
        return;
    }

    auditLogsEmpty.style.display = 'none';
    auditLogsList.innerHTML = logs
        .slice()
        .reverse()
        .map(log => {
            const verdictClass = log.verdict === 'BLOCK' ? 'blocked' : 'allowed';
            const executedText = log.executed ? 'Executed' : 'Not Executed';
            const detail = log.reason || log.execution_detail || 'No detail available';
            const time = new Date(log.timestamp).toLocaleString();

            return `
                <article class="audit-item ${verdictClass}">
                    <header>
                        <span class="audit-chip ${verdictClass}">${log.verdict}</span>
                        <span class="audit-meta">${time}</span>
                    </header>
                    <div class="audit-main">
                        <div><strong>Action:</strong> ${log.action_type} on ${log.platform}</div>
                        <div><strong>Status:</strong> ${executedText}</div>
                        <div><strong>Intent:</strong> ${log.intent}</div>
                        <div><strong>Reason:</strong> ${detail}</div>
                    </div>
                </article>
            `;
        })
        .join('');
}

async function loadAuditLogs() {
    try {
        const res = await fetch(`${API_BASE}/logs`);
        if (!res.ok) {
            throw new Error(`Logs fetch failed (${res.status})`);
        }
        const logs = await res.json();
        renderAuditLogs(logs);
    } catch (err) {
        if (auditLogsList) {
            auditLogsList.innerHTML = `<div class="empty-state">Error loading logs: ${err.message}</div>`;
        }
        if (auditLogsEmpty) {
            auditLogsEmpty.style.display = 'none';
        }
    }
}

async function savePolicyFromEditor() {
    if (!policyEditor || !policySaveStatus) return;

    let payload;
    try {
        payload = JSON.parse(policyEditor.value);
    } catch (err) {
        policySaveStatus.textContent = `Invalid JSON: ${err.message}`;
        policySaveStatus.className = 'inline-status error';
        return;
    }

    policySaveStatus.textContent = 'Saving policy...';
    policySaveStatus.className = 'inline-status';

    try {
        const res = await fetch(`${API_BASE}/policy`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        });
        if (!res.ok) {
            const msg = await res.text();
            throw new Error(msg || `Save failed (${res.status})`);
        }
        const updated = await res.json();
        const pretty = JSON.stringify(updated, null, 2);
        policyEditor.value = pretty;
        if (policyJson) policyJson.textContent = pretty;
        policySaveStatus.textContent = 'Policy saved successfully.';
        policySaveStatus.className = 'inline-status success';
        logToConsole('Policy updated successfully.', 'sys');
        loadPolicy();
    } catch (err) {
        policySaveStatus.textContent = `Save failed: ${err.message}`;
        policySaveStatus.className = 'inline-status error';
    }
}

async function clearServerLogs() {
    try {
        const res = await fetch(`${API_BASE}/logs`, { method: 'DELETE' });
        if (!res.ok) {
            throw new Error(`Clear failed (${res.status})`);
        }
        logToConsole('Audit logs cleared on server.', 'sys');
        loadAuditLogs();
    } catch (err) {
        logToConsole(`Clear logs failed: ${err.message}`, 'block');
    }
}

async function exportServerLogs() {
    try {
        const res = await fetch(`${API_BASE}/logs/export`);
        if (!res.ok) {
            throw new Error(`Export failed (${res.status})`);
        }
        const data = await res.json();
        const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `clawsocial-audit-logs-${Date.now()}.json`;
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);
        logToConsole('Audit logs exported.', 'sys');
    } catch (err) {
        logToConsole(`Export failed: ${err.message}`, 'block');
    }
}

async function submitTask(instruction, endpoint = '/task') {
    input.value = instruction;
    submitBtn.disabled = true;
    resetPipeline();
    logToConsole(`New instruction: "${instruction}"`, 'sys');
    addChatMessage('user', instruction);
    
    // 1. Intent Phase (simulated typing animation for UI feel)
    updateStage('intent', 'active', 'Parsing natural language...');
    
    try {
        const res = await fetch(`${API_BASE}${endpoint}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ instruction })
        });
        
        const data = await res.json();
        
        // Show Intent
        setTimeout(() => {
            updateStage('intent', 'completed', `
                <strong>Intent:</strong> ${data.intent.intent}<br>
                <strong>Platform:</strong> ${data.intent.platform}<br>
                <strong>Actions:</strong> ${data.intent.actions_allowed.join(', ')}
            `);
            
            // Show Reasoning
            updateStage('reasoning', 'active', 'Decomposing task...');
            
            setTimeout(() => {
                const plans = data.proposals.map(p => `- ${p.action_type}`).join('<br>');
                updateStage('reasoning', 'completed', `Generated ${data.proposals.length} plan(s):<br>${plans}`);
                
                // Show Policy
                updateStage('policy', 'active', 'Evaluating ArmorClaw runtime constraints...');
                
                setTimeout(() => {
                    let anyBlocked = false;
                    let policyHtml = '';
                    
                    data.policy_results.forEach(pr => {
                        const isBlock = pr.verdict === 'BLOCK';
                        if (isBlock) anyBlocked = true;
                        
                        const color = isBlock ? '#f43f5e' : '#10b981';
                        policyHtml += `<span style="color:${color};font-weight:bold;">[${pr.verdict}]</span> ${pr.reason.split('.')[0]}<br>`;
                        
                        // Console logs
                        logToConsole(`Policy ${pr.verdict}: ${pr.reason}`, isBlock ? 'block' : 'allow');
                    });
                    
                    updateStage('policy', anyBlocked ? 'failed' : 'completed', policyHtml);
                    
                    // Show Execution
                    updateStage('executor', 'active', 'Connecting to OpenClaw gateway...');
                    
                    setTimeout(() => {
                        let execHtml = '';
                        let hasSuccess = false;
                        
                        if (data.execution_results.length === 0 && anyBlocked) {
                            execHtml = 'Skipped due to Policy Block.';
                            updateStage('executor', 'failed', execHtml);
                        } else if (data.execution_results.length === 0) {
                            execHtml = 'No actions required.';
                            updateStage('executor', 'completed', execHtml);
                        } else {
                            data.execution_results.forEach(er => {
                                execHtml += `${er.detail}<br>`;
                                if (er.success) hasSuccess = true;
                                logToConsole(`Executed: ${er.detail}`, 'exec');
                            });
                            updateStage('executor', 'completed', execHtml);
                        }
                        
                        pipelineStatus.textContent = 'Completed ' + (anyBlocked ? '(with blocks)' : '');
                        pipelineStatus.className = `badge ${anyBlocked ? 'error' : 'success'}`;
                        submitBtn.disabled = false;
                        logToConsole(`Task finished: ${data.task_id}`, 'sys');
                        addChatMessage('assistant', buildAssistantReply(data), { html: true });
                        loadAuditLogs();
                        
                    }, 800);
                }, 800);
            }, 800);
        }, 600);
        
    } catch (err) {
        console.error(err);
        pipelineStatus.textContent = 'Error';
        pipelineStatus.className = 'badge error';
        logToConsole(`System Error: ${err.message}`, 'block');
        addChatMessage('assistant', `Error: ${err.message}`);
        submitBtn.disabled = false;
    }
}

// Event Listeners
form.addEventListener('submit', (e) => {
    e.preventDefault();
    if (input.value.trim()) {
        submitTask(input.value.trim());
    }
});

document.querySelectorAll('.action-demo').forEach(btn => {
    btn.addEventListener('click', (e) => {
        const type = e.target.dataset.type;
        let endpoint = `/demo/${type}`;
        let text = '';
        if (type === 'allowed') text = "Reply to comments on Instagram today.";
        else if (type === 'blocked') text = "Post this tweet on Twitter.";
        else if (type === 'delegation') text = "Publish a new post on Instagram.";
        
        submitTask(text, endpoint);
    });
});

navItems.forEach(item => {
    item.addEventListener('click', (e) => {
        e.preventDefault();
        const view = item.dataset.view;
        if (!view) return;
        window.location.hash = view;
        switchView(view);
    });
});

if (policyRefreshBtn) {
    policyRefreshBtn.addEventListener('click', loadPolicy);
}
if (policySaveBtn) {
    policySaveBtn.addEventListener('click', savePolicyFromEditor);
}
if (logsRefreshBtn) {
    logsRefreshBtn.addEventListener('click', loadAuditLogs);
}
if (logsClearBtn) {
    logsClearBtn.addEventListener('click', clearServerLogs);
}
if (logsExportBtn) {
    logsExportBtn.addEventListener('click', exportServerLogs);
}
if (clearChatBtn && chatThread) {
    clearChatBtn.addEventListener('click', () => {
        chatThread.innerHTML = '';
        addChatMessage('assistant', 'Chat cleared. Ready for your next command.');
    });
}

window.addEventListener('hashchange', () => {
    const view = window.location.hash.replace('#', '') || 'dashboard';
    if (appViews[view]) {
        switchView(view);
    }
});

// Init
window.addEventListener('DOMContentLoaded', () => {
    const initialView = window.location.hash.replace('#', '') || 'dashboard';
    switchView(appViews[initialView] ? initialView : 'dashboard');
    loadPolicy();
    loadAuditLogs();
    logToConsole('UI loaded. Backend metrics synchronized.', 'sys');
});
