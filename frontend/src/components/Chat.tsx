import { useChat } from '@/context/ChatContext';
import type { ChatSource, Website } from '@/types/api';
import api from '@/utils/api';
import { DislikeOutlined, LikeOutlined, SendOutlined } from '@ant-design/icons';
import {
  Button,
  Empty,
  Input,
  List,
  Select,
  Space,
  Spin,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { useEffect, useRef, useState } from 'react';

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
  const [sessionId, setSessionId] = useState('');
  const [inputValue, setInputValue] = useState('');
  const [websites, setWebsites] = useState<Website[]>([]);
  const [loadingWebsites, setLoadingWebsites] = useState(false);
  const [ratings, setRatings] = useState<Record<number, 'up' | 'down'>>({});
  const chatListRef = useRef<HTMLDivElement>(null);

  const handleFeedback = async (
    index: number,
    rating: 'up' | 'down',
    websiteId: string,
    sid: string,
  ) => {
    if (ratings[index]) return;
    setRatings((prev) => ({ ...prev, [index]: rating }));
    try {
      await api.post('/chat/feedback', {
        website_id: websiteId,
        session_id: sid,
        rating,
      });
    } catch {
      // keep optimistic state even if the server call fails
    }
  };

  useEffect(() => {
    let sessionStr = localStorage.getItem('sessionId');
    if (sessionStr) {
      setSessionId(sessionStr);
    } else {
      sessionStr = crypto.randomUUID();
      localStorage.setItem('sessionId', sessionStr);
      setSessionId(sessionStr);
    }
    fetchWebsites();
  }, []);

  useEffect(() => {
    chatListRef.current?.scrollTo({
      top: chatListRef.current.scrollHeight,
      behavior: 'smooth',
    });
  }, [messages, loading]);

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
    sendMessage(inputValue, selectedWebsiteId, sessionId);
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
      <div
        ref={chatListRef}
        style={{
          flex: 1,
          overflow: 'auto',
          padding: '24px 16px',
          background: '#fafafa',
        }}
      >
        <List
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
          renderItem={(
            item: { role: 'user' | 'assistant'; content: string; sources?: ChatSource[] },
            index: number,
          ) => (
            <List.Item
              style={{
                justifyContent: item.role === 'user' ? 'flex-end' : 'flex-start',
                border: 'none',
                padding: '8px 0',
                marginBottom: '8px',
                display: 'block',
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
                  display: 'inline-block',
                  maxWidth: '85%',
                  whiteSpace: 'pre-wrap',
                }}
              >
                {item.content}
              </div>

              {item.role === 'assistant' && item.content && (
                <>
                  {item.sources && item.sources.length > 0 && (
                    <div
                      style={{
                        marginTop: 6,
                        maxWidth: '85%',
                        fontSize: 12,
                        color: '#6b7280',
                      }}
                    >
                      <Text type='secondary' style={{ fontSize: 12 }}>
                        Sources:
                      </Text>{' '}
                      {item.sources.map((s, i) => (
                        <span key={i}>
                          {i > 0 && ', '}
                          {s.url ? (
                            <a
                              href={s.url}
                              target='_blank'
                              rel='noopener noreferrer'
                            >
                              {s.title || s.url}
                            </a>
                          ) : (
                            <span>{s.title || 'document'}</span>
                          )}
                        </span>
                      ))}
                    </div>
                  )}

                  {selectedWebsiteId && (
                    <div style={{ marginTop: 4, maxWidth: '85%' }}>
                      <Space size={4}>
                        <Tooltip title='Helpful'>
                          <Button
                            type='text'
                            size='small'
                            icon={<LikeOutlined />}
                            aria-label='thumbs up'
                            disabled={!!ratings[index]}
                            danger={ratings[index] === 'down'}
                            onClick={() =>
                              handleFeedback(
                                index,
                                'up',
                                selectedWebsiteId,
                                sessionId,
                              )
                            }
                          />
                        </Tooltip>
                        <Tooltip title='Not helpful'>
                          <Button
                            type='text'
                            size='small'
                            icon={<DislikeOutlined />}
                            aria-label='thumbs down'
                            disabled={!!ratings[index]}
                            danger={ratings[index] === 'up'}
                            onClick={() =>
                              handleFeedback(
                                index,
                                'down',
                                selectedWebsiteId,
                                sessionId,
                              )
                            }
                          />
                        </Tooltip>
                        {ratings[index] && (
                          <Text type='secondary' style={{ fontSize: 12 }}>
                            Thanks for the feedback!
                          </Text>
                        )}
                      </Space>
                    </div>
                  )}
                </>
              )}
            </List.Item>
          )}
        />
        {loading && messages.length > 0 && messages[messages.length - 1].role === 'user' && (
          <List.Item
            style={{
              justifyContent: 'flex-start',
              border: 'none',
              padding: '8px 0',
            }}
          >
            <div
              className='chat-bubble assistant'
              style={{
                boxShadow: '0 2px 8px rgba(0, 0, 0, 0.05)',
                lineHeight: '1.6',
                display: 'flex',
                alignItems: 'center',
                gap: '8px',
              }}
            >
              <Spin size='small' />
              <Text type='secondary' style={{ fontSize: 13 }}>
                Thinking...
              </Text>
            </div>
          </List.Item>
        )}
      </div>
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
