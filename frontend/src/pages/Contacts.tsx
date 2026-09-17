import { Card, Col, Row, Select, Table, Typography, message } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Contact, Website } from '../types/api';
import api, { getContacts } from '../utils/api';

const { Title, Text } = Typography;

export function Contacts() {
  const [websites, setWebsites] = useState<Website[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string>('');
  const [data, setData] = useState<Contact[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const { isAuthenticated } = useAuth();

  const columns: ColumnsType<Contact> = [
    {
      title: 'First Name',
      dataIndex: 'first_name',
      key: 'first_name',
      render: (text) => (
        <Text strong style={{ color: '#111827' }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'Last Name',
      dataIndex: 'last_name',
      key: 'last_name',
    },
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
    },
    {
      title: 'Session',
      dataIndex: 'session_id',
      key: 'session_id',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '12px' }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'Created At',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text) =>
        text ? (
          <Text type='secondary' style={{ fontSize: '14px' }}>
            {new Date(text).toLocaleString()}
          </Text>
        ) : (
          '—'
        ),
    },
  ];

  const fetchWebsites = async () => {
    if (!isAuthenticated) return;
    try {
      const response = await api.get('/websites', {
        params: { page: 1, limit: 100 },
      });
      const items: Website[] = response.data.items || [];
      setWebsites(items);
      if (items.length > 0 && !selectedWebsiteId) {
        setSelectedWebsiteId(items[0].id);
      }
    } catch (error) {
      console.error('Fetch websites error', error);
      message.error('Failed to load websites');
    }
  };

  const fetchContacts = async () => {
    if (!isAuthenticated || !selectedWebsiteId) return;
    setLoading(true);
    try {
      const response = await getContacts(selectedWebsiteId, {
        limit,
        offset: (page - 1) * limit,
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch contacts error', error);
      message.error('Failed to load contacts');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWebsites();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isAuthenticated]);

  useEffect(() => {
    fetchContacts();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWebsiteId, page, isAuthenticated]);

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title
          level={2}
          style={{
            fontWeight: 700,
            marginBottom: 8,
            letterSpacing: '-0.5px',
          }}
        >
          Contacts
        </Title>
        <Text type='secondary'>
          Visitors who filled the pre-chat form on your websites
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
        </Row>

        <Table
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: limit,
            onChange: setPage,
          }}
          rowKey='id'
        />
      </Card>
    </>
  );
}
