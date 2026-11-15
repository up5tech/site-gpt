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
    logoUrl: '',
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

  // CSS named colours (CSS Color 4), plus the two colour keywords. Matched as
  // whole words, so a name can never carry a `;`, a `}` or a `url()`.
  const NAMED_COLORS = new Set(
    (
      'aliceblue,antiquewhite,aqua,aquamarine,azure,beige,bisque,black,' +
      'blanchedalmond,blue,blueviolet,brown,burlywood,cadetblue,chartreuse,' +
      'chocolate,coral,cornflowerblue,cornsilk,crimson,cyan,darkblue,darkcyan,' +
      'darkgoldenrod,darkgray,darkgreen,darkgrey,darkkhaki,darkmagenta,' +
      'darkolivegreen,darkorange,darkorchid,darkred,darksalmon,darkseagreen,' +
      'darkslateblue,darkslategray,darkslategrey,darkturquoise,darkviolet,' +
      'deeppink,deepskyblue,dimgray,dimgrey,dodgerblue,firebrick,floralwhite,' +
      'forestgreen,fuchsia,gainsboro,ghostwhite,gold,goldenrod,gray,green,' +
      'greenyellow,grey,honeydew,hotpink,indianred,indigo,ivory,khaki,lavender,' +
      'lavenderblush,lawngreen,lemonchiffon,lightblue,lightcoral,lightcyan,' +
      'lightgoldenrodyellow,lightgray,lightgreen,lightgrey,lightpink,' +
      'lightsalmon,lightseagreen,lightskyblue,lightslategray,lightslategrey,' +
      'lightsteelblue,lightyellow,lime,limegreen,linen,magenta,maroon,' +
      'mediumaquamarine,mediumblue,mediumorchid,mediumpurple,mediumseagreen,' +
      'mediumslateblue,mediumspringgreen,mediumturquoise,mediumvioletred,' +
      'midnightblue,mintcream,mistyrose,moccasin,navajowhite,navy,oldlace,' +
      'olive,olivedrab,orange,orangered,orchid,palegoldenrod,palegreen,' +
      'paleturquoise,palevioletred,papayawhip,peachpuff,peru,pink,plum,' +
      'powderblue,purple,rebeccapurple,red,rosybrown,royalblue,saddlebrown,' +
      'salmon,sandybrown,seagreen,seashell,sienna,silver,skyblue,slateblue,' +
      'slategray,slategrey,snow,springgreen,steelblue,tan,teal,thistle,tomato,' +
      'turquoise,violet,wheat,white,whitesmoke,yellow,yellowgreen,' +
      'transparent,currentcolor'
    ).split(','),
  );

  function safeColor(value, fallback) {
    const candidate = String(value === null || value === undefined ? '' : value).trim();
    const allowed =
      HEX_COLOR.test(candidate) ||
      FUNC_COLOR.test(candidate) ||
      NAMED_COLORS.has(candidate.toLowerCase());
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

  // `widget_logo_url` becomes an <img src>, so only absolute https URLs and
  // raster data URIs are accepted. Anything else (javascript:, data:text/html,
  // inline SVG, a bare word) is dropped and the avatar falls back to the emoji.
  const LOGO_HTTPS = /^https:\/\/[^\s"'<>]+$/i;
  const LOGO_DATA = /^data:image\/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$/i;

  function safeLogoUrl(value) {
    const candidate = String(value === null || value === undefined ? '' : value).trim();
    return LOGO_HTTPS.test(candidate) || LOGO_DATA.test(candidate) ? candidate : '';
  }

  function sanitizeConfig(cfg) {
    const theme = cfg.theme || {};
    return Object.assign({}, cfg, {
      botName: safeText(cfg.botName, DEFAULT_CONFIG.botName),
      placeholder: safeText(cfg.placeholder, DEFAULT_CONFIG.placeholder, 200),
      logoUrl: safeLogoUrl(cfg.logoUrl),
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

  // ================= UI STRINGS =================
  // Every visible label has its English text at the call site, so this table
  // only holds the languages the widget ships. Resolution order in `t()`:
  // the owner's `widget_ui_strings` overrides, then this table for the resolved
  // language, then the English fallback. Anything unknown stays English.
  const TRANSLATIONS = {
    vi: {
      clear: 'Xoá',
      send: 'Gửi',
      thinking: 'Đang trả lời...',
      sources: 'Nguồn:',
      helpful: 'Hữu ích',
      notHelpful: 'Không hữu ích',
      thanksFeedback: 'Cảm ơn phản hồi của bạn!',
      contactIntro: ' — vui lòng giới thiệu bản thân để bắt đầu trò chuyện.',
      firstName: 'Tên',
      lastName: 'Họ',
      email: 'Email',
      contactInvalid: 'Vui lòng nhập tên, họ và email hợp lệ.',
      startChat: 'Bắt đầu trò chuyện',
      contactSaveFailed: 'Không lưu được. Vui lòng thử lại.',
      noResponse: 'Không có phản hồi',
      missingWebsiteId: 'Thiếu Website ID',
      error: 'Lỗi!',
    },
  };

  // Resolved from the `widget_language` setting. Starts as English so an embed
  // that has no such setting keeps exactly the V1 strings.
  let uiLanguage = 'en';
  let uiStrings = {};

  // `auto` follows the host page's browser language; an explicit code forces a
  // locale. Region suffixes are dropped (`vi-VN` -> `vi`).
  function normalizeLanguage(raw) {
    const value = String(raw === null || raw === undefined ? '' : raw)
      .trim()
      .toLowerCase();
    if (!value || value === 'auto') {
      const nav =
        typeof navigator !== 'undefined' && navigator.language
          ? String(navigator.language).toLowerCase()
          : '';
      return nav.split('-')[0] || 'en';
    }
    return value.split('-')[0];
  }

  // `widget_ui_strings` is owner-supplied JSON. Malformed input or a non-object
  // falls back silently to the catalogue / English, never to an error.
  function parseUiStrings(raw) {
    if (typeof raw !== 'string' || !raw.trim()) return {};
    try {
      const parsed = JSON.parse(raw);
      if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
        return {};
      }
      const out = {};
      Object.keys(parsed).forEach((key) => {
        if (typeof parsed[key] === 'string' && parsed[key].trim()) {
          out[key] = parsed[key];
        }
      });
      return out;
    } catch (e) {
      return {};
    }
  }

  function t(key, fallback) {
    const override = uiStrings[key];
    if (typeof override === 'string' && override) return override;
    const table = TRANSLATIONS[uiLanguage];
    const translated = table && table[key];
    return translated || fallback;
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

      .chat-header .title {
        display: flex;
        align-items: center;
        gap: 8px;
        min-width: 0;
      }

      .header-logo {
        width: 22px;
        height: 22px;
        object-fit: contain;
        border-radius: 4px;
        flex: 0 0 auto;
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
        <span class="title">
          <img class="header-logo" id="headerLogo" alt="" referrerpolicy="no-referrer" hidden />
          <span id="chatHeaderName">${escapeHtml(config.botName)}</span>
        </span>
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

  // ================= LOGO =================
  // The header badge and every bot avatar share the owner's logo. Both fall
  // back to the emoji when the image cannot load, so a dead URL can never leave
  // a broken image icon in the chat.
  function applyLogo() {
    const logo = shadow.getElementById('headerLogo');
    if (!logo) return;
    if (!config.logoUrl) {
      logo.hidden = true;
      logo.removeAttribute('src');
      return;
    }
    logo.onerror = () => {
      logo.hidden = true;
    };
    logo.src = config.logoUrl;
    logo.hidden = false;
  }

  function createBotAvatar() {
    if (!config.logoUrl) {
      const emoji = document.createElement('div');
      emoji.className = 'avatar';
      emoji.textContent = '🤖';
      return emoji;
    }
    const img = document.createElement('img');
    img.className = 'avatar';
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    img.onerror = () => {
      const fallback = document.createElement('div');
      fallback.className = 'avatar';
      fallback.textContent = '🤖';
      if (img.parentNode) img.parentNode.replaceChild(fallback, img);
    };
    img.src = config.logoUrl;
    return img;
  }

  // ================= MESSAGE =================
  function addMessage(text, role, isThinking = false, skipScroll = false) {
    const row = document.createElement('div');
    row.className = `row ${role}`;

    let avatar;
    if (role === 'user') {
      avatar = document.createElement('div');
      avatar.className = 'avatar';
      avatar.textContent = '👤';
    } else {
      avatar = createBotAvatar();
    }

    const bubble = document.createElement('div');
    bubble.className = 'bubble';

    if (isThinking) {
      bubble.textContent = t('thinking', 'Thinking...');
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
      heading.textContent = t('sources', 'Sources:');
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
    up.title = t('helpful', 'Helpful');
    const down = document.createElement('button');
    down.textContent = '👎';
    down.title = t('notHelpful', 'Not helpful');
    const thanks = document.createElement('span');
    thanks.className = 'thanks';
    thanks.style.display = 'none';
    thanks.textContent = t('thanksFeedback', 'Thanks for the feedback!');

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
    // The English copy at each call site is the fallback: `t()` swaps in the
    // language catalogue or the owner's `widget_ui_strings` when present.
    form.innerHTML = `
      <p><b>${escapeHtml(config.botName)}</b>${escapeHtml(t('contactIntro', ' — please introduce yourself to start chatting.'))}</p>
      <label>${escapeHtml(t('firstName', 'First name'))}<input name="first_name" autocomplete="given-name" /></label>
      <label>${escapeHtml(t('lastName', 'Last name'))}<input name="last_name" autocomplete="family-name" /></label>
      <label>${escapeHtml(t('email', 'Email'))}<input name="email" type="email" autocomplete="email" /></label>
      <div class="error"></div>
      <button class="submit" type="submit">${escapeHtml(t('startChat', 'Start chat'))}</button>
    `;
    const errEl = form.querySelector('.error');
    form.onsubmit = async (e) => {
      e.preventDefault();
      const first_name = form.first_name.value.trim();
      const last_name = form.last_name.value.trim();
      const email = form.email.value.trim();
      if (!first_name || !last_name || email.indexOf('@') < 0) {
        errEl.textContent = t(
          'contactInvalid',
          'Please fill first name, last name and a valid email.',
        );
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
        if (res.status === 403) {
          markUnavailable(null);
          return;
        }
        if (!res.ok) throw new Error('save failed');
        localStorage.setItem(
          'chat_widget_contact',
          JSON.stringify({ first_name, last_name, email }),
        );
        messagesEl.innerHTML = '';
        setChatInputVisible(true);
        addMessage(t('greeting', config.welcomeMessage), 'bot');
        renderSuggestions();
      } catch (err) {
        errEl.textContent = t(
          'contactSaveFailed',
          'Could not save. Please try again.',
        );
        btn.disabled = false;
      }
    };
    messagesEl.appendChild(form);
  }

  // ================= DISABLED WEBSITE =================
  // A website whose owner disabled it answers every public endpoint with 403.
  // That is a normal, expected state, not a broken widget: tell the visitor so
  // instead of the generic 'Error!' bubble, and never ask for contact details
  // on a site that cannot accept them.
  const UNAVAILABLE_MESSAGE =
    'This assistant is temporarily unavailable. Please try again later.';

  let siteDisabled = false;

  // `row` is the in-flight bot bubble to reuse; without one the message is
  // added as a new bubble (and any half-rendered content is dropped).
  function markUnavailable(row) {
    siteDisabled = true;
    setChatInputVisible(false);
    const bubble = row ? row.querySelector('.bubble') : null;
    if (bubble) {
      bubble.classList.remove('thinking');
      bubble.textContent = UNAVAILABLE_MESSAGE;
      return;
    }
    messagesEl.innerHTML = '';
    addMessage(UNAVAILABLE_MESSAGE, 'bot');
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

      if (res.status === 403) {
        // Disabled website: a clear message, not 'Error!'.
        markUnavailable(thinkingRow);
        inputEl.disabled = false;
        sendBtn.disabled = false;
        return;
      }

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

      thinkingMsg.innerHTML = renderMarkdown(
        reply || t('noResponse', 'No response'),
      );
      thinkingMsg.classList.remove('thinking');
      attachExtras(thinkingRow, pendingSources);

      scrollToBottom();
      saveHistory('bot', reply);
    } catch (err) {
      thinkingMsg.textContent = t('error', 'Error!');
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
      if (res.status === 403) {
        siteDisabled = true;
        return;
      }
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

      // Language before any label, because everything below goes through `t()`.
      // No key at all (a pre-V2 company) keeps the English V1 strings.
      if (cfg.widget_logo_url !== undefined) {
        config.logoUrl = safeLogoUrl(cfg.widget_logo_url);
      }
      if (cfg.widget_language) uiLanguage = normalizeLanguage(cfg.widget_language);
      uiStrings = parseUiStrings(cfg.widget_ui_strings);

      // Apply dynamic styles / labels now that config is loaded.
      headerNameEl.textContent = config.botName;
      clearBtn.textContent = t('clear', 'Clear');
      sendBtn.textContent = t('send', 'Send');
      toggleBtn.style.background = config.theme.primaryColor;
      shadow.querySelector('.chat-header').style.background =
        config.theme.primaryColor;
      shadow.querySelector('.chat-input button').style.background =
        config.theme.primaryColor;
      shadow.querySelector('.chat-input').style.background = config.footerColor;
      inputEl.placeholder = t('placeholder', config.placeholder);
      applyLogo();
      container.style[config.position === 'bottom-left' ? 'left' : 'right'] =
        '20px';
    } catch (e) {
      // fall back to ChatWidgetConfig / defaults
    }
  }

  // ================= INIT =================
  // Restore a returning visitor's history from the server (source of truth).
  // Falls back to the local copy if the server has nothing / is unreachable.
  // Fetch only, no DOM writes: the caller paints once it knows the contact
  // gate is satisfied, so this request can run in parallel with the others.
  async function fetchServerHistory() {
    if (!config.enableHistory || !hasWebsiteId || !config.apiUrl) return null;
    try {
      const base = config.apiUrl.replace(/\/$/, '');
      const res = await fetch(
        `${base}/api/conversations/${encodeURIComponent(sessionId)}` +
          `?website_id=${encodeURIComponent(config.website_id)}`,
      );
      if (!res.ok) return null;
      const data = await res.json();
      const items = data.items || [];
      return items.length ? items : null;
    } catch (e) {
      return null;
    }
  }

  function renderServerHistory(items) {
    if (!Array.isArray(items) || !items.length) return false;
    items.forEach((m) => addMessage(m.message, m.role, false, true));
    return true;
  }

  async function init() {
    if (!hasWebsiteId) {
      addMessage(t('missingWebsiteId', 'Missing Website ID'), 'bot');
      return;
    }

    // Config, contact and history do not depend on each other. They used to be
    // awaited one after another, so the first paint waited for three round
    // trips; issue them together and decide once they all settle.
    const contactRequired = needsContact();
    const [, restoredContact, historyItems] = await Promise.all([
      loadServerConfig(),
      contactRequired ? loadServerContact() : Promise.resolve(false),
      fetchServerHistory(),
    ]);

    // Disabled website: no contact form, no history, just the notice.
    if (siteDisabled) {
      markUnavailable(null);
      return;
    }

    if (contactRequired && !restoredContact) {
      showContactForm();
      return;
    }
    setChatInputVisible(true);

    // Painted only now: the contact form above clears the message list.
    const loadedFromServer = renderServerHistory(historyItems);
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
