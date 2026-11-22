import { Alert, Input, Table, Tag, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import type { PlatformCompany } from '../../types/api';
import { getPlatformCompanies } from '../../utils/api';
import { formatDate, platformErrorMessage } from './shared';

const { Title, Paragraph, Text } = Typography;

export function CompaniesSection() {
  const [items, setItems] = useState<PlatformCompany[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformCompanies({
        search: search || undefined,
        page,
        page_size: pageSize,
      });
      setItems(response.data.items);
      setTotal(response.data.total);
    } catch (reason) {
      setError(platformErrorMessage(reason, 'Could not load companies.'));
    } finally {
      setLoading(false);
    }
  }, [search, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<PlatformCompany> = [
    {
      title: 'Company',
      dataIndex: 'name',
      render: (name: string, row) => (
        <div>
          <Text strong>{name}</Text>
          <div>
            <Text type='secondary' style={{ fontSize: 12 }}>
              {row.id}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: 'Plan',
      dataIndex: 'plan_code',
      render: (value: string | null, row) =>
        value ? `${value}${row.interval ? ` · ${row.interval}` : ''}` : '—',
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (value: string | null) =>
        value ? (
          <Tag color={value === 'active' ? 'green' : value === 'past_due' ? 'orange' : 'default'}>
            {value}
          </Tag>
        ) : (
          '—'
        ),
    },
    {
      title: 'Period end',
      dataIndex: 'current_period_end',
      render: (value: string | null, row) =>
        value ? (
          <span>
            {formatDate(value)}
            {row.cancel_at_period_end ? ' (cancels)' : ''}
          </span>
        ) : (
          '—'
        ),
    },
    { title: 'Websites', dataIndex: 'websites', align: 'right' },
    { title: 'Active users', dataIndex: 'active_users', align: 'right' },
    {
      title: 'Created',
      dataIndex: 'created_at',
      render: (value: string) => formatDate(value),
    },
  ];

  return (
    <div>
      <Title level={3}>Companies</Title>
      <Paragraph type='secondary'>
        Read-only cross-company view. Subscription operations live in the
        Subscriptions section.
      </Paragraph>
      {error && <Alert type='error' showIcon message={error} style={{ marginBottom: 16 }} />}
      <Input.Search
        placeholder='Search by company name'
        allowClear
        onSearch={(value) => {
          setSearch(value.trim());
          setPage(1);
        }}
        style={{ maxWidth: 360, marginBottom: 16 }}
      />
      <Table
        rowKey='id'
        size='small'
        loading={loading}
        columns={columns}
        dataSource={items}
        pagination={{
          current: page,
          pageSize,
          total,
          showSizeChanger: true,
          pageSizeOptions: [10, 25, 50, 100],
          onChange: (nextPage, nextSize) => {
            setPage(nextPage);
            setPageSize(nextSize);
          },
        }}
      />
    </div>
  );
}
