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
    requireContactInfo: true,
  };

  // ================= SANITIZE CONFIG =================
  // `botName`, `placeholder`, the colours and the dimensions are interpolated
  // into shadow.innerHTML and a form template, and into CSS. They come from the
  // owner's settings (or from a tampered /api/widget-config answer), so text is
  // escaped at those sinks and colours/sizes must match a strict pattern;
  // anything else falls back to the default, leaving valid config untouched.
  const HEX_COLOR = /^#(?:[0-9a-f]{3,4}|[0-9a-f]{6}|[0-9a-f]{8})$/i;
  const FUNC_COLOR = /^(?:rgb|hsl)a?\(\s*[0-9.,%\s/]+\)$/i;
  const DIMENSION = /^\d{1,4}(?:px|rem|em|%|vw|vh)$/i;

  function safeColor(value, fallback) {
    const candidate = String(value === null || value === undefined ? '' : value).trim();
    const allowed = HEX_COLOR.test(candidate) || FUNC_COLOR.test(candidate);
    return allowed ? candidate : fallback;
  }

  function safeDimension(value, fallback) {
    const candidate = String(value === null || value === undefined ? '' : value).trim();
    return DIMENSION.test(candidate) ? candidate : fallback;
  }

  function safeText(value, fallback, maxLength) {
    if (typeof value !== 'string') return fallback;
    const trimmed = value.trim().slice(0, maxLength || 120);
    return trimmed || fallback;
  }

  function sanitizeConfig(cfg) {
    const theme = cfg.theme || {};
    return Object.assign({}, cfg, {
      botName: safeText(cfg.botName, DEFAULT_CONFIG.botName),
      placeholder: safeText(cfg.placeholder, DEFAULT_CONFIG.placeholder, 200),
      welcomeMessage: safeText(
        cfg.welcomeMessage,
        DEFAULT_CONFIG.welcomeMessage,
        500,
      ),
      position: cfg.position === 'bottom-left' ? 'bottom-left' : 'bottom-right',
      width: safeDimension(cfg.width, DEFAULT_CONFIG.width),
      height: safeDimension(cfg.height, DEFAULT_CONFIG.height),
      footerColor: safeColor(cfg.footerColor, DEFAULT_CONFIG.footerColor),
      theme: Object.assign({}, theme, {
        primaryColor: safeColor(
          theme.primaryColor,
          DEFAULT_CONFIG.theme.primaryColor,
        ),
        backgroundColor: safeColor(
          theme.backgroundColor,
          DEFAULT_CONFIG.theme.backgroundColor,
        ),
      }),
    });
  }

  // ================= CONFIG INSTANCE =================
  const config = sanitizeConfig(
    Object.assign({}, DEFAULT_CONFIG, window.ChatWidgetConfig || {}),
  );
  const hasWebsiteId = !!config.website_id;

  // ================= SESSION =================
  function newSession() {
    const id = crypto.randomUUID();
    localStorage.setItem('chat_widget_session', id);
    localStorage.removeItem('chat_widget_history');
    localStorage.removeItem('chat_widget_contact');
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

      .contact-form {
        flex: 1;
        overflow-y: auto;
        padding: 16px 14px;
        display: flex;
        flex-direction: column;
        gap: 10px;
      }

      .contact-form p {
        font-size: 14px;
        margin: 0 0 4px;
      }

      .contact-form label {
        font-size: 12px;
        color: #555;
        display: flex;
        flex-direction: column;
        gap: 4px;
      }

      .contact-form input {
        border: 1px solid #ccc;
        border-radius: 6px;
        padding: 8px 10px;
        font-size: 14px;
        outline: none;
        width: 100%;
        box-sizing: border-box;
      }

      .contact-form .error {
        font-size: 12px;
        color: #c00;
        min-height: 16px;
      }

      .contact-form button.submit {
        background: ${config.theme.primaryColor};
        color: white;
        border: none;
        border-radius: 6px;
        padding: 10px;
        cursor: pointer;
        font-size: 14px;
      }

      .contact-form button.submit:disabled {
        opacity: 0.6;
        cursor: default;
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
        <span id="chatHeaderName">${escapeHtml(config.botName)}</span>
        <button class="clear-btn" id="clearBtn">Clear</button>
      </div>
      <div class="chat-messages" id="messages"></div>
      <div class="chat-input" id="chatInput">
        <input id="input" placeholder="${escapeHtml(config.placeholder)}" />
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
  // Everything below is untrusted: it is either model output or text taken
  // from the customer's crawled documents, and the result is assigned to
  // innerHTML. HTML is therefore escaped first and markdown is applied to the
  // escaped string, so no tag can ever be introduced by the content itself.
  function escapeHtml(text) {
    return String(text === null || text === undefined ? '' : text)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#39;');
  }

  // Only absolute http(s) links are allowed; javascript:, data:, vbscript: and
  // friends are dropped (the label is kept as plain text).
  function safeUrl(url) {
    const trimmed = String(url || '').trim();
    return /^https?:\/\//i.test(trimmed) ? trimmed : null;
  }

  function renderMarkdown(text) {
    return escapeHtml(text)
      .replace(/```([\s\S]*?)```/g, '<pre>$1</pre>')
      .replace(/`([^`]+)`/g, '<code>$1</code>')
      .replace(/\*\*(.*?)\*\*/g, '<b>$1</b>')
      .replace(/\[(.*?)\]\((.*?)\)/g, (match, label, href) => {
        const url = safeUrl(href);
        if (!url) return label;
        return `<a href="${url}" target="_blank" rel="noopener noreferrer">${label}</a>`;
      })
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
      // Built with DOM nodes (textContent), never innerHTML: source titles come
      // from the customer's crawled pages and are untrusted.
      const heading = document.createElement('strong');
      heading.textContent = 'Sources:';
      src.appendChild(heading);
      src.appendChild(document.createTextNode(' '));
      sources.forEach((s, index) => {
        if (index > 0) src.appendChild(document.createTextNode(', '));
        const label = s.title || s.url || 'document';
        const url = safeUrl(s.url);
        if (url) {
          const link = document.createElement('a');
          link.href = url;
          link.target = '_blank';
          link.rel = 'noopener noreferrer';
          link.textContent = label;
          src.appendChild(link);
        } else {
          const span = document.createElement('span');
          span.textContent = label;
          src.appendChild(span);
        }
      });
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
    if (needsContact()) return;
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

  // ================= CONTACT =================
  function getContact() {
    try {
      return JSON.parse(localStorage.getItem('chat_widget_contact') || 'null');
    } catch (e) {
      return null;
    }
  }

  function needsContact() {
    return config.requireContactInfo && !getContact();
  }

  function setChatInputVisible(visible) {
    const bar = shadow.getElementById('chatInput');
    if (bar) bar.style.display = visible ? 'flex' : 'none';
  }

  // Restore contact from the server (e.g. localStorage was cleared).
  // Returns true when a saved contact was found and restored.
  async function loadServerContact() {
    if (!hasWebsiteId || !config.apiUrl) return false;
    try {
      const base = config.apiUrl.replace(/\/$/, '');
      const res = await fetch(
        `${base}/api/contacts/${encodeURIComponent(sessionId)}` +
          `?website_id=${encodeURIComponent(config.website_id)}`,
      );
      if (!res.ok) return false;
      const data = await res.json();
      if (!data || !data.email) return false;
      localStorage.setItem(
        'chat_widget_contact',
        JSON.stringify({
          first_name: data.first_name,
          last_name: data.last_name,
          email: data.email,
        }),
      );
      return true;
    } catch (e) {
      return false;
    }
  }

  function showContactForm() {
    setChatInputVisible(false);
    messagesEl.innerHTML = '';
    const form = document.createElement('form');
    form.className = 'contact-form';
    form.innerHTML = `
      <p><b>${escapeHtml(config.botName)}</b> — please introduce yourself to start chatting.</p>
      <label>First name<input name="first_name" autocomplete="given-name" /></label>
      <label>Last name<input name="last_name" autocomplete="family-name" /></label>
      <label>Email<input name="email" type="email" autocomplete="email" /></label>
      <div class="error"></div>
      <button class="submit" type="submit">Start chat</button>
    `;
    const errEl = form.querySelector('.error');
    form.onsubmit = async (e) => {
      e.preventDefault();
      const first_name = form.first_name.value.trim();
      const last_name = form.last_name.value.trim();
      const email = form.email.value.trim();
      if (!first_name || !last_name || email.indexOf('@') < 0) {
        errEl.textContent =
          'Please fill first name, last name and a valid email.';
        return;
      }
      const btn = form.querySelector('.submit');
      btn.disabled = true;
      try {
        const base = (config.apiUrl || '').replace(/\/$/, '');
        const res = await fetch(`${base}/api/contacts`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            website_id: config.website_id,
            session_id: sessionId,
            first_name,
            last_name,
            email,
          }),
        });
        if (!res.ok) throw new Error('save failed');
        localStorage.setItem(
          'chat_widget_contact',
          JSON.stringify({ first_name, last_name, email }),
        );
        messagesEl.innerHTML = '';
        setChatInputVisible(true);
        addMessage(config.welcomeMessage, 'bot');
        renderSuggestions();
      } catch (err) {
        errEl.textContent = 'Could not save. Please try again.';
        btn.disabled = false;
      }
    };
    messagesEl.appendChild(form);
  }

  // ================= SEND =================
  async function sendMessage(prefillText) {
    if (needsContact()) {
      showContactForm();
      return;
    }
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
    if (needsContact()) {
      showContactForm();
      return;
    }
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
      // Server values are sanitised with the same rules as ChatWidgetConfig.
      if (cfg.assistant_name)
        config.botName = safeText(cfg.assistant_name, config.botName);
      if (cfg.widget_header_color)
        config.theme.primaryColor = safeColor(
          cfg.widget_header_color,
          config.theme.primaryColor,
        );
      if (cfg.widget_footer_color)
        config.footerColor = safeColor(cfg.widget_footer_color, config.footerColor);
      if (cfg.widget_position)
        config.position =
          cfg.widget_position === 'bottom-left' ? 'bottom-left' : 'bottom-right';
      if (cfg.greeting_message)
        config.welcomeMessage = safeText(
          cfg.greeting_message,
          config.welcomeMessage,
          500,
        );
      if (cfg.placeholder_text)
        config.placeholder = safeText(
          cfg.placeholder_text,
          config.placeholder,
          200,
        );
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

    if (needsContact()) {
      const restored = await loadServerContact();
      if (!restored) {
        showContactForm();
        return;
      }
    }
    setChatInputVisible(true);

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
