import { Input, Pagination, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Company } from '../types/api';
import { getCompanies } from '../utils/api';

const { Text } = Typography;

interface Props {}

export function CompanyTable({}: Props) {
  const [data, setData] = useState<Company[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [nameFilter, setNameFilter] = useState('');
  const { isAuthenticated } = useAuth();

  const columns: ColumnsType<Company> = [
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

  const fetchCompanies = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getCompanies({
        name: nameFilter || undefined,
        page,
        limit,
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch companies error', error);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchCompanies();
  }, [page, nameFilter, isAuthenticated]);

  return (
    <>
      <Input.Search
        placeholder='Search companies...'
        onSearch={setNameFilter}
        style={{
          width: '100%',
          marginBottom: 20,
          borderRadius: '8px',
        }}
        allowClear
        size='large'
      />
      <Table
        columns={columns}
        dataSource={data}
        loading={loading}
        pagination={false}
        rowKey='id'
        size='middle'
      />
      <Pagination
        current={page}
        total={total}
        pageSize={limit}
        onChange={setPage}
        style={{
          marginTop: 20,
          textAlign: 'right',
          display: 'flex',
          justifyContent: 'flex-end',
        }}
      />
    </>
  );
}
