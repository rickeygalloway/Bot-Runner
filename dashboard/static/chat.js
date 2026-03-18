/**
 * dashboard/static/chat.js
 * Claude-powered chat for BotRunner — streams responses via SSE from /api/chat.
 */

const _chatHistory = [];

function chatKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault();
    sendChat();
  }
}

function clearChat() {
  _chatHistory.length = 0;
  const msgs = document.getElementById('chat-messages');
  msgs.innerHTML =
    '<p class="text-base-content/30 text-xs text-center font-mono mt-2" id="chat-placeholder">' +
    'Ask anything &mdash; "Why did stock screener fail?" &middot; "What\'s my most expensive bot?"' +
    '</p>';
}

async function sendChat() {
  const input = document.getElementById('chat-input');
  const sendBtn = document.getElementById('chat-send-btn');
  const text = input.value.trim();
  if (!text || sendBtn.disabled) return;

  // Remove placeholder on first message
  const placeholder = document.getElementById('chat-placeholder');
  if (placeholder) placeholder.remove();

  input.value = '';
  input.disabled = true;
  sendBtn.disabled = true;
  sendBtn.textContent = '...';

  _chatHistory.push({ role: 'user', content: text });
  _appendMsg('user', text);

  // Assistant bubble starts empty with a thinking indicator
  const assistantWrapper = _appendMsg('assistant', '');
  const contentEl = assistantWrapper.querySelector('.chat-content');

  const thinkingEl = document.createElement('span');
  thinkingEl.className = 'opacity-40 italic';
  thinkingEl.textContent = 'thinking...';
  contentEl.appendChild(thinkingEl);

  const msgs = document.getElementById('chat-messages');
  let responseText = '';

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ messages: _chatHistory }),
    });

    if (!resp.ok) {
      const detail = await resp.text();
      throw new Error(`HTTP ${resp.status}: ${detail}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop(); // hold incomplete line for next chunk

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue;
        const raw = line.slice(6);
        if (raw === '[DONE]') continue;

        let parsed;
        try { parsed = JSON.parse(raw); } catch { continue; }

        if (parsed.error) {
          thinkingEl.remove();
          contentEl.textContent = 'Error: ' + parsed.error;
          break;
        }

        if (parsed.text) {
          // Remove thinking indicator on first text token
          if (thinkingEl.parentNode) thinkingEl.remove();
          responseText += parsed.text;
          contentEl.textContent = responseText;
          msgs.scrollTop = msgs.scrollHeight;
        }
      }
    }

    if (responseText) {
      _chatHistory.push({ role: 'assistant', content: responseText });
    } else if (thinkingEl.parentNode) {
      thinkingEl.textContent = '(no response)';
    }

  } catch (err) {
    if (thinkingEl.parentNode) thinkingEl.remove();
    contentEl.textContent = 'Error: ' + err.message;
  } finally {
    sendBtn.disabled = false;
    sendBtn.textContent = 'SEND';
    input.disabled = false;
    input.focus();
  }
}

function _appendMsg(role, text) {
  const msgs = document.getElementById('chat-messages');

  const wrapper = document.createElement('div');
  wrapper.className = role === 'user' ? 'flex justify-end' : 'flex justify-start';

  const bubble = document.createElement('div');
  bubble.className =
    'chat-content font-mono text-sm whitespace-pre-wrap rounded-xl px-3 py-2 ' +
    (role === 'user'
      ? 'bg-accent/15 text-accent-content'
      : 'bg-base-300 text-base-content');
  bubble.style.maxWidth = '80%';
  bubble.textContent = text;

  wrapper.appendChild(bubble);
  msgs.appendChild(wrapper);
  msgs.scrollTop = msgs.scrollHeight;
  return wrapper;
}
