import { Alert, Select, Space, Table, Typography } from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import type { PlatformAuditEvent } from '../../types/api';
import { getPlatformAudit } from '../../utils/api';
import { formatDateTime, platformErrorMessage } from './shared';

const { Title, Paragraph, Text } = Typography;

export function AuditSection() {
  const [events, setEvents] = useState<PlatformAuditEvent[]>([]);
  const [limit, setLimit] = useState(50);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformAudit(limit);
      setEvents(response.data.events);
    } catch (reason) {
      setError(platformErrorMessage(reason, 'Could not load the audit trail.'));
    } finally {
      setLoading(false);
    }
  }, [limit]);

  useEffect(() => {
    void load();
  }, [load]);

  const columns: ColumnsType<PlatformAuditEvent> = [
    {
      title: 'When',
      dataIndex: 'created_at',
      width: 180,
      render: (value: string) => formatDateTime(value),
    },
    { title: 'Action', dataIndex: 'action', width: 280 },
    {
      title: 'Target',
      render: (_, row) =>
        `${row.target_type}${row.target_id ? ` · ${row.target_id}` : ''}`,
    },
    {
      title: 'Actor',
      render: (_, row) => row.actor_label ?? row.actor_user_id ?? '—',
    },
    {
      title: 'Detail',
      dataIndex: 'detail',
      render: (detail: Record<string, unknown> | null) =>
        detail ? (
          <Text code style={{ fontSize: 12, whiteSpace: 'pre-wrap' }}>
            {JSON.stringify(detail)}
          </Text>
        ) : (
          '—'
        ),
    },
  ];

  return (
    <div>
      <Title level={3}>Audit</Title>
      <Paragraph type='secondary'>
        Append-only. Every operator mutation records actor, action, target and
        time; secret-shaped detail is redacted before storage. There is no API
        to edit or delete a row.
      </Paragraph>
      {error && <Alert type='error' showIcon message={error} style={{ marginBottom: 16 }} />}
      <Space style={{ marginBottom: 16 }}>
        <Text type='secondary'>Rows</Text>
        <Select
          value={limit}
          style={{ width: 100 }}
          options={[25, 50, 100, 200].map((value) => ({ value, label: value }))}
          onChange={(value) => setLimit(value)}
        />
      </Space>
      <Table
        rowKey='id'
        size='small'
        loading={loading}
        columns={columns}
        dataSource={events}
        pagination={false}
        scroll={{ x: 960 }}
      />
    </div>
  );
}
