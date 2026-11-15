import { Empty } from 'antd';
import { useEffect, useState } from 'react';
import type { CSSProperties } from 'react';

export interface WidgetPreviewProps {
  assistantName?: string;
  headerColor?: string;
  footerColor?: string;
  position?: 'bottom-left' | 'bottom-right';
  greetingMessage?: string;
  placeholderText?: string;
  suggestedQuestions?: string;
  language?: string;
  uiStrings?: string;
  logoUrl?: string;
  handoffEnabled?: boolean;
  handoffLabel?: string;
}

// Same rule as widget.js: only absolute https URLs and raster data URIs can
// become an <img src>, so no javascript:/inline-SVG source reaches the preview.
const LOGO_HTTPS = /^https:\/\/[^\s"'<>]+$/i;
const LOGO_DATA = /^data:image\/(?:png|jpe?g|gif|webp);base64,[a-z0-9+/=\s]+$/i;

function safeLogoUrl(value: string | undefined): string {
  const candidate = (value || '').trim();
  return LOGO_HTTPS.test(candidate) || LOGO_DATA.test(candidate)
    ? candidate
    : '';
}

// The shipped label catalogue mirrors widget.js, which owns the full table; the
// preview only renders these two labels, so only those are duplicated here.
const PREVIEW_STRINGS: Record<
  string,
  { clear: string; send: string; talkToHuman: string }
> = {
  vi: { clear: 'Xoá', send: 'Gửi', talkToHuman: 'Nói chuyện với người thật' },
};

// Same resolution order as the widget: overrides, then the language catalogue,
// then the English fallback. Malformed JSON is ignored, never thrown.
function parseUiStrings(raw: string | undefined): Record<string, string> {
  if (!raw || !raw.trim()) return {};
  try {
    const parsed: unknown = JSON.parse(raw);
    if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return {};
    }
    const out: Record<string, string> = {};
    Object.entries(parsed as Record<string, unknown>).forEach(([key, value]) => {
      if (typeof value === 'string' && value.trim()) out[key] = value;
    });
    return out;
  } catch {
    return {};
  }
}

// `auto` cannot know the visitor's browser, so the preview uses this admin's.
function resolveLocale(language: string | undefined): string {
  const value = (language || '').trim().toLowerCase();
  const resolved =
    !value || value === 'auto'
      ? (navigator.language || 'en').toLowerCase()
      : value;
  return resolved.split('-')[0] || 'en';
}

const DEVICE_WIDTH = 320;
const DEVICE_HEIGHT = 460;

// Pick a readable text color (black/white) for a given background hex.
function readableOn(hex: string): string {
  const c = hex.replace('#', '');
  if (c.length < 6) return '#ffffff';
  const r = parseInt(c.slice(0, 2), 16);
  const g = parseInt(c.slice(2, 4), 16);
  const b = parseInt(c.slice(4, 6), 16);
  // Perceived luminance
  const lum = (0.299 * r + 0.587 * g + 0.114 * b) / 255;
  return lum > 0.6 ? '#1f1f1f' : '#ffffff';
}

export function WidgetPreview({
  assistantName = 'Site GPT',
  headerColor = '#4c74af',
  footerColor = '#4c74af',
  position = 'bottom-right',
  greetingMessage = 'Hi 👋 How can I help you?',
  placeholderText = 'Type a message...',
  suggestedQuestions = '',
  language,
  uiStrings,
  logoUrl,
  handoffEnabled = false,
  handoffLabel = 'Talk to a human',
}: WidgetPreviewProps) {
  // A logo that fails to load must fall back to the emoji, and a new URL gets a
  // fresh chance instead of staying on the previous failure.
  const [logoFailed, setLogoFailed] = useState(false);
  useEffect(() => setLogoFailed(false), [logoUrl]);
  const logo = logoFailed ? '' : safeLogoUrl(logoUrl);

  const overrides = parseUiStrings(uiStrings);
  const catalogue = PREVIEW_STRINGS[resolveLocale(language)] || {};
  const label = (key: 'clear' | 'send' | 'talkToHuman', fallback: string) =>
    overrides[key] || catalogue[key] || fallback;
  const greeting =
    overrides.greeting || greetingMessage || 'Hi! How can I help you?';
  const placeholder =
    overrides.placeholder || placeholderText || 'Type a message...';
  const side: 'left' | 'right' = position === 'bottom-left' ? 'left' : 'right';
  const headerText = readableOn(headerColor);
  const footerText = readableOn(footerColor);
  const suggestions = suggestedQuestions
    .split('\n')
    .map((s) => s.trim())
    .filter(Boolean);

  const deviceStyle: CSSProperties = {
    position: 'relative',
    width: DEVICE_WIDTH,
    height: DEVICE_HEIGHT,
    margin: '0 auto',
    background: '#f0f2f5',
    borderRadius: 16,
    border: '1px solid #e5e7eb',
    overflow: 'hidden',
    boxShadow: '0 8px 24px rgba(0,0,0,0.08)',
  };

  const chatBoxStyle: CSSProperties = {
    position: 'absolute',
    [side]: 10,
    bottom: 64,
    width: DEVICE_WIDTH - 36,
    height: DEVICE_HEIGHT - 120,
    background: '#ffffff',
    borderRadius: 12,
    boxShadow: '0 6px 18px rgba(0,0,0,0.2)',
    display: 'flex',
    flexDirection: 'column',
    overflow: 'hidden',
    fontFamily: 'Arial, sans-serif',
  };

  const headerStyle: CSSProperties = {
    background: headerColor,
    color: headerText,
    padding: '10px 12px',
    display: 'flex',
    justifyContent: 'space-between',
    alignItems: 'center',
    fontSize: 14,
    fontWeight: 600,
  };

  const clearBtnStyle: CSSProperties = {
    background: headerText,
    color: headerColor,
    border: 'none',
    padding: '3px 8px',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 11,
  };

  // Mirrors widget.js: an outlined button on the header colour.
  const handoffBtnStyle = (textColor: string): CSSProperties => ({
    background: 'transparent',
    color: textColor,
    border: `1px solid ${textColor}`,
    padding: '3px 8px',
    borderRadius: 6,
    cursor: 'pointer',
    fontSize: 11,
  });

  const messagesStyle: CSSProperties = {
    flex: 1,
    overflowY: 'auto',
    padding: 10,
  };

  const bubbleStyle: CSSProperties = {
    display: 'inline-block',
    padding: '8px 10px',
    borderRadius: 10,
    maxWidth: '80%',
    fontSize: 13,
    lineHeight: 1.4,
    wordBreak: 'break-word',
    background: '#f1f1f1',
    color: '#1f1f1f',
  };

  const suggestionsWrapStyle: CSSProperties = {
    display: 'flex',
    flexWrap: 'wrap',
    gap: 6,
    marginTop: 8,
    marginLeft: 34,
  };

  const chipStyle: CSSProperties = {
    border: `1px solid ${headerColor}`,
    color: headerColor,
    background: '#fff',
    borderRadius: 14,
    padding: '3px 10px',
    fontSize: 11,
    cursor: 'pointer',
  };

  const inputBarStyle: CSSProperties = {
    display: 'flex',
    borderTop: '1px solid #ddd',
    background: footerColor,
  };

  const inputStyle: CSSProperties = {
    flex: 1,
    border: 'none',
    padding: 10,
    outline: 'none',
    background: 'transparent',
    color: footerText,
    fontSize: 13,
  };

  const sendBtnStyle: CSSProperties = {
    background: headerColor,
    color: headerText,
    border: 'none',
    padding: '0 14px',
    cursor: 'pointer',
    fontSize: 13,
  };

  const toggleStyle: CSSProperties = {
    position: 'absolute',
    [side]: 14,
    bottom: 12,
    width: 44,
    height: 44,
    borderRadius: '50%',
    background: headerColor,
    color: headerText,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    fontSize: 20,
    boxShadow: '0 4px 10px rgba(0,0,0,0.25)',
  };

  return (
    <div style={{ padding: 8 }}>
      <div style={deviceStyle}>
        <div style={chatBoxStyle}>
          <div style={headerStyle}>
            <span
              style={{
                display: 'flex',
                alignItems: 'center',
                gap: 8,
                minWidth: 0,
              }}
            >
              {logo && (
                <img
                  key={logo}
                  src={logo}
                  alt=''
                  referrerPolicy='no-referrer'
                  style={{
                    width: 22,
                    height: 22,
                    objectFit: 'contain',
                    borderRadius: 4,
                    flex: '0 0 auto',
                  }}
                  onError={() => setLogoFailed(true)}
                />
              )}
              <span>{assistantName || 'Assistant'}</span>
            </span>
            <span style={{ display: 'flex', gap: 6, flex: '0 0 auto' }}>
              {handoffEnabled && (
                <button style={handoffBtnStyle(headerText)} type='button'>
                  {label('talkToHuman', handoffLabel || 'Talk to a human')}
                </button>
              )}
              <button style={clearBtnStyle} type='button'>
                {label('clear', 'Clear')}
              </button>
            </span>
          </div>
          <div style={messagesStyle}>
            <div style={{ display: 'flex', marginBottom: 8 }}>
              {logo ? (
                <img
                  key={logo}
                  src={logo}
                  alt=''
                  referrerPolicy='no-referrer'
                  style={{
                    width: 26,
                    height: 26,
                    marginRight: 6,
                    objectFit: 'contain',
                    borderRadius: 4,
                  }}
                  onError={() => setLogoFailed(true)}
                />
              ) : (
                <div
                  style={{
                    width: 26,
                    height: 26,
                    marginRight: 6,
                    textAlign: 'center',
                    lineHeight: '26px',
                  }}
                >
                  🤖
                </div>
              )}
              <div style={bubbleStyle}>{greeting}</div>
            </div>

            {suggestions.length > 0 ? (
              <div style={suggestionsWrapStyle}>
                {suggestions.map((q, i) => (
                  <button key={i} style={chipStyle} type='button'>
                    {q}
                  </button>
                ))}
              </div>
            ) : (
              <div style={{ ...suggestionsWrapStyle, marginLeft: 0 }}>
                <Empty
                  image={Empty.PRESENTED_IMAGE_SIMPLE}
                  description='No suggested questions'
                  style={{ margin: 0, opacity: 0.5 }}
                />
              </div>
            )}
          </div>
          <div style={inputBarStyle}>
            <input style={inputStyle} placeholder={placeholder} readOnly />
            <button style={sendBtnStyle} type='button'>
              {label('send', 'Send')}
            </button>
          </div>
        </div>

        <div style={toggleStyle}>💬</div>
      </div>
    </div>
  );
}
