import { CheckOutlined, CloseOutlined, SyncOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Col,
  Input,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import type { FeedbackItem, Website } from '../types/api';
import api, {
  getApiErrorMessage,
  getFeedback,
  rebuildQa,
  reviewFeedback,
} from '../utils/api';

const { Title, Text } = Typography;
const { TextArea } = Input;

const STATUS_COLORS: Record<string, string> = {
  pending: 'gold',
  approved: 'green',
  rejected: 'red',
};

export function Training() {
  const { isAuthenticated } = useAuth();
  const [websites, setWebsites] = useState<Website[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState('');
  const [status, setStatus] = useState<'pending' | 'approved' | 'rejected'>(
    'pending',
  );
  const [items, setItems] = useState<FeedbackItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [loading, setLoading] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [rebuilding, setRebuilding] = useState(false);
  // Edited answers live here until the admin approves, so typing never
  // round-trips to the server.
  const [drafts, setDrafts] = useState<Record<string, string>>({});

  const fetchWebsites = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const response = await api.get('/websites', {
        params: { page: 1, limit: 100 },
      });
      const list: Website[] = response.data.items || [];
      setWebsites(list);
      setSelectedWebsiteId((prev) => prev || (list[0]?.id ?? ''));
    } catch (error) {
      console.error('Fetch websites error', error);
      message.error('Failed to load websites');
    }
  }, [isAuthenticated]);

  const fetchFeedback = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getFeedback({
        website_id: selectedWebsiteId || undefined,
        status,
        // Only 👎 answers need training; 👍 ratings are positive signal only.
        rating: 'down',
        page,
        limit,
      });
      setItems(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch feedback error', error);
      message.error('Failed to load feedback');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, selectedWebsiteId, status, page, limit]);

  useEffect(() => {
    fetchWebsites();
  }, [fetchWebsites]);

  useEffect(() => {
    fetchFeedback();
  }, [fetchFeedback]);

  const review = async (item: FeedbackItem, decision: 'approved' | 'rejected') => {
    setBusyId(item.id);
    try {
      await reviewFeedback(item.id, {
        status: decision,
        ...(decision === 'approved'
          ? { reviewed_answer: drafts[item.id] ?? item.answer ?? '' }
          : {}),
      });
      message.success(
        decision === 'approved'
          ? 'Approved and added to the training corpus'
          : 'Rejected',
      );
      await fetchFeedback();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to update the feedback'));
    } finally {
      setBusyId(null);
    }
  };

  const rebuild = async () => {
    if (!selectedWebsiteId) return;
    setRebuilding(true);
    try {
      const response = await rebuildQa(selectedWebsiteId);
      message.success(
        `Training document rebuilt from ${response.data.approved} approved pair(s)`,
      );
    } catch (error) {
      message.error(
        getApiErrorMessage(error, 'Failed to rebuild the training document'),
      );
    } finally {
      setRebuilding(false);
    }
  };

  const columns: ColumnsType<FeedbackItem> = [
    {
      title: 'Question',
      dataIndex: 'question',
      key: 'question',
      render: (text: string | null, item) => (
        <Space direction='vertical' size={0} style={{ maxWidth: 260 }}>
          <Text strong>{text || 'Unavailable'}</Text>
          <Text type='secondary' style={{ fontSize: 12 }}>
            {item.session_id}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Original answer',
      dataIndex: 'answer',
      key: 'answer',
      render: (text: string | null) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text || '—'}
        </Text>
      ),
    },
    {
      title: 'Corrected answer',
      key: 'reviewed_answer',
      render: (_, item) => (
        <TextArea
          rows={3}
          value={drafts[item.id] ?? item.reviewed_answer ?? item.answer ?? ''}
          onChange={(e) =>
            setDrafts((prev) => ({ ...prev, [item.id]: e.target.value }))
          }
          disabled={item.status === 'rejected'}
        />
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (value: string) => <Tag color={STATUS_COLORS[value]}>{value}</Tag>,
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, item) => (
        <Space>
          <Button
            type='primary'
            size='small'
            icon={<CheckOutlined />}
            loading={busyId === item.id}
            disabled={!item.message_id}
            onClick={() => review(item, 'approved')}
          >
            Approve
          </Button>
          <Button
            danger
            size='small'
            icon={<CloseOutlined />}
            loading={busyId === item.id}
            onClick={() => review(item, 'rejected')}
          >
            Reject
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={2} style={{ fontWeight: 700, marginBottom: 8 }}>
          Training
        </Title>
        <Text type='secondary'>
          Fix the answers visitors marked as unhelpful. Approved pairs are added
          to the website&apos;s knowledge base; rejected ones are not.
        </Text>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }} align='middle'>
          <Col xs={24} md={8}>
            <Select
              placeholder='Select website'
              style={{ width: '100%' }}
              value={selectedWebsiteId || undefined}
              onChange={(value) => {
                setSelectedWebsiteId(value);
                setPage(1);
              }}
              options={websites.map((w) => ({ value: w.id, label: w.name }))}
            />
          </Col>
          <Col xs={12} md={5}>
            <Select
              style={{ width: '100%' }}
              value={status}
              onChange={(value) => {
                setStatus(value);
                setPage(1);
              }}
              options={[
                { value: 'pending', label: 'Pending' },
                { value: 'approved', label: 'Approved' },
                { value: 'rejected', label: 'Rejected' },
              ]}
            />
          </Col>
          <Col xs={12} md={6}>
            <Button
              icon={<SyncOutlined />}
              loading={rebuilding}
              disabled={!selectedWebsiteId}
              onClick={rebuild}
            >
              Rebuild corpus
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey='id'
          pagination={{
            current: page,
            total,
            pageSize: limit,
            onChange: setPage,
          }}
          locale={{ emptyText: 'No feedback in this view' }}
        />
      </Card>
    </>
  );
}
