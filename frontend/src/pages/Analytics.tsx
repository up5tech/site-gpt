import { EyeOutlined, SendOutlined } from '@ant-design/icons';
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
  DigestTopic,
  UnansweredQuestion,
} from '../types/api';
import {
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

export function Analytics() {
  const { isAuthenticated } = useAuth();
  const [days, setDays] = useState(7);
  const [data, setData] = useState<AnalyticsSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [previewHtml, setPreviewHtml] = useState<string | null>(null);
  const [previewing, setPreviewing] = useState(false);
  const [sending, setSending] = useState(false);

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

  const ratings = data ? data.feedback_up + data.feedback_down : 0;
  const positiveShare = ratings > 0 ? Math.round(((data?.feedback_up ?? 0) / ratings) * 100) : 0;

  const topicColumns: ColumnsType<DigestTopic> = [
    { title: 'Topic', dataIndex: 'term', key: 'term' },
    { title: 'Mentions', dataIndex: 'count', key: 'count', width: 110 },
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
            <Space>
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
