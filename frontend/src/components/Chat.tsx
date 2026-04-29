import { useChat } from '@/context/ChatContext';
import type { Website } from '@/types/api';
import api from '@/utils/api';
import { SendOutlined } from '@ant-design/icons';
import { Button, Empty, Input, List, Select, Typography, message } from 'antd';
import { useEffect, useState } from 'react';

const { TextArea } = Input;
const { Text } = Typography;

export function Chat() {
  const {
    messages,
    sendMessage,
    loading,
    selectedWebsiteId,
    setSelectedWebsiteId,
  } = useChat();
  const [inputValue, setInputValue] = useState('');
  const [websites, setWebsites] = useState<Website[]>([]);
  const [loadingWebsites, setLoadingWebsites] = useState(false);

  useEffect(() => {
    fetchWebsites();
  }, []);

  const fetchWebsites = async () => {
    setLoadingWebsites(true);
    try {
      const response = await api.get<{
        items: Website[];
        total: number;
        page: number;
        limit: number;
      }>('/websites');
      // console.log('Fetch websites response', response.data);
      setWebsites(response.data.items || []);
    } catch (error) {
      message.error('Failed to load websites');
    } finally {
      setLoadingWebsites(false);
    }
  };

  const handleSubmit = () => {
    if (!inputValue.trim()) return;
    if (!selectedWebsiteId) {
      message.warning('Please select a website first');
      return;
    }
    sendMessage(inputValue, selectedWebsiteId);
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
      <div
        style={{
          padding: '16px',
          background: '#ffffff',
          borderBottom: '1px solid #e5e7eb',
        }}
      >
        <Select
          placeholder='Select a website to chat with'
          style={{ width: '100%' }}
          value={selectedWebsiteId}
          onChange={setSelectedWebsiteId}
          loading={loadingWebsites}
          options={websites.map((site) => ({
            label: site.name,
            value: site.id,
          }))}
        />
      </div>
      <List
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '24px 16px',
          background: '#fafafa',
        }}
        locale={{
          emptyText: (
            <Empty
              description={
                selectedWebsiteId
                  ? 'No messages yet. Start chatting!'
                  : 'Please select a website to start chatting'
              }
              image={Empty.PRESENTED_IMAGE_SIMPLE}
            />
          ),
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
        <div style={{ display: 'flex', gap: '8px', alignItems: 'flex-start' }}>
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
            disabled={loading || !selectedWebsiteId}
            style={{
              flex: 1,
              borderRadius: '8px',
              padding: '12px 16px',
            }}
          />
          <Button
            type='primary'
            icon={<SendOutlined />}
            onClick={handleSubmit}
            loading={loading}
            disabled={!inputValue.trim() || loading || !selectedWebsiteId}
            style={{
              borderRadius: '8px',
              height: '46px',
              padding: '0 20px',
              flexShrink: 0,
            }}
          />
        </div>
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
