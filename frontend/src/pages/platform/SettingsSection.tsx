import {
  Alert,
  Button,
  Checkbox,
  Input,
  message,
  Modal,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import type { PlatformSetting } from '../../types/api';
import {
  getPlatformSettings,
  previewPlatformSetting,
  updatePlatformSetting,
} from '../../utils/api';
import { formatDateTime, platformErrorMessage } from './shared';

const { Title, Paragraph, Text } = Typography;

export function SettingsSection() {
  const [settings, setSettings] = useState<PlatformSetting[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editing, setEditing] = useState<PlatformSetting | null>(null);
  const [value, setValue] = useState('');
  const [reason, setReason] = useState('');
  const [confirmed, setConfirmed] = useState(false);
  const [preview, setPreview] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformSettings();
      setSettings(response.data.settings);
    } catch (reasonValue) {
      setError(platformErrorMessage(reasonValue, 'Could not load settings.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const open = (setting: PlatformSetting) => {
    setEditing(setting);
    setValue(setting.value);
    setReason('');
    setConfirmed(false);
    setPreview(null);
  };

  const runPreview = async () => {
    if (!editing) return;
    try {
      const response = await previewPlatformSetting(editing.key, value);
      setPreview(
        response.data.changed
          ? `“${response.data.current || '(empty)'}” → “${response.data.next || '(empty)'}”`
          : 'No change.',
      );
    } catch (errorValue) {
      message.error(
        platformErrorMessage(errorValue, 'That value cannot be saved.'),
      );
    }
  };

  const save = async () => {
    if (!editing) return;
    setBusy(true);
    try {
      await updatePlatformSetting(editing.key, {
        value,
        reason,
        confirm: confirmed,
      });
      message.success('Setting updated and audited.');
      setEditing(null);
      void load();
    } catch (errorValue) {
      message.error(
        platformErrorMessage(errorValue, 'The setting was refused.'),
      );
    } finally {
      setBusy(false);
    }
  };

  const columns: ColumnsType<PlatformSetting> = [
    {
      title: 'Setting',
      dataIndex: 'key',
      render: (key: string, row) => (
        <div>
          <Text strong>{row.label}</Text>
          <div>
            <Text code>{key}</Text>
          </div>
        </div>
      ),
    },
    { title: 'Description', dataIndex: 'description' },
    {
      title: 'Value',
      dataIndex: 'value',
      render: (current: string) =>
        current ? (
          <Text>{current}</Text>
        ) : (
          <Text type='secondary'>(empty)</Text>
        ),
    },
    {
      title: 'Source',
      dataIndex: 'is_override',
      render: (override: boolean) =>
        override ? <Tag color='blue'>override</Tag> : <Tag>default</Tag>,
    },
    {
      title: 'Updated',
      dataIndex: 'updated_at',
      render: (updated: string | null) => formatDateTime(updated),
    },
    {
      title: '',
      render: (_, row) => (
        <Button size='small' onClick={() => open(row)}>
          Edit
        </Button>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Settings</Title>
      <Paragraph type='secondary'>
        Only typed, non-secret display values are writable here. Deployment
        environment stays authoritative for auth, networking, secrets, billing
        enforcement and destructive retention.
      </Paragraph>
      {error && <Alert type='error' showIcon message={error} style={{ marginBottom: 16 }} />}
      <Table
        rowKey='key'
        size='small'
        loading={loading}
        columns={columns}
        dataSource={settings}
        pagination={false}
      />

      <Modal
        open={editing !== null}
        title={editing ? editing.label : ''}
        okText='Save'
        confirmLoading={busy}
        okButtonProps={{
          disabled:
            reason.trim().length < 3 ||
            (editing?.high_impact === true && !confirmed),
        }}
        onOk={() => void save()}
        onCancel={() => setEditing(null)}
      >
        {editing && (
          <Space direction='vertical' style={{ width: '100%' }}>
            <Text type='secondary'>{editing.description}</Text>
            <Input.TextArea
              rows={3}
              maxLength={editing.max_length || undefined}
              showCount={Boolean(editing.max_length)}
              value={value}
              onChange={(event) => setValue(event.target.value)}
            />
            <Button onClick={() => void runPreview()}>Preview</Button>
            {preview && <Alert type='info' showIcon message={preview} />}
            <Input.TextArea
              rows={2}
              placeholder='Reason (written to the audit trail)'
              value={reason}
              onChange={(event) => setReason(event.target.value)}
            />
            {editing.high_impact && (
              <Checkbox
                checked={confirmed}
                onChange={(event) => setConfirmed(event.target.checked)}
              >
                I understand this is a high-impact change.
              </Checkbox>
            )}
          </Space>
        )}
      </Modal>
    </div>
  );
}
