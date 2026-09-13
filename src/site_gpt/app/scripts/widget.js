(function () {
  // ================= CONFIG =================
  const DEFAULT_CONFIG = {
    apiUrl: '',
    website_id: '',
    botName: 'Assistant',
    position: 'bottom-right',
    width: '360px',
    height: '480px',
    theme: {
      primaryColor: '#4c74af',
      backgroundColor: '#ffffff',
    },
    footerColor: '#4c74af',
    placeholder: 'Type a message...',
    welcomeMessage: 'Hi 👋 How can I help you?',
    enableHistory: true,
    suggestedQuestions: [],
  };

  const config = Object.assign(
    {},
    DEFAULT_CONFIG,
    window.ChatWidgetConfig || {},
  );
  const hasWebsiteId = !!config.website_id;

  // ================= SESSION =================
  function newSession() {
    const id = crypto.randomUUID();
    localStorage.setItem('chat_widget_session', id);
    localStorage.removeItem('chat_widget_history');
    return id;
  }

  let sessionId = localStorage.getItem('chat_widget_session') || newSession();

  // ================= ROOT =================
  const container = document.createElement('div');
  container.style.position = 'fixed';
  container.style.zIndex = '9999';
  container.style.bottom = '20px';
  container.style[config.position === 'bottom-left' ? 'left' : 'right'] =
    '20px';
  document.body.appendChild(container);

  const shadow = container.attachShadow({ mode: 'open' });

  // ================= UI =================
  shadow.innerHTML = `
    <style>
      .chat-toggle {
        background: ${config.theme.primaryColor};
        color: white;
        border: none;
        border-radius: 50%;
        width: 52px;
        height: 52px;
        cursor: pointer;
        font-size: 22px;
      }

      .chat-box {
        display: none;
        flex-direction: column;
        width: ${config.width};
        height: ${config.height};
        background: ${config.theme.backgroundColor};
        border-radius: 12px;
        box-shadow: 0 6px 18px rgba(0,0,0,0.2);
        overflow: hidden;
        margin-bottom: 10px;
        font-family: Arial, sans-serif;
      }

      .chat-header {
        background: ${config.theme.primaryColor};
        color: white;
        padding: 10px;
        display: flex;
        justify-content: space-between;
        align-items: center;
      }

      .clear-btn {
        background: white;
        color: ${config.theme.primaryColor};
        border: none;
        padding: 4px 8px;
        border-radius: 6px;
        cursor: pointer;
        font-size: 12px;
      }

      .chat-messages {
        flex: 1;
        overflow-y: auto;
        padding: 10px;
      }

      .chat-input {
        display: flex;
        border-top: 1px solid #ddd;
        background: ${config.footerColor};
      }

      .chat-input input {
        flex: 1;
        border: none;
        padding: 10px;
        outline: none;
        background: transparent;
      }

      .chat-input button {
        background: ${config.theme.primaryColor};
        color: white;
        border: none;
        padding: 10px 14px;
        cursor: pointer;
      }

      .row {
        display: flex;
        margin-bottom: 8px;
      }

      .row.user {
        justify-content: flex-end;
      }

      .avatar {
        width: 28px;
        height: 28px;
        margin: 0 6px;
      }

      .bubble {
        padding: 8px 10px;
        border-radius: 10px;
        max-width: 75%;
        font-size: 14px;
        word-break: break-word;
        background: #f1f1f1;
      }

      .user .bubble {
        background: #DCF8C6;
      }

      .bot .bubble {
        background: #f1f1f1;
      }

      .thinking {
        font-style: italic;
        opacity: 0.7;
      }

      .sources {
        margin-top: 6px;
        max-width: 80%;
        font-size: 12px;
        color: #555;
        line-height: 1.5;
      }

      .sources a {
        color: ${config.theme.primaryColor};
        word-break: break-word;
      }

      .feedback {
        margin-top: 4px;
        display: flex;
        gap: 6px;
        align-items: center;
      }

      .feedback button {
        border: 1px solid #ccc;
        background: #fff;
        border-radius: 6px;
        cursor: pointer;
        padding: 2px 8px;
        font-size: 13px;
      }

      .feedback button:disabled {
        opacity: 0.5;
        cursor: default;
      }

      .feedback .thanks {
        font-size: 12px;
        color: #888;
      }

      .suggestions {
        display: flex;
        flex-wrap: wrap;
        gap: 6px;
        margin: 4px 0 10px 40px;
      }

      .suggestions button {
        border: 1px solid ${config.theme.primaryColor};
        color: ${config.theme.primaryColor};
        background: #fff;
        border-radius: 14px;
        padding: 4px 10px;
        font-size: 12px;
        cursor: pointer;
      }

      pre {
        background: #222;
        color: #eee;
        padding: 8px;
        border-radius: 6px;
        overflow-x: auto;
      }

      code {
        background: #eee;
        padding: 2px 4px;
        border-radius: 4px;
      }

      a {
        color: blue;
      }
    </style>

    <div class="chat-box" id="chatBox">
      <div class="chat-header">
        <span id="chatHeaderName">${config.botName}</span>
        <button class="clear-btn" id="clearBtn">Clear</button>
      </div>
      <div class="chat-messages" id="messages"></div>
      <div class="chat-input">
        <input id="input" placeholder="${config.placeholder}" />
        <button id="sendBtn">Send</button>
      </div>
    </div>

    <button class="chat-toggle" id="toggleBtn">💬</button>
  `;

  const chatBox = shadow.getElementById('chatBox');
  const toggleBtn = shadow.getElementById('toggleBtn');
  const messagesEl = shadow.getElementById('messages');
  const inputEl = shadow.getElementById('input');
  const sendBtn = shadow.getElementById('sendBtn');
  const clearBtn = shadow.getElementById('clearBtn');
  const headerNameEl = shadow.getElementById('chatHeaderName');

  // ================= SCROLL =================
  function scrollToBottom(force = false) {
    requestAnimationFrame(() => {
      setTimeout(
        () => {
          messagesEl.scrollTop = messagesEl.scrollHeight;
        },
        force ? 0 : 50,
      );
    });
  }

  // ================= MARKDOWN =================
  function renderMarkdown(text) {
    return text
      .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\[(.*?)\]\((.*?)\)/g, '<a href="$2" target="_blank">$1</a>')
      .replace(/\n/g, '<br>');
  }

  // ================= MESSAGE =================
  function addMessage(text, role, isThinking = false, skipScroll = false) {
    const row = document.createElement('div');
    row.className = `row ${role}`;

    const avatar = document.createElement('div');
    avatar.className = 'avatar';
    avatar.textContent = role === 'user' ? '👤' : '🤖';

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    if (isThinking) {
      bubble.textContent = 'Thinking...';
      bubble.classList.add('thinking');
    } else {
      bubble.innerHTML = renderMarkdown(text);
    }

    if (role === 'user') {
      row.appendChild(bubble);
      row.appendChild(avatar);
    } else {
      row.appendChild(avatar);
      row.appendChild(bubble);
    }

    messagesEl.appendChild(row);

    if (!skipScroll) {
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    return row;
  }

  // Append cited sources + feedback buttons under a bot message row.
  function attachExtras(row, sources) {
    // Sources
    if (sources && sources.length > 0) {
      const src = document.createElement('div');
      src.className = 'sources';
      let html = '<strong>Sources:</strong> ';
      html += sources
        .map((s) => {
          const label = s.title || s.url || 'document';
          if (s.url) {
            return `<a href="${s.url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
          }
          return `<span>${label}</span>`;
        })
        .join(', ');
      src.innerHTML = html;
      row.appendChild(src);
    }

    // Feedback (only once)
    if (row.querySelector('.feedback')) return;
    const fb = document.createElement('div');
    fb.className = 'feedback';
    const up = document.createElement('button');
    up.textContent = '👍';
    up.title = 'Helpful';
    const down = document.createElement('button');
    down.textContent = '👎';
    down.title = 'Not helpful';
    const thanks = document.createElement('span');
    thanks.className = 'thanks';
    thanks.style.display = 'none';
    thanks.textContent = 'Thanks for the feedback!';

    const send = (rating) => {
      up.disabled = true;
      down.disabled = true;
      thanks.style.display = 'inline';
      const base = (config.apiUrl || '').replace(/\/$/, '');
      fetch(`${base}/api/chat/feedback`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          website_id: config.website_id,
          session_id: sessionId,
          rating,
        }),
      }).catch(() => {});
    };

    up.onclick = () => send('up');
    down.onclick = () => send('down');
    fb.appendChild(up);
    fb.appendChild(down);
    fb.appendChild(thanks);
    row.appendChild(fb);
  }

  // ================= HISTORY =================
  function saveHistory(role, text) {
    if (!config.enableHistory) return;
    const history = JSON.parse(
      localStorage.getItem('chat_widget_history') || '[]',
    );
    history.push({ role, text });
    localStorage.setItem('chat_widget_history', JSON.stringify(history));
  }

  function loadHistory() {
    if (!config.enableHistory) return;

    const history = JSON.parse(
      localStorage.getItem('chat_widget_history') || '[]',
    );

    history.forEach((msg) => {
      addMessage(msg.text, msg.role, false, true); // skip scroll
    });
  }

  function renderSuggestions() {
    if (!config.suggestedQuestions || config.suggestedQuestions.length === 0)
      return;
    if (messagesEl.children.length > 0) return;
    const wrap = document.createElement('div');
    wrap.className = 'suggestions';
    config.suggestedQuestions.forEach((q) => {
      const btn = document.createElement('button');
      btn.textContent = q;
      btn.onclick = () => sendMessage(q);
      wrap.appendChild(btn);
    });
    messagesEl.appendChild(wrap);
  }

  // ================= SEND =================
  async function sendMessage(prefillText) {
    const text = (prefillText || inputEl.value || '').trim();
    if (!text) return;

    inputEl.value = '';

    addMessage(text, 'user');
    saveHistory('user', text);

    inputEl.disabled = true;
    sendBtn.disabled = true;

    const thinkingRow = addMessage('', 'bot', true);
    const thinkingMsg = thinkingRow.querySelector('.bubble');

    try {
      const base = (config.apiUrl || '').replace(/\/$/, '');
      const res = await fetch(`${base}/api/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: text,
          website_id: config.website_id,
          session_id: sessionId,
        }),
      });

      if (!res.ok || !res.body) {
        throw new Error('chat request failed');
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let reply = '';
      let pendingSources = [];

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() || '';

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload) continue;
          try {
            const data = JSON.parse(payload);
            if (typeof data.chunk === 'string') reply += data.chunk;
            else if (typeof data.error === 'string')
              reply += (reply ? '\n\n' : '') + '⚠️ ' + data.error;
            else if (data.done === true && Array.isArray(data.sources))
              pendingSources = data.sources;
          } catch (e) {
            // ignore malformed SSE line
          }
        }
      }

      thinkingMsg.innerHTML = renderMarkdown(reply || 'No response');
      thinkingMsg.classList.remove('thinking');
      attachExtras(thinkingRow, pendingSources);

      scrollToBottom();
      saveHistory('bot', reply);
    } catch (err) {
      thinkingMsg.textContent = 'Error!';
    }

    inputEl.disabled = false;
    sendBtn.disabled = false;
    inputEl.focus();
  }

  // ================= CLEAR =================
  clearBtn.onclick = () => {
    sessionId = newSession();
    messagesEl.innerHTML = '';
    addMessage(config.welcomeMessage, 'bot');
    renderSuggestions();
  };

  // ================= EVENTS =================
  sendBtn.onclick = () => sendMessage();
  inputEl.addEventListener('keypress', (e) => {
    if (e.key === 'Enter') sendMessage();
  });

  toggleBtn.onclick = () => {
    const isOpen = chatBox.style.display === 'flex';

    chatBox.style.display = isOpen ? 'none' : 'flex';

    if (!isOpen) {
      scrollToBottomForce();
    }
  };

  function scrollToBottomForce() {
    requestAnimationFrame(() => {
      requestAnimationFrame(() => {
        const last = messagesEl.lastElementChild;
        if (last) {
          last.scrollIntoView({ behavior: 'auto', block: 'end' });
        }
      });
    });
  }

  // ================= SERVER CONFIG =================
  async function loadServerConfig() {
    if (!hasWebsiteId || !config.apiUrl) return;
    try {
      const base = config.apiUrl.replace(/\/$/, '');
      const res = await fetch(
        `${base}/api/widget-config?website_id=${encodeURIComponent(config.website_id)}`,
      );
      if (!res.ok) return;
      const cfg = await res.json();
      if (cfg.assistant_name) config.botName = cfg.assistant_name;
      if (cfg.widget_header_color) config.theme.primaryColor = cfg.widget_header_color;
      if (cfg.widget_footer_color) config.footerColor = cfg.widget_footer_color;
      if (cfg.widget_position) config.position = cfg.widget_position;
      if (cfg.greeting_message) config.welcomeMessage = cfg.greeting_message;
      if (cfg.placeholder_text) config.placeholder = cfg.placeholder_text;
      if (cfg.suggested_questions)
        config.suggestedQuestions = String(cfg.suggested_questions)
          .split('\n')
          .map((s) => s.trim())
          .filter(Boolean);

      // Apply dynamic styles / labels now that config is loaded.
      headerNameEl.textContent = config.botName;
      toggleBtn.style.background = config.theme.primaryColor;
      shadow.querySelector('.chat-header').style.background =
        config.theme.primaryColor;
      shadow.querySelector('.chat-input button').style.background =
        config.theme.primaryColor;
      shadow.querySelector('.chat-input').style.background = config.footerColor;
      inputEl.placeholder = config.placeholder;
      container.style[config.position === 'bottom-left' ? 'left' : 'right'] =
        '20px';
    } catch (e) {
      // fall back to ChatWidgetConfig / defaults
    }
  }

  // ================= INIT =================
  // Restore a returning visitor's history from the server (source of truth).
  // Falls back to the local copy if the server has nothing / is unreachable.
  async function loadServerHistory() {
    if (!config.enableHistory || !hasWebsiteId || !config.apiUrl) return false;
    try {
      const base = config.apiUrl.replace(/\/$/, '');
      const res = await fetch(
        `${base}/api/conversations/${encodeURIComponent(sessionId)}` +
          `?website_id=${encodeURIComponent(config.website_id)}`,
      );
      if (!res.ok) return false;
      const data = await res.json();
      const items = data.items || [];
      if (!items.length) return false;
      items.forEach((m) => addMessage(m.message, m.role, false, true));
      return true;
    } catch (e) {
      return false;
    }
  }

  async function init() {
    if (!hasWebsiteId) {
      addMessage('Missing Website ID', 'bot');
      return;
    }

    await loadServerConfig();

    const loadedFromServer = await loadServerHistory();
    if (!loadedFromServer) loadHistory();

    if (
      !localStorage.getItem('chat_widget_initialized') &&
      messagesEl.children.length === 0
    ) {
      addMessage(config.welcomeMessage, 'bot');
      localStorage.setItem('chat_widget_initialized', 'true');
    }

    renderSuggestions();

    scrollToBottomForce();
  }

  init();
})();
