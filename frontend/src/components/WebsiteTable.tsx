import { Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../utils/api';

const { Text } = Typography;

interface Website {
  id: string;
  name: string;
  url: string;
  description: string;
  site_map_url: string;
}

export function WebsiteTable() {
  const [data, setData] = useState<Website[]>([]);
  const [loading, setLoading] = useState(false);
  const { isAuthenticated } = useAuth();

  const columns: ColumnsType<Website> = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text) => (
        <Text strong style={{ color: '#111827' }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      render: (text) => <Text style={{ fontSize: '14px' }}>{text}</Text>,
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '14px' }}>
          {text || '—'}
        </Text>
      ),
    },
  ];

  const fetchWebsites = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await api.get('/websites', {
        params: {
          page: 1,
          limit: 10,
        },
      });
      setData(response.data.items || []);
    } catch (error) {
      console.error('Fetch websites error', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWebsites();
  }, [isAuthenticated]);

  return (
    <Table
      columns={columns}
      dataSource={data}
      loading={loading}
      pagination={false}
      rowKey='id'
      size='middle'
    />
  );
}
