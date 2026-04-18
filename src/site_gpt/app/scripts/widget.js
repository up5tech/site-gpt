(function () {
  // ================= CONFIG =================
  const DEFAULT_CONFIG = {
    apiUrl: '',
    token: '',
    botName: 'Assistant',
    position: 'bottom-right',
    width: '360px',
    height: '480px',
    theme: {
      primaryColor: '#4CAF50',
      backgroundColor: '#ffffff',
    },
    placeholder: 'Type a message...',
    welcomeMessage: 'Hi 👋 How can I help you?',
    enableHistory: true,
  };

  const config = Object.assign(
    {},
    DEFAULT_CONFIG,
    window.ChatWidgetConfig || {},
  );
  const hasToken = !!config.token;

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
      }

      .chat-input input {
        flex: 1;
        border: none;
        padding: 10px;
        outline: none;
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
        <span>${config.botName}</span>
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

    return bubble;
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

  // ================= SEND =================
  async function sendMessage() {
    const text = inputEl.value.trim();
    if (!text) return;

    addMessage(text, 'user');
    saveHistory('user', text);
    inputEl.value = '';

    inputEl.disabled = true;
    sendBtn.disabled = true;

    const thinkingMsg = addMessage('', 'bot', true);

    try {
      const res = await fetch(config.apiUrl, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${config.token}`,
        },
        body: JSON.stringify({
          message: text,
          session_id: sessionId,
        }),
      });

      const data = await res.json();
      const reply = data.answer || 'No response';

      thinkingMsg.innerHTML = renderMarkdown(reply);
      thinkingMsg.classList.remove('thinking');

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
    addMessage('I am here to help you.', 'bot');
  };

  // ================= EVENTS =================
  sendBtn.onclick = sendMessage;
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

  // ================= INIT =================
  function init() {
    if (!hasToken) {
      addMessage('Missing API token', 'bot');
      return;
    }

    loadHistory();

    if (!localStorage.getItem('chat_widget_initialized')) {
      addMessage(config.welcomeMessage, 'bot');
      localStorage.setItem('chat_widget_initialized', 'true');
    }

    scrollToBottomForce();
  }

  init();
})();
