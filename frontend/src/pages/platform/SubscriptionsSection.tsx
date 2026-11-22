import {
  Alert,
  Button,
  Checkbox,
  Input,
  message,
  Modal,
  Select,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import type {
  PlatformSubscription,
  PlatformSubscriptionAction,
} from '../../types/api';
import {
  getPlatformSubscriptions,
  runPlatformSubscriptionAction,
} from '../../utils/api';
import { formatDate, formatDateTime, platformErrorMessage } from './shared';

const { Title, Paragraph, Text } = Typography;

const STATUSES = [
  'active',
  'trialing',
  'past_due',
  'unpaid',
  'incomplete',
  'paused',
  'canceled',
];

const ACTION_LABEL: Record<PlatformSubscriptionAction, string> = {
  cancel_at_period_end: 'Cancel at period end',
  request_reconciliation: 'Request reconciliation',
};

export function SubscriptionsSection() {
  const [items, setItems] = useState<PlatformSubscription[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [status, setStatus] = useState<string | undefined>();
  const [search, setSearch] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [target, setTarget] = useState<{
    row: PlatformSubscription;
    action: PlatformSubscriptionAction;
  } | null>(null);
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [saving, setSaving] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformSubscriptions({
        status: status || undefined,
        search: search || undefined,
        page,
        page_size: pageSize,
      });
      setItems(response.data.items);
      setTotal(response.data.total);
    } catch (reasonValue) {
      setError(platformErrorMessage(reasonValue, 'Could not load subscriptions.'));
    } finally {
      setLoading(false);
    }
  }, [status, search, page, pageSize]);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (
    row: PlatformSubscription,
    action: PlatformSubscriptionAction,
  ) => {
    setTarget({ row, action });
    setReason('');
    setConfirmed(false);
  };

  const submit = async () => {
    if (!target) return;
    setSaving(true);
    try {
      await runPlatformSubscriptionAction(target.row.company_id, {
        action: target.action,
        reason,
        confirm: target.action === 'cancel_at_period_end' ? confirmed : false,
      });
      message.success(
        target.action === 'cancel_at_period_end'
          ? 'Stripe accepted the cancellation request; the mirror updates when the webhook arrives.'
          : 'Reconciliation request recorded in the audit trail.',
      );
      setTarget(null);
      void load();
    } catch (errorValue) {
      message.error(
        platformErrorMessage(errorValue, 'The action could not be completed.'),
      );
    } finally {
      setSaving(false);
    }
  };

  const columns: ColumnsType<PlatformSubscription> = [
    {
      title: 'Company',
      dataIndex: 'company_name',
      render: (name: string, row) => (
        <div>
          <Text strong>{name}</Text>
          <div>
            <Text type='secondary' style={{ fontSize: 12 }}>
              {row.company_id}
            </Text>
          </div>
        </div>
      ),
    },
    {
      title: 'Plan',
      render: (_, row) => `${row.plan_code}${row.interval ? ` · ${row.interval}` : ''}`,
    },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (value: string) => (
        <Tag
          color={
            value === 'active' || value === 'trialing'
              ? 'green'
              : value === 'past_due' || value === 'unpaid'
                ? 'orange'
                : 'default'
          }
        >
          {value}
        </Tag>
      ),
    },
    {
      title: 'Period',
      render: (_, row) =>
        `${formatDate(row.current_period_start)} → ${formatDate(row.current_period_end)}`,
    },
    {
      title: 'Cancel at end',
      dataIndex: 'cancel_at_period_end',
      render: (value: boolean) => (value ? 'Yes' : 'No'),
    },
    {
      title: 'Stripe refs',
      render: (_, row) => (
        <Text type='secondary' style={{ fontSize: 12 }}>
          {row.stripe_customer_id ?? '—'}
          <br />
          {row.stripe_subscription_id ?? '—'}
          {row.last_event_at ? (
            <>
              <br />
              event {formatDateTime(row.last_event_at)}
            </>
          ) : null}
        </Text>
      ),
    },
    {
      title: 'Actions',
      render: (_, row) => (
        <Space direction='vertical' size={4}>
          <Button size='small' onClick={() => open(row, 'request_reconciliation')}>
            Reconcile
          </Button>
          <Button
            size='small'
            danger
            disabled={row.status === 'canceled'}
            onClick={() => open(row, 'cancel_at_period_end')}
          >
            Cancel at end
          </Button>
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Subscriptions</Title>
      <Paragraph type='secondary'>
        Stripe is authoritative. Cancelling asks Stripe and never edits the
        local row; a verified webhook applies the change. There is no action
        that grants or marks a subscription paid.
      </Paragraph>
      {error && <Alert type='error' showIcon message={error} style={{ marginBottom: 16 }} />}
      <Space style={{ marginBottom: 16 }} wrap>
        <Select
          allowClear
          placeholder='Any status'
          style={{ width: 180 }}
          options={STATUSES.map((value) => ({ value, label: value }))}
          value={status}
          onChange={(value) => {
            setStatus(value);
            setPage(1);
          }}
        />
        <Input.Search
          placeholder='Search by company'
          allowClear
          style={{ width: 260 }}
          onSearch={(value) => {
            setSearch(value.trim());
            setPage(1);
          }}
        />
      </Space>
      <Table
        rowKey='company_id'
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

      <Modal
        open={target !== null}
        title={target ? ACTION_LABEL[target.action] : ''}
        okText='Submit'
        confirmLoading={saving}
        okButtonProps={{
          disabled:
            reason.trim().length < 3 ||
            (target?.action === 'cancel_at_period_end' && !confirmed),
        }}
        onOk={() => void submit()}
        onCancel={() => setTarget(null)}
      >
        {target && (
          <Space direction='vertical' style={{ width: '100%' }}>
            <Text>
              {target.row.company_name} · {target.row.plan_code} ·{' '}
              {target.row.status}
            </Text>
            <Input.TextArea
              rows={3}
              placeholder='Reason (written to the audit trail)'
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            {target.action === 'cancel_at_period_end' && (
              <Checkbox
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              >
                I understand this changes the customer&apos;s Stripe subscription.
              </Checkbox>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
}
