import { useChat } from '@/context/ChatContext';
import { SendOutlined } from '@ant-design/icons';
import { Button, Form, Input, List, Space, Typography } from 'antd';
import { useState } from 'react';

const { TextArea } = Input;
const { useForm } = Form;
const { Text } = Typography;

interface Props {
  style?: React.CSSProperties;
}

export function Chat() {
  const { messages, sendMessage, loading } = useChat();
  const [inputValue, setInputValue] = useState('');
  const [form] = useForm();

  const handleSubmit = () => {
    if (!inputValue.trim()) return;
    sendMessage(inputValue);
    setInputValue('');
  };

  return (
    <div
      style={{
        height: '500px',
        display: 'flex',
        flexDirection: 'column',
        background: '#fafafa',
        borderRadius: '12px',
        overflow: 'hidden',
      }}
    >
      <List
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '24px 16px',
          background: '#fafafa',
        }}
        dataSource={messages}
        renderItem={(item: { role: 'user' | 'assistant'; content: string }) => (
          <List.Item
            style={{
              justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
              border: 'none',
              padding: '8px 0',
              marginBottom: '8px',
            }}
          >
            <div
              className={`chat-bubble ${item.role}`}
              style={{
                boxShadow:
                  item.role === 'user'
                    ? '0 2px 8px rgba(0, 0, 0, 0.15)'
                    : '0 2px 8px rgba(0, 0, 0, 0.05)',
                lineHeight: '1.6',
              }}
            >
              {item.content}
            </div>
          </List.Item>
        )}
      />
      <div
        style={{
          padding: '16px',
          background: '#ffffff',
          borderTop: '1px solid #e5e7eb',
          boxShadow: '0 -2px 8px rgba(0, 0, 0, 0.03)',
        }}
      >
        <Space.Compact style={{ width: '100%' }}>
          <TextArea
            value={inputValue}
            onChange={(e) => setInputValue(e.target.value)}
            onPressEnter={(e) => {
              if (e.shiftKey) return;
              e.preventDefault();
              handleSubmit();
            }}
            placeholder='Ask about your site...'
            autoSize={{ minRows: 1, maxRows: 4 }}
            disabled={loading}
            style={{
              borderRadius: '8px 0 0 8px',
              padding: '12px 16px',
            }}
          />
          <Button
            type='primary'
            icon={<SendOutlined />}
            onClick={handleSubmit}
            loading={loading}
            disabled={!inputValue.trim() || loading}
            style={{
              borderRadius: '0 8px 8px 0',
              padding: '0 20px',
            }}
          />
        </Space.Compact>
        <div
          style={{
            marginTop: '8px',
            textAlign: 'center',
          }}
        >
          <Text type='secondary' style={{ fontSize: '12px' }}>
            Press Enter to send, Shift + Enter for new line
          </Text>
        </div>
      </div>
    </div>
  );
}
