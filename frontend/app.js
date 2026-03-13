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

document.getElementById('clear-logs').addEventListener('click', () => {
    consoleOutput.innerHTML = '';
    logToConsole('Console cleared.', 'sys');
});

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

async function loadPolicy() {
    try {
        const res = await fetch(`${API_BASE}/policy`);
        const data = await res.json();
        
        policySummary.innerHTML = `
            <li><i class="ri-global-line"></i><div><strong>Platforms</strong>${data.platform_restrictions.join(', ')}</div></li>
            <li><i class="ri-check-double-line"></i><div><strong>Allowed Actions</strong>${data.allowed_actions.join(', ')}</div></li>
            <li><i class="ri-close-circle-line"></i><div><strong>Forbidden</strong>${data.forbidden_actions.join(', ')}</div></li>
            <li><i class="ri-speed-up-line"></i><div><strong>Rates</strong>${data.max_posts_per_day} posts/day, ${data.max_replies_per_hour} replies/hr</div></li>
        `;
    } catch (err) {
        policySummary.innerHTML = '<li>Error loading policy</li>';
    }
}

async function submitTask(instruction, endpoint = '/task') {
    input.value = instruction;
    submitBtn.disabled = true;
    resetPipeline();
    logToConsole(`New instruction: "${instruction}"`, 'sys');
    
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
                        
                    }, 800);
                }, 800);
            }, 800);
        }, 600);
        
    } catch (err) {
        console.error(err);
        pipelineStatus.textContent = 'Error';
        pipelineStatus.className = 'badge error';
        logToConsole(`System Error: ${err.message}`, 'block');
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

// Init
window.addEventListener('DOMContentLoaded', () => {
    loadPolicy();
    logToConsole('UI loaded. Backend metrics synchronized.', 'sys');
});
