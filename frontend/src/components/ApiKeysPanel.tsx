import { CopyOutlined, DeleteOutlined, PlusOutlined } from '@ant-design/icons';
import {
  Alert,
  Button,
  Form,
  Input,
  Modal,
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
import type { ApiKeyItem } from '../types/api';
import {
  createApiKey,
  getApiErrorMessage,
  getApiKeys,
  revokeApiKey,
} from '../utils/api';

const { Text, Paragraph } = Typography;

// Mirrors `services/api_keys.py::ALLOWED_SCOPES`.
const SCOPE_OPTIONS = [
  { value: 'read', label: 'read — settings, conversations, contacts, analytics' },
  { value: 'ingest:write', label: 'ingest:write — queue a re-crawl' },
  { value: 'settings:write', label: 'settings:write — update widget settings' },
  { value: 'chat:write', label: 'chat:write — ask a website a question' },
];

interface FormValues {
  name: string;
  scopes: string[];
}

/**
 * API keys for `/api/v1`. The raw key exists only in the create response, so it
 * is shown in a modal with a copy button and never fetched again.
 */
export function ApiKeysPanel() {
  const { isAuthenticated } = useAuth();
  const [form] = Form.useForm<FormValues>();
  const [items, setItems] = useState<ApiKeyItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [createdKey, setCreatedKey] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);

  const fetchKeys = useCallback(async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await getApiKeys();
      setItems(response.data || []);
    } catch (error) {
      console.error('Fetch API keys error', error);
      message.error('Failed to load API keys');
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated]);

  useEffect(() => {
    fetchKeys();
  }, [fetchKeys]);

  const submit = async () => {
    const values = await form.validateFields();
    setSaving(true);
    try {
      const response = await createApiKey({
        name: values.name.trim(),
        scopes: values.scopes,
      });
      setOpen(false);
      form.resetFields();
      setCreatedKey(response.data.key);
      await fetchKeys();
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Failed to create the API key'));
    } finally {
      setSaving(false);
    }
  };

  const revoke = (item: ApiKeyItem) => {
    Modal.confirm({
      title: `Revoke "${item.name}"?`,
      content:
        'Any integration using this key stops working immediately. The row stays for the audit trail.',
      okText: 'Revoke',
      okButtonProps: { danger: true },
      onOk: async () => {
        setBusyId(item.id);
        try {
          await revokeApiKey(item.id);
          message.success('API key revoked');
          await fetchKeys();
        } catch (error) {
          message.error(getApiErrorMessage(error, 'Failed to revoke the key'));
        } finally {
          setBusyId(null);
        }
      },
    });
  };

  const columns: ColumnsType<ApiKeyItem> = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text: string) => <Text strong>{text}</Text>,
    },
    {
      title: 'Key',
      dataIndex: 'key_prefix',
      key: 'key_prefix',
      render: (text: string) => <Text code>{text}…</Text>,
    },
    {
      title: 'Scopes',
      dataIndex: 'scopes',
      key: 'scopes',
      render: (scopes: string[]) => (
        <Space size={[4, 4]} wrap>
          {scopes.map((scope) => (
            <Tag key={scope}>{scope}</Tag>
          ))}
        </Space>
      ),
    },
    {
      title: 'Created',
      dataIndex: 'created_at',
      key: 'created_at',
      render: (text: string) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text ? new Date(text).toLocaleString() : '—'}
        </Text>
      ),
    },
    {
      title: 'Last used',
      dataIndex: 'last_used_at',
      key: 'last_used_at',
      render: (text: string | null) => (
        <Text type='secondary' style={{ fontSize: 13 }}>
          {text ? new Date(text).toLocaleString() : 'Never'}
        </Text>
      ),
    },
    {
      title: 'Status',
      key: 'status',
      render: (_, item) =>
        item.revoked_at ? (
          <Tag color='red'>revoked</Tag>
        ) : (
          <Tag color='green'>active</Tag>
        ),
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, item) => (
        <Button
          size='small'
          danger
          icon={<DeleteOutlined />}
          disabled={!!item.revoked_at}
          loading={busyId === item.id}
          onClick={() => revoke(item)}
        >
          Revoke
        </Button>
      ),
    },
  ];

  return (
    <>
      <Paragraph type='secondary'>
        Keys authenticate the versioned <Text code>/api/v1</Text> API for
        server-to-server callers. Only a hash is stored — the key itself is shown
        once, when it is created.
      </Paragraph>

      <Space style={{ marginBottom: 16 }}>
        <Button
          type='primary'
          icon={<PlusOutlined />}
          onClick={() => {
            form.resetFields();
            form.setFieldsValue({ scopes: ['read'] });
            setOpen(true);
          }}
        >
          Create key
        </Button>
      </Space>

      <Table
        columns={columns}
        dataSource={items}
        loading={loading}
        rowKey='id'
        pagination={false}
        locale={{ emptyText: 'No API keys yet' }}
      />

      <Modal
        open={open}
        title='Create API key'
        onCancel={() => setOpen(false)}
        onOk={submit}
        okText='Create'
        confirmLoading={saving}
        destroyOnClose
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Form.Item
            name='name'
            label='Name'
            tooltip='For your own reference, e.g. "Zapier production".'
            rules={[{ required: true, message: 'Give the key a name' }]}
          >
            <Input placeholder='Zapier production' />
          </Form.Item>
          <Form.Item
            name='scopes'
            label='Scopes'
            rules={[{ required: true, message: 'Pick at least one scope' }]}
          >
            <Select mode='multiple' options={SCOPE_OPTIONS} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={createdKey !== null}
        title='Copy your API key now'
        onCancel={() => setCreatedKey(null)}
        footer={
          <Button type='primary' onClick={() => setCreatedKey(null)}>
            Done
          </Button>
        }
      >
        <Alert
          type='warning'
          showIcon
          message='This is the only time the key is shown'
          description='Only a hash is stored, so it cannot be recovered. Paste it into your integration now.'
          style={{ marginBottom: 16 }}
        />
        <Space.Compact style={{ width: '100%' }}>
          <Input value={createdKey ?? ''} readOnly />
          <Button
            icon={<CopyOutlined />}
            onClick={() => {
              if (createdKey) {
                navigator.clipboard.writeText(createdKey);
                message.success('Copied to clipboard');
              }
            }}
          >
            Copy
          </Button>
        </Space.Compact>
      </Modal>
    </>
  );
}
