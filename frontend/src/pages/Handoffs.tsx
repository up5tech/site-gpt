import { Card, Col, Row, Select, Space, Table, Tag, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import type { HandoffItem, Website } from '../types/api';
import api, { getApiErrorMessage, getHandoffs, updateHandoff } from '../utils/api';

const { Title, Text } = Typography;

const STATUS_COLORS: Record<string, string> = {
  pending: 'gold',
  accepted: 'blue',
  closed: 'green',
};

const STATUSES = ['pending', 'accepted', 'closed'] as const;

export function Handoffs() {
  const { isAuthenticated } = useAuth();
  const [websites, setWebsites] = useState<Website[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState('');
  const [status, setStatus] = useState<'pending' | 'accepted' | 'closed' | ''>('');
  const [data, setData] = useState<HandoffItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchWebsites = useCallback(async () => {
    if (!isAuthenticated) return;
    try {
      const response = await api.get('/websites', {
        params: { page: 1, limit: 100 },
      });
      const items: Website[] = response.data.items || [];
      setWebsites(items);
      setSelectedWebsiteId((prev) => prev || (items[0]?.id ?? ''));
    } catch (error) {
      console.error('Fetch websites error', error);
      message.error('Failed to load websites');
    }
  }, [isAuthenticated]);

  const fetchHandoffs = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getHandoffs({
        website_id: selectedWebsiteId || undefined,
        status: status || undefined,
        page,
        limit,
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch handoffs error', error);
      message.error('Failed to load handoff requests');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, selectedWebsiteId, status, page, limit]);

  useEffect(() => {
    fetchWebsites();
  }, [fetchWebsites]);

  useEffect(() => {
    fetchHandoffs();
  }, [fetchHandoffs]);

  const changeStatus = async (item: HandoffItem, next: string) => {
    setBusyId(item.id);
    try {
      await updateHandoff(item.id, {
        status: next as 'pending' | 'accepted' | 'closed',
      });
      message.success(`Marked as ${next}`);
      await fetchHandoffs();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to update the request'));
    } finally {
      setBusyId(null);
    }
  };

  const columns: ColumnsType<HandoffItem> = [
    {
      title: 'Visitor',
      key: 'visitor',
      render: (_, item) => (
        <Space direction='vertical' size={0}>
          <Text strong>{item.contact_name || 'Anonymous visitor'}</Text>
          <Text type='secondary' style={{ fontSize: 12 }}>
            {item.contact_email || '—'}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Website',
      dataIndex: 'website_name',
      key: 'website_name',
      render: (text: string | null) => text || '—',
    },
    {
      title: 'Message',
      dataIndex: 'message',
      key: 'message',
      render: (text: string | null) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text || 'No message'}
        </Text>
      ),
    },
    {
      title: 'Session',
      dataIndex: 'session_id',
      key: 'session_id',
      render: (text: string) => (
        <Text type='secondary' style={{ fontSize: 12 }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (value: string) => <Tag color={STATUS_COLORS[value]}>{value}</Tag>,
    },
    {
      title: 'Received',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text: string) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text ? new Date(text).toLocaleString() : '—'}
        </Text>
      ),
    },
    {
      title: 'Update',
      key: 'update',
      render: (_, item) => (
        <Select
          size='small'
          style={{ width: 110 }}
          value={item.status}
          loading={busyId === item.id}
          onChange={(next) => changeStatus(item, next)}
          options={STATUSES.map((value) => ({ value, label: value }))}
        />
      ),
    },
  ];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={2} style={{ fontWeight: 700, marginBottom: 8 }}>
          Handoffs
        </Title>
        <Text type='secondary'>
          Visitors who asked to talk to a human from your widget
        </Text>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
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
              placeholder='Any status'
              value={status || undefined}
              allowClear
              onChange={(value) => {
                setStatus(value || '');
                setPage(1);
              }}
              options={STATUSES.map((value) => ({ value, label: value }))}
            />
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={data}
          loading={loading}
          rowKey='id'
          pagination={{
            current: page,
            total,
            pageSize: limit,
            onChange: setPage,
          }}
          locale={{ emptyText: 'No handoff requests yet' }}
        />
      </Card>
    </>
  );
}
