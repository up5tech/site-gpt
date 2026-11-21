import { SendOutlined } from '@ant-design/icons';
import {
  Alert,
  Avatar,
  Badge,
  Button,
  Card,
  Col,
  Empty,
  Input,
  List,
  Popconfirm,
  Row,
  Segmented,
  Space,
  Tag,
  Tooltip,
  Typography,
  message,
} from 'antd';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import type {
  InboxConversation,
  InboxConversationDetail,
  InboxMessage,
  InboxPresence,
  InboxState,
} from '../types/api';
import {
  claimInboxConversation,
  closeInboxConversation,
  getApiErrorMessage,
  getApiErrorStatus,
  getInboxConversation,
  getInboxConversations,
  getInboxPresence,
  getInboxStatus,
  openInboxEvents,
  releaseInboxConversation,
  sendInboxReply,
} from '../utils/api';

const { Title, Text, Paragraph } = Typography;
const { TextArea } = Input;

const PAGE_SIZE = 20;

const STATE_COLORS: Record<InboxState, string> = {
  bot: 'default',
  waiting: 'gold',
  human: 'blue',
  closed: 'green',
};

const STATE_LABELS: Record<InboxState, string> = {
  bot: 'Bot',
  waiting: 'Queued',
  human: 'With agent',
  closed: 'Closed',
};

// The insight labels (V4 F2) — shown only when the company opted in and a run
// classified the conversation. Colour is secondary to the word itself.
const SENTIMENT_COLORS: Record<string, string> = {
  positive: 'green',
  neutral: 'default',
  negative: 'orange',
  frustrated: 'red',
};

const RESOLUTION_COLORS: Record<string, string> = {
  resolved: 'green',
  unresolved: 'orange',
  escalated: 'purple',
  unknown: 'default',
};

const capitalise = (value: string) => value.charAt(0).toUpperCase() + value.slice(1);

/** The AI's sentiment/resolution tags of one conversation, or nothing. */
function InsightTags({
  sentiment,
  resolution,
}: {
  sentiment?: string | null;
  resolution?: string | null;
}) {
  if (!sentiment && !resolution) return null;
  return (
    <Space size={4} wrap>
      {sentiment && (
        <Tag color={SENTIMENT_COLORS[sentiment] || 'default'} style={{ fontSize: 11 }}>
          {capitalise(sentiment)}
        </Tag>
      )}
      {resolution && (
        <Tag color={RESOLUTION_COLORS[resolution] || 'default'} style={{ fontSize: 11 }}>
          {capitalise(resolution)}
        </Tag>
      )}
    </Space>
  );
}

function ageOf(iso: string | null | undefined): string {
  if (!iso) return '—';
  const then = new Date(iso).getTime();
  if (!Number.isFinite(then)) return '—';
  const seconds = Math.max(0, Math.round((Date.now() - then) / 1000));
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  if (hours < 24) return `${hours}h`;
  return `${Math.round(hours / 24)}d`;
}

function initials(name: string | null | undefined): string {
  const words = (name || '?').trim().split(/\s+/).slice(0, 2);
  const letters = words.map((word) => word[0]?.toUpperCase() || '').join('');
  return letters || '?';
}

/**
 * One SSE frame's `event:`/`data:` lines. A heartbeat is a bare comment, so
 * both stay null and the caller skips it.
 */
function parseFrame(raw: string): { event: string | null; data: string | null } {
  let event: string | null = null;
  let data: string | null = null;
  for (const line of raw.split('\n')) {
    if (line.startsWith('event:')) event = line.slice(6).trim();
    else if (line.startsWith('data:')) data = line.slice(5).trim();
  }
  return { event, data };
}

/** One stored message. `agent` is the team's own side, so it sits on the right. */
function Bubble({ item }: { item: InboxMessage }) {
  const fromTeam = item.role === 'agent';
  const who = fromTeam ? item.author_name || 'Agent' : item.role === 'user' ? 'Visitor' : 'Assistant';
  return (
    <div style={{ display: 'flex', justifyContent: fromTeam ? 'flex-end' : 'flex-start' }}>
      <div
        style={{
          maxWidth: '82%',
          background: fromTeam ? '#e6f4ff' : '#fff',
          border: '1px solid #eee',
          borderRadius: 10,
          padding: '8px 12px',
        }}
      >
        <Text type='secondary' style={{ fontSize: 11 }}>
          {who} · {new Date(item.created_at).toLocaleTimeString()}
        </Text>
        <Paragraph style={{ margin: 0, whiteSpace: 'pre-wrap' }}>{item.message}</Paragraph>
      </div>
    </div>
  );
}

export function Inbox() {
  const { user, isAuthenticated } = useAuth();

  const [statusLoaded, setStatusLoaded] = useState(false);
  const [enabled, setEnabled] = useState(false);

  const [stateFilter, setStateFilter] = useState<InboxState | 'all'>('waiting');
  const [page, setPage] = useState(1);
  const [queue, setQueue] = useState<InboxConversation[]>([]);
  const [total, setTotal] = useState(0);
  const [loadingQueue, setLoadingQueue] = useState(false);

  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<InboxConversationDetail | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const [presence, setPresence] = useState<InboxPresence[]>([]);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState(false);
  const [draft, setDraft] = useState('');

  // Every notification just bumps this: the queue and the open transcript are
  // re-read from the database, because pub/sub is a hint, not the truth.
  const [tick, setTick] = useState(0);
  const refresh = useCallback(() => setTick((value) => value + 1), []);

  const transcriptRef = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!isAuthenticated) return;
    let cancelled = false;
    getInboxStatus()
      .then((response) => {
        if (!cancelled) setEnabled(response.data.enabled);
      })
      .catch(() => {
        if (!cancelled) setEnabled(false);
      })
      .finally(() => {
        if (!cancelled) setStatusLoaded(true);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    setLoadingQueue(true);
    getInboxConversations({
      state: stateFilter === 'all' ? undefined : stateFilter,
      page,
      limit: PAGE_SIZE,
    })
      .then((response) => {
        if (cancelled) return;
        const items = response.data.items || [];
        setQueue(items);
        setTotal(response.data.total || 0);
        setSelectedId((current) =>
          current && items.some((item) => item.id === current)
            ? current
            : items[0]?.id ?? null,
        );
      })
      .catch((error) => {
        if (!cancelled) message.error(getApiErrorMessage(error, 'Failed to load the inbox'));
      })
      .finally(() => {
        if (!cancelled) setLoadingQueue(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, stateFilter, page, tick]);

  useEffect(() => {
    if (!enabled || !selectedId) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    setLoadingDetail(true);
    getInboxConversation(selectedId)
      .then((response) => {
        if (!cancelled) setDetail(response.data);
      })
      .catch((error) => {
        if (cancelled) return;
        if (getApiErrorStatus(error) === 404) {
          setDetail(null);
          setSelectedId(null);
          return;
        }
        message.error(getApiErrorMessage(error, 'Failed to load the conversation'));
      })
      .finally(() => {
        if (!cancelled) setLoadingDetail(false);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, selectedId, tick]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    getInboxPresence()
      .then((response) => {
        if (!cancelled) setPresence(response.data || []);
      })
      .catch(() => {
        if (!cancelled) setPresence([]);
      });
    return () => {
      cancelled = true;
    };
  }, [enabled, tick]);

  // The event stream: `fetch()` with the JWT, one reconnect loop. A dropped
  // socket is not an error — the refetch after reconnecting reconciles.
  useEffect(() => {
    if (!enabled || !isAuthenticated) {
      setLive(false);
      return;
    }
    const controller = new AbortController();
    let stopped = false;

    const sleep = (ms: number) =>
      new Promise<void>((resolve) => {
        const timer = setTimeout(resolve, ms);
        controller.signal.addEventListener('abort', () => {
          clearTimeout(timer);
          resolve();
        });
      });

    const run = async () => {
      let failures = 0;
      while (!stopped) {
        try {
          const response = await openInboxEvents(controller.signal);
          if (response.status === 404) {
            // The flag was turned off while the page was open.
            setEnabled(false);
            return;
          }
          if (!response.ok || !response.body) throw new Error(`stream ${response.status}`);
          failures = 0;
          setLive(true);
          const reader = response.body.getReader();
          const decoder = new TextDecoder();
          let buffer = '';
          while (!stopped) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            const frames = buffer.split('\n\n');
            buffer = frames.pop() || '';
            for (const frame of frames) {
              const parsed = parseFrame(frame);
              if (parsed.event || parsed.data) refresh();
            }
          }
        } catch {
          // Offline, blocked by a proxy, or logged out: retry below.
        }
        setLive(false);
        if (stopped) return;
        failures = Math.min(failures + 1, 4);
        await sleep(1000 * 2 ** failures);
      }
    };

    void run();
    return () => {
      stopped = true;
      controller.abort();
    };
  }, [enabled, isAuthenticated, refresh]);

  useEffect(() => {
    const element = transcriptRef.current;
    if (element) element.scrollTop = element.scrollHeight;
  }, [detail]);

  const runAction = async (label: string, action: () => Promise<unknown>) => {
    setBusy(true);
    try {
      await action();
      message.success(label);
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'That action failed'));
    } finally {
      setBusy(false);
    }
  };

  const sendReply = async () => {
    const text = draft.trim();
    if (!detail || !text) return;
    setBusy(true);
    try {
      await sendInboxReply(detail.id, text);
      setDraft('');
      refresh();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'The reply was not sent'));
    } finally {
      setBusy(false);
    }
  };

  if (!statusLoaded) return <Card loading />;

  if (!enabled) {
    return (
      <Card>
        <Empty description='The live-agent inbox is not enabled for this company' />
      </Card>
    );
  }

  const holdsConversation =
    !!detail && (detail.assigned_user_id === user?.id || user?.role === 'admin');
  const canReply = !!detail && detail.state === 'human' && holdsConversation;

  const composerHint = canReply
    ? 'Enter sends · Shift+Enter adds a line'
    : detail?.state === 'human'
      ? 'Another agent is handling this conversation'
      : 'Claim the conversation to reply';

  return (
    <>
      <Row
        justify='space-between'
        align='middle'
        gutter={[16, 16]}
        style={{ marginBottom: 16 }}
      >
        <Col>
          <Title level={2} style={{ fontWeight: 700, marginBottom: 4 }}>
            Inbox
          </Title>
          <Text type='secondary'>
            Answer visitors yourself — the bot stays quiet while a conversation is with an agent.
          </Text>
        </Col>
        <Col>
          <Space size='middle'>
            <Badge
              status={live ? 'processing' : 'default'}
              text={live ? 'Live' : 'Reconnecting'}
            />
            <Tooltip
              title={
                presence.length
                  ? presence
                      .map(
                        (agent) =>
                          `${agent.name || agent.user_id}${
                            agent.connections > 1 ? ` (${agent.connections} tabs)` : ''
                          }`,
                      )
                      .join(', ')
                  : 'Only you are online'
              }
            >
              <Avatar.Group max={{ count: 5 }} size='small'>
                {presence.map((agent) => (
                  <Avatar key={agent.user_id} style={{ backgroundColor: '#1677ff' }}>
                    {initials(agent.name)}
                  </Avatar>
                ))}
              </Avatar.Group>
            </Tooltip>
            <Text type='secondary'>
              {presence.length ? `${presence.length} online` : 'Only you'}
            </Text>
          </Space>
        </Col>
      </Row>

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={9}>
          <Card
            title={
              <Segmented
                size='small'
                value={stateFilter}
                onChange={(value) => {
                  setStateFilter(value as InboxState | 'all');
                  setPage(1);
                }}
                options={[
                  { label: 'Queued', value: 'waiting' },
                  { label: 'With agent', value: 'human' },
                  { label: 'Closed', value: 'closed' },
                  { label: 'All', value: 'all' },
                ]}
              />
            }
            styles={{ body: { padding: 0 } }}
          >
            <List<InboxConversation>
              loading={loadingQueue}
              dataSource={queue}
              locale={{
                emptyText: (
                  <Empty
                    description='Nothing here'
                    image={Empty.PRESENTED_IMAGE_SIMPLE}
                  />
                ),
              }}
              pagination={
                total > PAGE_SIZE
                  ? {
                      current: page,
                      pageSize: PAGE_SIZE,
                      total,
                      size: 'small',
                      onChange: setPage,
                    }
                  : false
              }
              renderItem={(item) => (
                <List.Item
                  onClick={() => setSelectedId(item.id)}
                  style={{
                    cursor: 'pointer',
                    padding: 12,
                    background: item.id === selectedId ? '#f0f5ff' : undefined,
                  }}
                >
                  <List.Item.Meta
                    title={
                      <Space size={6} wrap>
                        <Text strong style={{ maxWidth: 200 }}>
                          {item.title || 'New conversation'}
                        </Text>
                        <Tag color={STATE_COLORS[item.state]}>{STATE_LABELS[item.state]}</Tag>
                        <InsightTags
                          sentiment={item.sentiment}
                          resolution={item.resolution}
                        />
                      </Space>
                    }
                    description={
                      <Space direction='vertical' size={0}>
                        <Text type='secondary' style={{ fontSize: 12 }}>
                          {item.website_name || 'Website'} · waiting{' '}
                          {ageOf(item.last_message_at)}
                        </Text>
                        <Text type='secondary' style={{ fontSize: 12 }}>
                          {item.assigned_user_name
                            ? `Agent: ${item.assigned_user_name}`
                            : item.contact_name || 'Unassigned'}
                        </Text>
                      </Space>
                    }
                  />
                </List.Item>
              )}
            />
          </Card>
        </Col>

        <Col xs={24} lg={15}>
          <Card
            loading={loadingDetail}
            title={
              detail ? (
                <Space direction='vertical' size={0}>
                  <Space size={8} wrap>
                    <Text strong>{detail.contact_name || detail.title || 'Conversation'}</Text>
                    <Tag color={STATE_COLORS[detail.state]}>{STATE_LABELS[detail.state]}</Tag>
                  </Space>
                  <Text type='secondary' style={{ fontSize: 12 }}>
                    {detail.website_name || 'Website'} · {detail.contact_email || 'no contact'} ·{' '}
                    {detail.message_count} messages
                  </Text>
                </Space>
              ) : (
                'Conversation'
              )
            }
            extra={
              detail ? (
                <Space wrap>
                  {detail.state === 'waiting' && (
                    <Button
                      type='primary'
                      loading={busy}
                      onClick={() =>
                        runAction('Conversation claimed', () =>
                          claimInboxConversation(detail.id),
                        )
                      }
                    >
                      Claim
                    </Button>
                  )}
                  {detail.state === 'human' && holdsConversation && (
                    <Button
                      loading={busy}
                      onClick={() =>
                        runAction('Released to the queue', () =>
                          releaseInboxConversation(detail.id),
                        )
                      }
                    >
                      Release
                    </Button>
                  )}
                  {(detail.state === 'waiting' ||
                    (detail.state === 'human' && holdsConversation)) && (
                    <Popconfirm
                      title='Close this conversation?'
                      description='The bot answers again if the visitor writes.'
                      onConfirm={() =>
                        runAction('Conversation closed', () =>
                          closeInboxConversation(detail.id),
                        )
                      }
                    >
                      <Button danger loading={busy}>
                        Close
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              ) : null
            }
          >
            {detail ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
                {(detail.sentiment || detail.resolution || detail.summary) && (
                  <Alert
                    type='info'
                    showIcon
                    message={
                      <Space size={6} wrap>
                        <Text strong style={{ fontSize: 13 }}>
                          AI insight
                        </Text>
                        <InsightTags
                          sentiment={detail.sentiment}
                          resolution={detail.resolution}
                        />
                      </Space>
                    }
                    description={detail.summary || undefined}
                  />
                )}

                <div
                  ref={transcriptRef}
                  style={{
                    height: 420,
                    overflowY: 'auto',
                    padding: '8px',
                    background: '#fafafa',
                    borderRadius: 8,
                  }}
                >
                  <Space direction='vertical' size={10} style={{ width: '100%' }}>
                    {detail.messages.map((item) => (
                      <Bubble key={item.id} item={item} />
                    ))}
                  </Space>
                </div>

                <div>
                  <TextArea
                    rows={3}
                    value={draft}
                    onChange={(event) => setDraft(event.target.value)}
                    placeholder={
                      canReply
                        ? 'Write as the team…'
                        : detail.state === 'human'
                          ? 'Another agent is handling this conversation'
                          : 'Claim the conversation to reply'
                    }
                    disabled={!canReply}
                    onPressEnter={(event) => {
                      if (event.shiftKey) return;
                      event.preventDefault();
                      void sendReply();
                    }}
                  />
                  <Space
                    style={{ marginTop: 8, width: '100%', justifyContent: 'space-between' }}
                  >
                    <Text type='secondary' style={{ fontSize: 12 }}>
                      {composerHint}
                    </Text>
                    <Button
                      type='primary'
                      icon={<SendOutlined />}
                      disabled={!canReply || !draft.trim()}
                      loading={busy}
                      onClick={() => void sendReply()}
                    >
                      Send
                    </Button>
                  </Space>
                </div>

                {detail.contact && (
                  <Alert
                    type='info'
                    showIcon
                    message={`${detail.contact.first_name} ${detail.contact.last_name} · ${detail.contact.email}`}
                    description={
                      detail.contact.consent_at
                        ? `Consented ${new Date(detail.contact.consent_at).toLocaleString()}`
                        : undefined
                    }
                  />
                )}
              </div>
            ) : (
              <Empty description='Pick a conversation from the queue' />
            )}
          </Card>
        </Col>
      </Row>
    </>
  );
}
