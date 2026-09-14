import { Empty } from 'antd';
import type { CSSProperties } from 'react';

export interface WidgetPreviewProps {
  assistantName?: string;
  headerColor?: string;
  footerColor?: string;
  position?: 'bottom-left' | 'bottom-right';
  greetingMessage?: string;
  placeholderText?: string;
  suggestedQuestions?: string;
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
}: WidgetPreviewProps) {
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
            <span>{assistantName || 'Assistant'}</span>
            <button style={clearBtnStyle} type='button'>
              Clear
            </button>
          </div>
          <div style={messagesStyle}>
            <div style={{ display: 'flex', marginBottom: 8 }}>
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
              <div style={bubbleStyle}>
                {greetingMessage || 'Hi! How can I help you?'}
              </div>
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
            <input
              style={inputStyle}
              placeholder={placeholderText || 'Type a message...'}
              readOnly
            />
            <button style={sendBtnStyle} type='button'>
              Send
            </button>
          </div>
        </div>

        <div style={toggleStyle}>💬</div>
      </div>
    </div>
  );
}
