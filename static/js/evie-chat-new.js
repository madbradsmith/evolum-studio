(function () {
    'use strict';

    // ── Helper: strip tags from display text ──
    function stripTags(text) {
        return (text || '')
            .replace(/\[(REMEMBER|MOOD|CALL|ANCHOR|MODE|CONTINUE):[^\]]*\]/gi, '')
            .replace(/\[CONTINUE\]/gi, '')
            .trim();
    }

    document.addEventListener('DOMContentLoaded', () => {
        // Detect Filmmaker Workspace or Self-Tape Room panel
        const wsPanel = document.querySelector('.ws-evie');
        const coachPanel = document.querySelector('.evie-coach');

        if (!wsPanel && !coachPanel) return;

        const isWorkspace = !!wsPanel;
        const panel = isWorkspace ? wsPanel : coachPanel;

        // ── Form selectors based on page type ──
        const inputEl = panel.querySelector(isWorkspace ? '.ws-evie-input' : '.evie-input');
        const sendBtn = panel.querySelector(isWorkspace ? '.ws-evie-send' : null);
        const feedEl = panel.querySelector(isWorkspace ? '.ws-evie-body' : '.evie-body');
        const statusEl = panel.querySelector(isWorkspace ? '.ws-evie-status' : '.evie-status');

        if (!inputEl || !feedEl) return;

        const conversation = [];
        let userName = '';
        let projects = window.EVOLUM_PROJECTS || [];
        let busy = false;

        // Bootstrap greeting or fetch current name
        fetch('/api/auth/me', { credentials: 'same-origin' })
            .then(res => res.ok ? res.json() : null)
            .then(data => {
                if (data) {
                    userName = data.user_name || data.name || data.user_email || '';
                }
                initGreeting();
            })
            .catch(() => {
                initGreeting();
            });

        function initGreeting() {
            // Read initial message from HTML if present to keep design pristine, or push first greet
            const firstMsgEl = feedEl.querySelector(isWorkspace ? '.ev-msg' : '.evie-message');
            if (firstMsgEl) {
                const txtEl = firstMsgEl.querySelector(isWorkspace ? '.txt' : '.evie-message-text');
                if (txtEl) {
                    conversation.push({ role: 'assistant', content: txtEl.textContent.trim() });
                }
            }
        }

        // ── Append Bubble Helper ──
        function appendBubble(role, text, thinking) {
            const isUser = role === 'user';
            
            // Remove initial suggest chips from feed when user sends their first message
            if (isUser) {
                const suggestRow = feedEl.querySelector(isWorkspace ? '.ev-suggest' : '.evie-cta-row');
                if (suggestRow) suggestRow.remove();
            }

            const wrap = document.createElement('div');
            if (isWorkspace) {
                wrap.className = 'ev-msg' + (isUser ? ' ev-msg-user' : '');
                if (thinking) wrap.style.opacity = '0.5';
                wrap.innerHTML = `
                    <div class="meta">${isUser ? 'You' : 'Evie'} · now</div>
                    <div class="txt">${text}</div>
                `;
            } else {
                wrap.className = 'evie-message' + (isUser ? ' evie-message-user' : '');
                if (thinking) wrap.style.opacity = '0.5';
                wrap.innerHTML = `
                    <div class="evie-message-meta">${isUser ? 'You' : 'Evie'} · now</div>
                    <div class="evie-message-text">${text}</div>
                `;
            }

            feedEl.appendChild(wrap);
            feedEl.scrollTop = feedEl.scrollHeight;
            return wrap.querySelector(isWorkspace ? '.txt' : '.evie-message-text');
        }

        // ── Stream / Send Logic ──
        async function send() {
            const msg = inputEl.value.trim();
            if (!msg || busy) return;
            busy = true;

            if (sendBtn) sendBtn.disabled = true;
            inputEl.value = '';
            inputEl.style.height = '';

            conversation.push({ role: 'user', content: msg });
            appendBubble('user', msg);

            const origStatus = statusEl.textContent;
            statusEl.textContent = 'thinking…';
            const evieBubble = appendBubble('evie', '…', true);

            let fullText = '';
            try {
                const resp = await fetch('/api/evie/workspace/stream', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        messages: conversation,
                        user_name: userName,
                        projects: projects.map(p => ({
                            id: p.id, title: p.title,
                            type: p.project_type || p.type || '', status: p.status || p.statusLabel || ''
                        }))
                    })
                });

                if (!resp.ok) throw new Error(`HTTP ${resp.status}`);

                const reader = resp.body.getReader();
                const decoder = new TextDecoder();
                let firstChunk = true;

                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;

                    const lines = decoder.decode(value, { stream: true }).split('\n');
                    for (const line of lines) {
                        if (!line.startsWith('data: ')) continue;
                        const data = line.slice(6).trim();
                        if (data === '[DONE]') break;
                        try {
                            const obj = JSON.parse(data);
                            if (obj.text) {
                                if (firstChunk) {
                                    evieBubble.textContent = '';
                                    firstChunk = false;
                                }
                                fullText += obj.text;
                                evieBubble.textContent = stripTags(fullText);
                                feedEl.scrollTop = feedEl.scrollHeight;
                            }
                        } catch (e) {}
                    }
                }
            } catch (e) {
                evieBubble.textContent = 'Something went wrong — try again.';
            }

            if (fullText) {
                const clean = stripTags(fullText);
                evieBubble.textContent = clean;
                evieBubble.parentElement.style.opacity = '';
                conversation.push({ role: 'assistant', content: fullText });

                // Handle preferred name identity hooks
                const callMatch = fullText.match(/\[CALL:([^\]]+)\]/i);
                if (callMatch) {
                    const callName = callMatch[1].trim();
                    try { localStorage.setItem('evie_call_name', callName); } catch (e) {}
                    fetch('/api/evie/anchor', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ preferred_name: callName }),
                    }).catch(() => {});
                }

                // Handle anchor phrases
                const anchorMatch = fullText.match(/\[ANCHOR:([^\]]+)\]/i);
                if (anchorMatch) {
                    fetch('/api/evie/anchor', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ anchor_phrase: anchorMatch[1].trim() }),
                    }).catch(() => {});
                }
            }

            statusEl.textContent = origStatus;
            busy = false;
            if (sendBtn) sendBtn.disabled = false;
            inputEl.focus();
        }

        // ── Event Handlers ──
        inputEl.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                send();
            }
        });

        if (sendBtn) {
            sendBtn.addEventListener('click', send);
        }

        // Wire suggestion chips initially
        function wireChips() {
            const chips = panel.querySelectorAll(isWorkspace ? '.ev-chip' : '.evie-chip');
            chips.forEach(b => {
                b.addEventListener('click', () => {
                    const text = b.textContent.replace(/^(Idea|Script|Brief|Tool)/, '').trim();
                    inputEl.value = text;
                    send();
                });
            });
        }
        wireChips();
    });
})();
