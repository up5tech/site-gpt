import {
  DeleteOutlined,
  EditOutlined,
  PlusOutlined,
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
import type { IntegrationItem, IntegrationPayload, IntegrationType } from '../types/api';
import {
  createIntegration,
  deleteIntegration,
  getApiErrorMessage,
  getIntegrations,
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

  useEffect(() => {
    fetchItems();
  }, [fetchItems]);

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

      <Alert
        style={{ marginTop: 16 }}
        type='info'
        showIcon
        message='Delivery failures never break the request'
        description='If an endpoint is down, the lead, rating, handoff or digest is still saved and the failure is logged. Use Test to check an endpoint after configuring it.'
      />
    </>
  );
}
