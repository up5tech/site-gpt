import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
  RedoOutlined,
  ThunderboltOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Modal,
  Row,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
  message,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import type {
  DeliveryItem,
  IntegrationItem,
  IntegrationPayload,
  IntegrationType,
} from '../types/api';
import {
  createIntegration,
  deleteIntegration,
  getApiErrorMessage,
  getApiErrorStatus,
  getIntegrationDeliveries,
  getIntegrations,
  resendIntegrationDelivery,
  testIntegration,
  updateIntegration,
} from '../utils/api';

const { Title, Text, Paragraph } = Typography;

// Mirrors `services/integrations.py::EVENT_TYPES`.
const EVENT_OPTIONS = [
  { value: 'lead.captured', label: 'Lead captured (contact form)' },
  { value: 'feedback.received', label: 'Feedback received (👍/👎)' },
  { value: 'handoff.requested', label: 'Handoff requested' },
  { value: 'digest.generated', label: 'Digest generated' },
  { value: 'ping', label: 'Ping (test)' },
];

// Mirrors the providers' `secret_fields`: these inputs render the stored value
// as `***` and submitting the mask keeps the secret.
const TYPE_FIELDS: Record<
  IntegrationType,
  { key: string; label: string; placeholder?: string; secret?: boolean }[]
> = {
  webhook: [
    {
      key: 'url',
      label: 'Endpoint URL',
      placeholder: 'https://example.com/hooks/sitegpt',
    },
  ],
  slack: [
    {
      key: 'webhook_url',
      label: 'Slack incoming webhook URL',
      placeholder: 'https://hooks.slack.com/services/…',
      secret: true,
    },
  ],
  zendesk: [
    { key: 'subdomain', label: 'Zendesk subdomain', placeholder: 'acme' },
    { key: 'email', label: 'Agent email', placeholder: 'agent@example.com' },
    { key: 'api_token', label: 'API token', secret: true },
  ],
  crisp: [
    { key: 'website_id', label: 'Crisp website id' },
    { key: 'identifier', label: 'Crisp identifier', secret: true },
    { key: 'token', label: 'Crisp token', secret: true },
  ],
};

const TYPE_OPTIONS = (Object.keys(TYPE_FIELDS) as IntegrationType[]).map(
  (value) => ({ value, label: value }),
);

const SELECTED_SECRET = '***';

interface IntegrationFormValues {
  type?: IntegrationType;
  name?: string;
  events?: string[];
  config?: Record<string, string>;
}

export function Integrations() {
  const { isAuthenticated } = useAuth();
  const [form] = Form.useForm<IntegrationFormValues>();
  const [items, setItems] = useState<IntegrationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [editing, setEditing] = useState<IntegrationItem | null>(null);
  const [saving, setSaving] = useState(false);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [formType, setFormType] = useState<IntegrationType>('webhook');
  const [deliveries, setDeliveries] = useState<DeliveryItem[]>([]);
  const [deliveryCount, setDeliveryCount] = useState({ pending: 0, dead: 0 });
  const [deliveriesLoading, setDeliveriesLoading] = useState(false);
  const [resendingId, setResendingId] = useState<string | null>(null);

  const fetchItems = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getIntegrations();
      setItems(response.data || []);
    } catch (error) {
      console.error('Fetch integrations error', error);
      message.error('Failed to load integrations');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  const fetchDeliveries = useCallback(async () => {
    if (!isAuthenticated) return;
    setDeliveriesLoading(true);
    try {
      const response = await getIntegrationDeliveries();
      setDeliveries(response.data?.items || []);
      setDeliveryCount({
        pending: response.data?.pending || 0,
        dead: response.data?.dead || 0,
      });
    } catch (error) {
      console.error('Fetch deliveries error', error);
    } finally {
      setDeliveriesLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    fetchItems();
    fetchDeliveries();
  }, [fetchItems, fetchDeliveries]);

  const openCreate = () => {
    setEditing(null);
    setFormType('webhook');
    form.resetFields();
    form.setFieldsValue({
      type: 'webhook',
      events: ['lead.captured'],
      config: {},
    });
    setOpen(true);
  };

  const openEdit = (item: IntegrationItem) => {
    setEditing(item);
    setFormType(item.type);
    form.resetFields();
    form.setFieldsValue({
      type: item.type,
      name: item.name,
      events: item.events,
      config: item.config,
    });
    setOpen(true);
  };

  const submit = async () => {
    const values = await form.validateFields();
    // Drop empty fields so an untouched optional secret is not stored as "".
    const config: Record<string, string> = {};
    Object.entries(values.config || {}).forEach(([key, value]) => {
      if (typeof value === 'string' && value.trim()) config[key] = value;
    });

    const payload: IntegrationPayload = {
      name: values.name?.trim(),
      events: values.events || [],
      config,
    };
    setSaving(true);
    try {
      if (editing) {
        await updateIntegration(editing.id, payload);
        message.success('Integration updated');
      } else {
        await createIntegration({ ...payload, type: values.type });
        message.success('Integration created');
      }
      setOpen(false);
      await fetchItems();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to save the integration'));
    } finally {
      setSaving(false);
    }
  };

  const toggleEnabled = async (item: IntegrationItem, enabled: boolean) => {
    setBusyId(item.id);
    try {
      await updateIntegration(item.id, { enabled });
      setItems((prev) =>
        prev.map((row) => (row.id === item.id ? { ...row, enabled } : row)),
      );
      message.success(enabled ? 'Integration enabled' : 'Integration disabled');
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to update the integration'));
    } finally {
      setBusyId(null);
    }
  };

  const runTest = async (item: IntegrationItem) => {
    setBusyId(item.id);
    try {
      const response = await testIntegration(item.id);
      if (response.data.delivered) {
        message.success(
          `Ping delivered${response.data.status_code ? ` (HTTP ${response.data.status_code})` : ''}`,
        );
      } else {
        message.warning(`Ping failed: ${response.data.error || 'unknown error'}`);
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to test the integration'));
    } finally {
      setBusyId(null);
    }
  };

  const resend = async (delivery: DeliveryItem) => {
    setResendingId(delivery.id);
    try {
      const response = await resendIntegrationDelivery(delivery.id);
      if (response.data.delivered) {
        message.success('Event delivered');
      } else {
        message.warning(
          `Still failing: ${response.data.last_error || 'unknown error'} — queued for retry`,
        );
      }
      await fetchDeliveries();
    } catch (error) {
      // A 409 explains itself: either another admin is already resending this
      // delivery, or retention purged its payload. Everything else stays
      // generic so a server detail cannot leak into the UI.
      if (getApiErrorStatus(error) === 409) {
        message.warning(
          getApiErrorMessage(error, 'This delivery cannot be resent right now'),
        );
      } else {
        message.error('Failed to resend the event');
      }
    } finally {
      setResendingId(null);
    }
  };

  const remove = (item: IntegrationItem) => {
    Modal.confirm({
      title: `Delete "${item.name}"?`,
      content: 'Events will stop being delivered to it immediately.',
      okText: 'Delete',
      okButtonProps: { danger: true },
      onOk: async () => {
        try {
          await deleteIntegration(item.id);
          message.success('Integration deleted');
          await fetchItems();
        } catch (error) {
          message.error(getApiErrorMessage(error, 'Failed to delete'));
        }
      },
    });
  };

  const columns: ColumnsType<IntegrationItem> = [
    {
      title: 'Name',
      key: 'name',
      render: (_, item) => (
        <Space direction='vertical' size={0}>
          <Text strong>{item.name}</Text>
          <Tag>{item.type}</Tag>
        </Space>
      ),
    },
    {
      title: 'Events',
      dataIndex: 'events',
      key: 'events',
      render: (events: string[]) => (
        <Space size={[4, 4]} wrap>
          {events.length === 0 ? (
            <Text type='secondary'>None — no deliveries</Text>
          ) : (
            events.map((event) => <Tag key={event}>{event}</Tag>)
          )}
        </Space>
      ),
    },
    {
      title: 'Enabled',
      key: 'enabled',
      width: 110,
      render: (_, item) => (
        <Switch
          checked={item.enabled}
          loading={busyId === item.id}
          onChange={(checked) => toggleEnabled(item, checked)}
        />
      ),
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 260,
      render: (_, item) => (
        <Space>
          <Button
            size='small'
            icon={<ThunderboltOutlined />}
            loading={busyId === item.id}
            onClick={() => runTest(item)}
          >
            Test
          </Button>
          <Button size='small' icon={<EditOutlined />} onClick={() => openEdit(item)}>
            Edit
          </Button>
          <Button
            size='small'
            danger
            icon={<DeleteOutlined />}
            onClick={() => remove(item)}
          >
            Delete
          </Button>
        </Space>
      ),
    },
  ];

  const STATUS_COLOR: Record<DeliveryItem['status'], string> = {
    delivered: 'green',
    pending: 'gold',
    dead: 'red',
  };

  const deliveryColumns: ColumnsType<DeliveryItem> = [
    {
      title: 'When',
      key: 'created_at',
      width: 170,
      render: (_, item) => (
        <Text type='secondary' style={{ fontSize: 12 }}>
          {new Date(item.created_at).toLocaleString()}
        </Text>
      ),
    },
    {
      title: 'Event',
      key: 'event',
      render: (_, item) => (
        <Space direction='vertical' size={0}>
          <Text>{item.event_type}</Text>
          <Text type='secondary' style={{ fontSize: 11 }} code>
            {item.event_id.slice(0, 8)}
          </Text>
        </Space>
      ),
    },
    {
      title: 'Integration',
      key: 'integration',
      render: (_, item) => (
        <Space direction='vertical' size={0}>
          <Text>{item.integration_name}</Text>
          <Tag>{item.integration_type}</Tag>
        </Space>
      ),
    },
    {
      title: 'Status',
      key: 'status',
      width: 150,
      render: (_, item) => (
        <Space direction='vertical' size={0}>
          <Tag color={STATUS_COLOR[item.status]}>{item.status}</Tag>
          <Text type='secondary' style={{ fontSize: 11 }}>
            {item.attempts}/{item.max_attempts} attempts
          </Text>
          {item.status === 'pending' && item.next_attempt_at && (
            <Text type='secondary' style={{ fontSize: 11 }}>
              next: {new Date(item.next_attempt_at).toLocaleTimeString()}
            </Text>
          )}
        </Space>
      ),
    },
    {
      title: 'Last error',
      key: 'last_error',
      render: (_, item) =>
        item.last_error ? (
          <Text type='danger' style={{ fontSize: 12 }} ellipsis={{ tooltip: item.last_error }}>
            {item.last_error}
          </Text>
        ) : (
          <Text type='secondary'>—</Text>
        ),
    },
    {
      title: 'Action',
      key: 'action',
      width: 120,
      render: (_, item) => (
        <Button
          size='small'
          icon={<RedoOutlined />}
          loading={resendingId === item.id}
          disabled={!item.payload_available}
          title={
            item.payload_available
              ? undefined
              : 'The payload was purged by retention — the event cannot be resent'
          }
          onClick={() => resend(item)}
        >
          Resend
        </Button>
      ),
    },
  ];

  const fields = TYPE_FIELDS[formType] || [];

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title level={2} style={{ fontWeight: 700, marginBottom: 8 }}>
          Integrations
        </Title>
        <Text type='secondary'>
          Send events to a webhook, Slack, Zendesk or Crisp. Each integration
          subscribes to its own events.
        </Text>
      </div>

      <Card>
        <Row justify='end' style={{ marginBottom: 16 }}>
          <Col>
            <Button type='primary' icon={<PlusOutlined />} onClick={openCreate}>
              New integration
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={items}
          loading={loading}
          rowKey='id'
          pagination={false}
          locale={{ emptyText: 'No integrations yet' }}
        />
      </Card>

      <Modal
        open={open}
        title={editing ? 'Edit integration' : 'New integration'}
        onCancel={() => setOpen(false)}
        onOk={submit}
        okText={editing ? 'Save' : 'Create'}
        confirmLoading={saving}
        width={560}
        destroyOnClose
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Form.Item
            name='type'
            label='Type'
            rules={[{ required: true, message: 'Pick a type' }]}
          >
            <Select
              options={TYPE_OPTIONS}
              disabled={!!editing}
              onChange={(value: IntegrationType) => {
                setFormType(value);
                form.setFieldsValue({ config: {} });
              }}
            />
          </Form.Item>
          <Form.Item
            name='name'
            label='Name'
            rules={[{ required: true, message: 'Give it a name' }]}
          >
            <Input placeholder='Sales webhook' />
          </Form.Item>

          {fields.map((field) => (
            <Form.Item
              key={field.key}
              name={['config', field.key]}
              label={field.label}
              tooltip={
                field.secret
                  ? 'Stored server-side and never returned. Leaving *** keeps the saved value.'
                  : undefined
              }
            >
              <Input
                placeholder={
                  field.secret ? SELECTED_SECRET : field.placeholder || ''
                }
              />
            </Form.Item>
          ))}

          <Form.Item name='events' label='Events'>
            <Select mode='multiple' options={EVENT_OPTIONS} />
          </Form.Item>
        </Form>

        <Paragraph type='secondary' style={{ fontSize: 12, marginBottom: 0 }}>
          Webhooks are signed with <code>INTEGRATION_WEBHOOK_SECRET</code> in
          <code> X-SiteGPT-Signature</code> over
          <code> &lt;timestamp&gt;.&lt;body&gt;</code>.
        </Paragraph>
      </Modal>

      <Card
        style={{ marginTop: 16 }}
        title='Recent deliveries'
        extra={
          <Space size={8}>
            {deliveryCount.pending > 0 && (
              <Tag color='gold'>{deliveryCount.pending} pending</Tag>
            )}
            {deliveryCount.dead > 0 && <Tag color='red'>{deliveryCount.dead} dead</Tag>}
            <Button size='small' onClick={fetchDeliveries} loading={deliveriesLoading}>
              Refresh
            </Button>
          </Space>
        }
      >
        <Table
          columns={deliveryColumns}
          dataSource={deliveries}
          loading={deliveriesLoading}
          rowKey='id'
          size='small'
          pagination={false}
          locale={{ emptyText: 'No deliveries yet' }}
        />
      </Card>

      <Alert
        style={{ marginTop: 16 }}
        type='info'
        showIcon
        message='Delivery failures never break the request'
        description='Every event is stored before it is sent, so a lead, rating, handoff or digest is never dropped when an endpoint is down: failed sends retry with backoff and land here as dead when the attempts run out. Each event carries a stable event_id for the receiver to dedupe, and Resend retries it by hand.'
      />
    </>
  );
}
