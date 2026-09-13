import { useChat } from '@/context/ChatContext';
import type {
  ChatSource,
  ConversationSummary,
  Website,
} from '@/types/api';
import api, {
  deleteConversation,
  getConversationMessages,
  getConversations,
} from '@/utils/api';
import {
  DeleteOutlined,
  DislikeOutlined,
  LikeOutlined,
  MessageOutlined,
  PlusOutlined,
  SendOutlined,
} from '@ant-design/icons';
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
    loadMessages,
    loading,
    selectedWebsiteId,
    setSelectedWebsiteId,
  } = useChat();
  const [sessionId, setSessionId] = useState('');
  const [inputValue, setInputValue] = useState('');
  const [websites, setWebsites] = useState<Website[]>([]);
  const [loadingWebsites, setLoadingWebsites] = useState(false);
  const [ratings, setRatings] = useState<Record<number, 'up' | 'down'>>({});
  const [conversations, setConversations] = useState<ConversationSummary[]>([]);
  const [loadingConversations, setLoadingConversations] = useState(false);
  const [convTotal, setConvTotal] = useState(0);
  const [selectedSessionId, setSelectedSessionId] = useState<string | null>(
    null,
  );
  const CONV_PAGE = 20;
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

  // Deep-link support: a Dashboard link can preselect a website via ?website=.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const websiteParam = params.get('website');
    if (websiteParam) setSelectedWebsiteId(websiteParam);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // When the website changes, start a fresh chat and load its history list.
  useEffect(() => {
    if (!selectedWebsiteId) {
      setConversations([]);
      setConvTotal(0);
      return;
    }
    const sid = crypto.randomUUID();
    localStorage.setItem('sessionId', sid);
    setSessionId(sid);
    setSelectedSessionId(null);
    loadMessages([]);
    (async () => {
      const items = await loadConversations(selectedWebsiteId, true);
      const params = new URLSearchParams(window.location.search);
      const focus = params.get('focus');
      if (items.length > 0) {
        if (focus === 'latest') {
          selectConversation(items[0]);
        } else if (focus) {
          const match = items.find((c) => c.session_id === focus);
          if (match) {
            selectConversation(match);
          } else {
            // Not on the first page; fetch the session directly instead.
            getConversationMessages(selectedWebsiteId, focus)
              .then((r) => {
                loadMessages(r.data.items || []);
                setSessionId(focus);
                setSelectedSessionId(focus);
              })
              .catch(() => {});
          }
        }
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWebsiteId]);

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

  const loadConversations = async (
    websiteId: string,
    reset = false,
  ): Promise<ConversationSummary[]> => {
    if (reset) {
      setConversations([]);
      setConvTotal(0);
    }
    setLoadingConversations(true);
    try {
      const offset = reset ? 0 : conversations.length;
      const res = await getConversations(websiteId, {
        limit: CONV_PAGE,
        offset,
      });
      const items = res.data.items || [];
      setConversations((prev) => (reset ? items : [...prev, ...items]));
      setConvTotal(res.data.total ?? 0);
      return items;
    } catch {
      return [];
    } finally {
      setLoadingConversations(false);
    }
  };

  const selectConversation = async (conv: ConversationSummary) => {
    if (!selectedWebsiteId) return;
    setSelectedSessionId(conv.session_id);
    setSessionId(conv.session_id);
    try {
      const res = await getConversationMessages(
        selectedWebsiteId,
        conv.session_id,
      );
      loadMessages(res.data.items || []);
    } catch {
      message.error('Failed to load conversation');
    }
  };

  const newChat = () => {
    const sid = crypto.randomUUID();
    localStorage.setItem('sessionId', sid);
    setSessionId(sid);
    setSelectedSessionId(null);
    loadMessages([]);
  };

  const removeConversation = async (conv: ConversationSummary) => {
    if (!selectedWebsiteId) return;
    try {
      await deleteConversation(selectedWebsiteId, conv.session_id);
      setConversations((prev) =>
        prev.filter((c) => c.session_id !== conv.session_id),
      );
      if (selectedSessionId === conv.session_id) newChat();
      message.success('Conversation deleted');
    } catch {
      message.error('Failed to delete conversation');
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
        flexDirection: 'row',
        background: '#fafafa',
        borderRadius: '12px',
        overflow: 'hidden',
      }}
    >
      {/* ================= CONVERSATION HISTORY SIDEBAR ================= */}
      <div
        style={{
          width: '240px',
          flexShrink: 0,
          background: '#ffffff',
          borderRight: '1px solid #e5e7eb',
          display: 'flex',
          flexDirection: 'column',
        }}
      >
        <div
          style={{
            padding: '12px',
            borderBottom: '1px solid #e5e7eb',
          }}
        >
          <Button
            type='primary'
            icon={<PlusOutlined />}
            block
            onClick={newChat}
            disabled={!selectedWebsiteId}
          >
            New chat
          </Button>
        </div>
        <div style={{ flex: 1, overflow: 'auto', padding: '8px' }}>
          {!selectedWebsiteId ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description='Select a website'
              style={{ marginTop: 40 }}
            />
          ) : loadingConversations ? (
            <div style={{ textAlign: 'center', padding: 24 }}>
              <Spin size='small' />
            </div>
          ) : conversations.length === 0 ? (
            <Empty
              image={Empty.PRESENTED_IMAGE_SIMPLE}
              description='No history yet'
              style={{ marginTop: 40 }}
            />
          ) : (
            conversations.map((conv) => (
              <div
                key={conv.session_id}
                onClick={() => selectConversation(conv)}
                style={{
                  padding: '10px 12px',
                  borderRadius: '8px',
                  cursor: 'pointer',
                  marginBottom: 4,
                  background:
                    selectedSessionId === conv.session_id
                      ? '#eef2ff'
                      : 'transparent',
                  border:
                    selectedSessionId === conv.session_id
                      ? '1px solid #c7d2fe'
                      : '1px solid transparent',
                }}
              >
                <div
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'space-between',
                    gap: 4,
                  }}
                >
                  <Text
                    strong
                    ellipsis
                    style={{ fontSize: 13, maxWidth: '170px' }}
                  >
                    <MessageOutlined style={{ marginRight: 6 }} />
                    {conv.title || 'Chat'}
                  </Text>
                  <DeleteOutlined
                    onClick={(e) => {
                      e.stopPropagation();
                      removeConversation(conv);
                    }}
                    style={{ color: '#9ca3af', fontSize: 12 }}
                  />
                </div>
                <div
                  style={{
                    fontSize: 11,
                    color: '#9ca3af',
                    marginTop: 2,
                  }}
                >
                  {conv.message_count} msgs ·{' '}
                  {new Date(conv.last_message_at).toLocaleDateString()}
                </div>
              </div>
            ))
          )}
          {selectedWebsiteId &&
            !loadingConversations &&
            conversations.length < convTotal && (
              <div style={{ textAlign: 'center', padding: '6px 0 12px' }}>
                <Button
                  type='link'
                  size='small'
                  onClick={() => loadConversations(selectedWebsiteId)}
                >
                  Load more ({conversations.length}/{convTotal})
                </Button>
              </div>
            )}
        </div>
      </div>

      {/* ================= CHAT PANE ================= */}
      <div
        style={{
          flex: 1,
          display: 'flex',
          flexDirection: 'column',
          minWidth: 0,
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
    </div>
  );
}
