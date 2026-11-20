import { DownloadOutlined, EyeOutlined, SendOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Col,
  Modal,
  Progress,
  Row,
  Select,
  Space,
  Statistic,
  Table,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type {
  AnalyticsSummary,
  DigestGroup,
  DigestTopic,
  FunnelStage,
  TopQuestion,
  TrendPoint,
  UnansweredQuestion,
} from '../types/api';
import {
  exportAnalyticsCsv,
  getAnalyticsSummary,
  getApiErrorMessage,
  previewDigest,
  sendDigestNow,
} from '../utils/api';

const { Title, Text } = Typography;

const WINDOWS = [
  { label: 'Last 7 days', value: 7 },
  { label: 'Last 30 days', value: 30 },
  { label: 'Last 90 days', value: 90 },
];

const CHART_WIDTH = 720;
const CHART_HEIGHT = 240;
const CHART_PADDING = { top: 20, right: 16, bottom: 32, left: 44 };

// Hand-rolled SVG (V4 D1: no chart library). The two fills are separated by
// luminance, not hue alone, so the series stay distinguishable in greyscale.
const MESSAGES_FILL = '#0958d9';
const CONVERSATIONS_FILL = '#bae0ff';

const STAGE_LABELS: Record<string, string> = {
  started: 'Conversations started',
  answered: 'Answered',
  lead: 'Became a lead',
  handoff: 'Asked for a human',
  human: 'Reached a human',
};

const stageLabel = (stage: string) => STAGE_LABELS[stage] ?? stage;

/**
 * Daily activity: grouped bars per UTC day (messages, conversations), with
 * direct value labels where the slot has room for them and axis labels behind.
 * An empty window says so instead of drawing an axis with nothing in it.
 */
function TrendChart({ points }: { points: TrendPoint[] }) {
  const hasData = points.some(
    (point) => point.messages > 0 || point.conversations > 0,
  );
  if (!hasData) {
    return <Text type='secondary'>No data in this window</Text>;
  }

  const plotWidth = CHART_WIDTH - CHART_PADDING.left - CHART_PADDING.right;
  const plotHeight = CHART_HEIGHT - CHART_PADDING.top - CHART_PADDING.bottom;
  const baseline = CHART_PADDING.top + plotHeight;
  const max = Math.max(
    1,
    ...points.map((point) => Math.max(point.messages, point.conversations)),
  );
  const slot = plotWidth / points.length;
  const barWidth = Math.max(1.5, Math.min(16, slot / 2 - 1));
  const gap = Math.min(2, slot / 4);
  // A 90-day window keeps the axis labels rather than overlapping numbers.
  const showMessagesLabels = slot >= 20;
  const showConversationLabels = slot >= 34;
  const labelStep = Math.max(1, Math.ceil(points.length / 10));
  const ticks = [0, Math.round(max / 2), max].filter(
    (value, index, list) => list.indexOf(value) === index,
  );
  const height = (value: number) => (value / max) * plotHeight;

  return (
    <>
      <svg
        role='img'
        aria-label='Daily messages and conversations'
        viewBox={`0 0 ${CHART_WIDTH} ${CHART_HEIGHT}`}
        style={{ width: '100%', height: 'auto' }}
      >
        {ticks.map((tick) => (
          <g key={tick}>
            <line
              x1={CHART_PADDING.left}
              x2={CHART_WIDTH - CHART_PADDING.right}
              y1={baseline - height(tick)}
              y2={baseline - height(tick)}
              stroke='#f0f0f0'
            />
            <text
              x={CHART_PADDING.left - 8}
              y={baseline - height(tick) + 3}
              textAnchor='end'
              fontSize={10}
              fill='#8c8c8c'
            >
              {tick}
            </text>
          </g>
        ))}

        {points.map((point, index) => {
          const start = CHART_PADDING.left + index * slot;
          const group = start + (slot - 2 * barWidth - gap) / 2;
          const messagesHeight = height(point.messages);
          const conversationsHeight = height(point.conversations);
          return (
            <g key={point.date}>
              <rect
                x={group}
                y={baseline - messagesHeight}
                width={barWidth}
                height={messagesHeight}
                rx={1}
                fill={MESSAGES_FILL}
              >
                <title>{`${point.date}: ${point.messages} messages`}</title>
              </rect>
              <rect
                x={group + barWidth + gap}
                y={baseline - conversationsHeight}
                width={barWidth}
                height={conversationsHeight}
                rx={1}
                fill={CONVERSATIONS_FILL}
              >
                <title>
                  {`${point.date}: ${point.conversations} conversations`}
                </title>
              </rect>
              {showMessagesLabels && (
                <text
                  x={group + barWidth / 2}
                  y={baseline - messagesHeight - 4}
                  textAnchor='middle'
                  fontSize={9}
                  fill='#595959'
                >
                  {point.messages}
                </text>
              )}
              {showConversationLabels && (
                <text
                  x={group + barWidth + gap + barWidth / 2}
                  y={baseline - conversationsHeight - 4}
                  textAnchor='middle'
                  fontSize={9}
                  fill='#8c8c8c'
                >
                  {point.conversations}
                </text>
              )}
              {index % labelStep === 0 && (
                <text
                  x={start + slot / 2}
                  y={baseline + 16}
                  textAnchor='middle'
                  fontSize={10}
                  fill='#8c8c8c'
                >
                  {point.date.slice(5)}
                </text>
              )}
            </g>
          );
        })}
      </svg>
      <Space size={16} style={{ marginTop: 8 }}>
        <Space size={6}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: MESSAGES_FILL,
            }}
          />
          <Text type='secondary' style={{ fontSize: 12 }}>
            Messages
          </Text>
        </Space>
        <Space size={6}>
          <span
            style={{
              display: 'inline-block',
              width: 10,
              height: 10,
              borderRadius: 2,
              background: CONVERSATIONS_FILL,
            }}
          />
          <Text type='secondary' style={{ fontSize: 12 }}>
            Conversations
          </Text>
        </Space>
      </Space>
    </>
  );
}

/**
 * The five stages as labelled horizontal bars: the count, and what share of the
 * previous stage it is. Stages count distinct sessions and overlap (a lead
 * without a handoff still counts), so the share is a ratio, not a strict drop.
 */
function FunnelBars({ stages }: { stages: FunnelStage[] }) {
  if (stages.length === 0 || stages.every((stage) => stage.sessions === 0)) {
    return <Text type='secondary'>No data in this window</Text>;
  }
  const max = Math.max(1, ...stages.map((stage) => stage.sessions));

  return (
    <Space direction='vertical' size={14} style={{ width: '100%' }}>
      {stages.map((stage, index) => {
        const previous = index > 0 ? stages[index - 1].sessions : null;
        const conversion =
          previous === null
            ? 'window total'
            : previous === 0
              ? '—'
              : `${Math.round((stage.sessions / previous) * 100)}% of ${stageLabel(
                  stages[index - 1].stage,
                ).toLowerCase()}`;
        return (
          <div key={stage.stage}>
            <div
              style={{
                display: 'flex',
                justifyContent: 'space-between',
                gap: 12,
                marginBottom: 4,
              }}
            >
              <Text>{stageLabel(stage.stage)}</Text>
              <Space size={8}>
                <Text strong>{stage.sessions}</Text>
                <Text type='secondary' style={{ fontSize: 12 }}>
                  {conversion}
                </Text>
              </Space>
            </div>
            <div
              style={{
                height: 10,
                background: '#f0f0f0',
                borderRadius: 5,
                overflow: 'hidden',
              }}
            >
              <div
                style={{
                  width: `${(stage.sessions / max) * 100}%`,
                  height: '100%',
                  background: MESSAGES_FILL,
                  borderRadius: 5,
                }}
              />
            </div>
          </div>
        );
      })}
    </Space>
  );
}

export function Analytics() {
  const { isAuthenticated } = useAuth();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [sending, setSending] = useState(false);
  const [exporting, setExporting] = useState(false);

  const fetchSummary = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getAnalyticsSummary(days);
      setData(response.data);
    } catch (error) {
      console.error('Fetch analytics error', error);
      message.error('Failed to load analytics');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, days]);

  useEffect(() => {
    fetchSummary();
  }, [fetchSummary]);

  const openPreview = async () => {
    setPreviewing(true);
    try {
      const response = await previewDigest();
      setPreviewHtml(response.data.html);
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to render the digest'));
    } finally {
      setPreviewing(false);
    }
  };

  const sendNow = async () => {
    setSending(true);
    try {
      const response = await sendDigestNow();
      const result = response.data;
      if (result.status === 'sent') {
        message.success(`Digest sent to ${result.recipients ?? 0} recipient(s)`);
      } else if (result.status === 'empty') {
        message.info('No activity this week, so no digest was sent');
      } else {
        message.warning(result.reason || `Digest not sent (${result.status})`);
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to send the digest'));
    } finally {
      setSending(false);
    }
  };

  const downloadCsv = async () => {
    setExporting(true);
    try {
      await exportAnalyticsCsv(days);
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to export the CSV'));
    } finally {
      setExporting(false);
    }
  };

  const ratings = data ? data.feedback_up + data.feedback_down : 0;
  const positiveShare = ratings > 0 ? Math.round(((data?.feedback_up ?? 0) / ratings) * 100) : 0;
  // Only populated when the window is exactly one completed digest week.
  const groups = data?.topic_groups ?? [];

  const topicColumns: ColumnsType<DigestTopic> = [
    { title: 'Topic', dataIndex: 'term', key: 'term' },
    { title: 'Mentions', dataIndex: 'count', key: 'count', width: 110 },
  ];

  const groupColumns: ColumnsType<DigestGroup> = [
    { title: 'Topic', dataIndex: 'label', key: 'label' },
    {
      title: 'Summary',
      dataIndex: 'summary',
      key: 'summary',
      render: (text: string | null) => text || <Text type='secondary'>—</Text>,
    },
  ];

  const questionColumns: ColumnsType<TopQuestion> = [
    { title: 'Question', dataIndex: 'question', key: 'question' },
    { title: 'Asked', dataIndex: 'count', key: 'count', width: 110 },
  ];

  const unansweredColumns: ColumnsType<UnansweredQuestion> = [
    {
      title: 'Question',
      dataIndex: 'question',
      key: 'question',
      render: (text: string | null, item) => (
        <Space direction='vertical' size={0}>
          <Text strong>{text || 'Unavailable question'}</Text>
          <Text type='secondary' style={{ fontSize: 12 }}>
            {item.website_name || 'Unknown website'}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Asked',
      dataIndex: 'asked_at',
      key: 'asked_at',
      width: 190,
      render: (text: string) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text ? new Date(text).toLocaleString() : '—'}
        </Text>
      ),
    },
    {
      title: 'Open',
      key: 'open',
      width: 100,
      render: (_, item) => (
        <Link to={`/chat?website=${item.website_id}&focus=${item.session_id}`}>
          Transcript
        </Link>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={2} style={{ fontWeight: 700, marginBottom: 8 }}>
          Analytics
        </Title>
        <Text type='secondary'>
          What visitors asked, and what your content could not answer yet.
        </Text>
      </div>

      <Card style={{ marginBottom: 16 }}>
        <Row gutter={[16, 16]} align='middle' style={{ marginBottom: 16 }}>
          <Col xs={12} md={5}>
            <Select
              style={{ width: '100%' }}
              value={days}
              onChange={setDays}
              options={WINDOWS}
            />
          </Col>
          <Col xs={12} md={7}>
            {/* `wrap` keeps the pair inside its half-width column on a phone
                instead of pushing the card past the viewport. */}
            <Space wrap>
              <Button
                icon={<EyeOutlined />}
                loading={previewing}
                onClick={openPreview}
              >
                Preview digest
              </Button>
              <Button
                type='primary'
                icon={<SendOutlined />}
                loading={sending}
                onClick={sendNow}
              >
                Send now
              </Button>
            </Space>
          </Col>
          <Col xs={12} md={4}>
            <Button
              icon={<DownloadOutlined />}
              loading={exporting}
              onClick={downloadCsv}
            >
              Export CSV
            </Button>
          </Col>
        </Row>

        <Row gutter={[16, 16]}>
          <Col xs={12} md={5}>
            <Statistic
              title='Conversations'
              value={data?.conversation_volume ?? 0}
              loading={loading}
            />
          </Col>
          <Col xs={12} md={5}>
            <Statistic
              title='Messages'
              value={data?.message_count ?? 0}
              loading={loading}
            />
          </Col>
          <Col xs={12} md={5}>
            <Statistic
              title='New contacts'
              value={data?.new_contacts ?? 0}
              loading={loading}
            />
          </Col>
          <Col xs={12} md={4}>
            <Statistic
              title='👍 / 👎'
              value={`${data?.feedback_up ?? 0} / ${data?.feedback_down ?? 0}`}
              loading={loading}
            />
          </Col>
          <Col xs={12} md={5}>
            <Text type='secondary' style={{ fontSize: 12 }}>
              Helpful share
            </Text>
            <Progress percent={positiveShare} size='small' />
          </Col>
        </Row>
      </Card>

      <Card title='Daily activity' style={{ marginBottom: 16 }} loading={loading}>
        <TrendChart points={data?.trend ?? []} />
      </Card>

      <Card
        title='Engagement funnel'
        style={{ marginBottom: 16 }}
        loading={loading}
        extra={
          <Text type='secondary' style={{ fontSize: 12 }}>
            Distinct sessions; stages overlap
          </Text>
        }
      >
        <FunnelBars stages={data?.funnel ?? []} />
      </Card>

      <Card title='Top questions' style={{ marginBottom: 16 }}>
        <Table
          columns={questionColumns}
          dataSource={data?.top_questions ?? []}
          loading={loading}
          rowKey='question'
          pagination={false}
          size='small'
          locale={{ emptyText: 'No questions in this window' }}
        />
      </Card>

      {groups.length > 0 ? (
        <Card
          title='Topic groups'
          style={{ marginBottom: 16 }}
          extra={
            <Text type='secondary' style={{ fontSize: 12 }}>
              Named from {groups[0].sampled_messages} of{' '}
              {groups[0].eligible_messages} visitor questions
            </Text>
          }
        >
          <Table
            columns={groupColumns}
            dataSource={groups}
            loading={loading}
            rowKey={(_, index) => String(index)}
            pagination={false}
            size='small'
          />
        </Card>
      ) : (
        <Card title='Top topics' style={{ marginBottom: 16 }}>
          <Table
            columns={topicColumns}
            dataSource={data?.top_topics ?? []}
            loading={loading}
            rowKey='term'
            pagination={false}
            size='small'
            locale={{ emptyText: 'No visitor questions in this window' }}
          />
        </Card>
      )}

      <Card title='Questions your content could not answer'>
        <Table
          columns={unansweredColumns}
          dataSource={data?.unanswered_questions ?? []}
          loading={loading}
          rowKey={(item) => `${item.session_id}-${item.asked_at}`}
          pagination={false}
          size='small'
          locale={{ emptyText: 'Every question was answered from your content' }}
        />
      </Card>

      <Modal
        open={previewHtml !== null}
        title='Weekly digest preview'
        onCancel={() => setPreviewHtml(null)}
        footer={
          <Button type='primary' onClick={() => setPreviewHtml(null)}>
            Close
          </Button>
        }
        width={720}
      >
        {/* The digest is our own generated, escaped HTML; the iframe keeps it
            isolated from the admin app either way. */}
        <iframe
          title='digest preview'
          srcDoc={previewHtml ?? ''}
          sandbox=''
          style={{ width: '100%', height: 420, border: '1px solid #e5e7eb' }}
        />
      </Modal>
    </>
  );
}
