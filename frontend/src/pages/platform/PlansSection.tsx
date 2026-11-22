import {
  Alert,
  Button,
  Checkbox,
  Form,
  Input,
  InputNumber,
  message,
  Modal,
  Select,
  Space,
  Switch,
  Table,
  Tag,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import type { PlatformPlan } from '../../types/api';
import {
  addPlatformPlanPrice,
  archivePlatformPlan,
  createPlatformPlan,
  getPlatformPlans,
  publishPlatformPlan,
  updatePlatformPlan,
} from '../../utils/api';
import {
  formatMoney,
  limitsText,
  parseLimits,
  platformErrorMessage,
} from './shared';

const { Title, Paragraph, Text } = Typography;

type Lifecycle = { plan: PlatformPlan; action: 'publish' | 'archive' };

const STATUS_COLOR: Record<string, string> = {
  draft: 'default',
  published: 'green',
  archived: 'red',
};

function featureText(features: string[]): string {
  return features.join('\n');
}

export function PlansSection() {
  const [plans, setPlans] = useState<PlatformPlan[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const [editing, setEditing] = useState<PlatformPlan | null>(null);
  const [pricing, setPricing] = useState<PlatformPlan | null>(null);
  const [lifecycle, setLifecycle] = useState<Lifecycle | null>(null);
  const [lifecycleReason, setLifecycleReason] = useState('');
  const [lifecycleConfirmed, setLifecycleConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [createForm] = Form.useForm();
  const [editForm] = Form.useForm();
  const [priceForm] = Form.useForm();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await getPlatformPlans();
      setPlans(response.data.plans);
    } catch (reason) {
      setError(platformErrorMessage(reason, 'Could not load the catalog.'));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const submit = async (work: () => Promise<unknown>, success: string) => {
    setBusy(true);
    try {
      await work();
      message.success(success);
      setCreateOpen(false);
      setEditing(null);
      setPricing(null);
      setLifecycle(null);
      void load();
    } catch (reason) {
      message.error(platformErrorMessage(reason, 'The change was refused.'));
    } finally {
      setBusy(false);
    }
  };

  const create = async (values: Record<string, unknown>) => {
    try {
      const limits = parseLimits(String(values.limits ?? ''));
      await submit(
        () =>
          createPlatformPlan({
            code: values.code,
            name: values.name,
            description: values.description ?? '',
            features: String(values.features ?? '')
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean),
            limits,
            self_serve_checkout: Boolean(values.self_serve_checkout),
            interval: values.interval,
            currency: values.currency,
            price_minor: Math.round(Number(values.price) * 100),
            stripe_price_id: values.stripe_price_id || null,
            reason: values.reason,
          }),
        'Draft plan created.',
      );
      createForm.resetFields();
    } catch (reason) {
      message.error((reason as Error).message);
    }
  };

  const edit = async (values: Record<string, unknown>) => {
    if (!editing) return;
    try {
      const limits = parseLimits(String(values.limits ?? ''));
      await submit(
        () =>
          updatePlatformPlan(editing.code, {
            name: values.name,
            description: values.description ?? '',
            features: String(values.features ?? '')
              .split('\n')
              .map((line) => line.trim())
              .filter(Boolean),
            limits,
            self_serve_checkout: Boolean(values.self_serve_checkout),
            reason: values.reason,
            confirm: Boolean(values.confirm),
          }),
        'Plan updated.',
      );
    } catch (reason) {
      message.error((reason as Error).message);
    }
  };

  const changePrice = async (values: Record<string, unknown>) => {
    if (!pricing) return;
    await submit(
      () =>
        addPlatformPlanPrice(pricing.code, {
          interval: values.interval,
          currency: values.currency,
          price_minor: Math.round(Number(values.price) * 100),
          stripe_price_id: values.stripe_price_id || null,
          reason: values.reason,
          confirm: Boolean(values.confirm),
        }),
      'New price record created; the previous one stays as history.',
    );
  };

  const runLifecycle = async () => {
    if (!lifecycle) return;
    await submit(
      () =>
        lifecycle.action === 'publish'
          ? publishPlatformPlan(lifecycle.plan.code, lifecycleReason)
          : archivePlatformPlan(lifecycle.plan.code, lifecycleReason),
      lifecycle.action === 'publish' ? 'Plan published.' : 'Plan archived.',
    );
  };

  const openEdit = (plan: PlatformPlan) => {
    setEditing(plan);
    editForm.setFieldsValue({
      name: plan.name,
      description: plan.description,
      features: featureText(plan.features),
      limits: limitsText(plan.limits),
      self_serve_checkout: plan.self_serve_checkout,
      reason: '',
      confirm: false,
    });
  };

  const openPrice = (plan: PlatformPlan) => {
    const active = plan.prices.find((price) => price.active);
    setPricing(plan);
    priceForm.setFieldsValue({
      interval: active?.interval ?? 'month',
      currency: active?.currency ?? 'usd',
      price: (active?.price_minor ?? 0) / 100,
      stripe_price_id: '',
      reason: '',
      confirm: false,
    });
  };

  const openLifecycle = (plan: PlatformPlan, action: 'publish' | 'archive') => {
    setLifecycle({ plan, action });
    setLifecycleReason('');
    setLifecycleConfirmed(false);
  };

  const columns: ColumnsType<PlatformPlan> = [
    {
      title: 'Code',
      dataIndex: 'code',
      render: (code: string) => <Text code>{code}</Text>,
    },
    { title: 'Name', dataIndex: 'name' },
    {
      title: 'Status',
      dataIndex: 'status',
      render: (status: string) => <Tag color={STATUS_COLOR[status]}>{status}</Tag>,
    },
    {
      title: 'Active price',
      render: (_, plan) => {
        const active = plan.prices.find((price) => price.active);
        if (!active) return <Text type='danger'>none</Text>;
        return (
          <div>
            {formatMoney(active.price_minor, active.currency)}{' '}
            <Text type='secondary'>/{active.interval}</Text>
            <div>
              <Text type='secondary' style={{ fontSize: 12 }}>
                {active.stripe_price_id ?? 'no Stripe mapping'}
              </Text>
            </div>
          </div>
        );
      },
    },
    {
      title: 'Prices',
      render: (_, plan) => `${plan.prices.length} record(s)`,
    },
    {
      title: 'Self-serve',
      dataIndex: 'self_serve_checkout',
      render: (value: boolean) => (value ? 'Yes' : 'Contact sales'),
    },
    {
      title: 'Actions',
      render: (_, plan) => (
        <Space wrap size={4}>
          {plan.status === 'draft' && (
            <Button size='small' type='primary' onClick={() => openLifecycle(plan, 'publish')}>
              Publish
            </Button>
          )}
          {plan.status !== 'archived' && (
            <>
              <Button size='small' onClick={() => openEdit(plan)}>
                Edit
              </Button>
              <Button size='small' onClick={() => openPrice(plan)}>
                New price
              </Button>
              <Button size='small' danger onClick={() => openLifecycle(plan, 'archive')}>
                Archive
              </Button>
            </>
          )}
        </Space>
      ),
    },
  ];

  return (
    <div>
      <Title level={3}>Plans &amp; pricing</Title>
      <Paragraph type='secondary'>
        Drafts are invisible publicly. Publishing requires a usable active price
        and, while billing is enabled, a Stripe Price mapping. Price changes add
        an immutable record; existing subscribers keep the Price they bought.
      </Paragraph>
      {error && <Alert type='error' showIcon message={error} style={{ marginBottom: 16 }} />}
      <Button type='primary' onClick={() => setCreateOpen(true)} style={{ marginBottom: 16 }}>
        New plan
      </Button>
      <Table
        rowKey='id'
        size='small'
        loading={loading}
        columns={columns}
        dataSource={plans}
        pagination={false}
      />

      <Modal
        open={createOpen}
        title='New draft plan'
        okText='Create draft'
        confirmLoading={busy}
        onOk={() => createForm.submit()}
        onCancel={() => setCreateOpen(false)}
        width={640}
      >
        <Form form={createForm} layout='vertical' onFinish={create} initialValues={{
          interval: 'month',
          currency: 'usd',
          self_serve_checkout: true,
          features: '',
          limits: '',
        }}>
          <Space style={{ width: '100%' }} size='middle' wrap>
            <Form.Item name='code' label='Code' rules={[{ required: true }]} style={{ width: 220 }}>
              <Input placeholder='starter' />
            </Form.Item>
            <Form.Item name='name' label='Name' rules={[{ required: true }]} style={{ width: 260 }}>
              <Input />
            </Form.Item>
          </Space>
          <Form.Item name='description' label='Description'>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Space size='middle' wrap>
            <Form.Item name='interval' label='Interval' rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={[{ value: 'month', label: 'month' }, { value: 'year', label: 'year' }]} />
            </Form.Item>
            <Form.Item name='currency' label='Currency' rules={[{ required: true }]}>
              <Input style={{ width: 100 }} maxLength={3} />
            </Form.Item>
            <Form.Item name='price' label='Price (major unit)' rules={[{ required: true }]}>
              <InputNumber min={0} step={0.01} style={{ width: 160 }} />
            </Form.Item>
            <Form.Item name='self_serve_checkout' label='Self-serve' valuePropName='checked'>
              <Switch />
            </Form.Item>
          </Space>
          <Form.Item name='stripe_price_id' label='Stripe Price ID (private, optional)'>
            <Input placeholder='price_…' />
          </Form.Item>
          <Form.Item
            name='features'
            label='Feature lines (one per line)'
            rules={[{ required: true, message: 'At least one feature line' }]}
          >
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item
            name='limits'
            label='Limits (key=value per line)'
            rules={[{ required: true, message: 'At least one limit' }]}
          >
            <Input.TextArea rows={3} placeholder={'websites=1\nseats=3'} />
          </Form.Item>
          <Form.Item name='reason' label='Reason (audited)' rules={[{ required: true, min: 3 }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={editing !== null}
        title={`Edit ${editing?.code ?? ''}`}
        okText='Save'
        confirmLoading={busy}
        onOk={() => editForm.submit()}
        onCancel={() => setEditing(null)}
        width={640}
      >
        <Form form={editForm} layout='vertical' onFinish={edit}>
          <Form.Item name='name' label='Name' rules={[{ required: true }]}>
            <Input />
          </Form.Item>
          <Form.Item name='description' label='Description'>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name='features' label='Feature lines (one per line)'>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name='limits' label='Limits (key=value per line)'>
            <Input.TextArea rows={3} />
          </Form.Item>
          <Form.Item name='self_serve_checkout' label='Self-serve' valuePropName='checked'>
            <Switch />
          </Form.Item>
          <Form.Item name='reason' label='Reason (audited)' rules={[{ required: true, min: 3 }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name='confirm' valuePropName='checked'>
            <Checkbox>I understand this changes what existing and new customers see.</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={pricing !== null}
        title={`New price for ${pricing?.code ?? ''}`}
        okText='Create price record'
        confirmLoading={busy}
        onOk={() => priceForm.submit()}
        onCancel={() => setPricing(null)}
      >
        <Alert
          type='info'
          showIcon
          style={{ marginBottom: 16 }}
          message='Prices are immutable'
          description='The current price is archived, not edited. Existing Stripe subscribers keep the Price they bought; only new checkouts see the new one.'
        />
        <Form form={priceForm} layout='vertical' onFinish={changePrice}>
          <Space size='middle' wrap>
            <Form.Item name='interval' label='Interval' rules={[{ required: true }]}>
              <Select style={{ width: 120 }} options={[{ value: 'month', label: 'month' }, { value: 'year', label: 'year' }]} />
            </Form.Item>
            <Form.Item name='currency' label='Currency' rules={[{ required: true }]}>
              <Input style={{ width: 100 }} maxLength={3} />
            </Form.Item>
            <Form.Item name='price' label='Price (major unit)' rules={[{ required: true }]}>
              <InputNumber min={0} step={0.01} style={{ width: 160 }} />
            </Form.Item>
          </Space>
          <Form.Item name='stripe_price_id' label='Stripe Price ID (private, optional)'>
            <Input placeholder='price_…' />
          </Form.Item>
          <Form.Item name='reason' label='Reason (audited)' rules={[{ required: true, min: 3 }]}>
            <Input.TextArea rows={2} />
          </Form.Item>
          <Form.Item name='confirm' valuePropName='checked'>
            <Checkbox>I understand a new Price ends the current one for new checkouts.</Checkbox>
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        open={lifecycle !== null}
        title={lifecycle?.action === 'publish' ? 'Publish plan' : 'Archive plan'}
        okText={lifecycle?.action === 'publish' ? 'Publish' : 'Archive'}
        okButtonProps={{
          danger: lifecycle?.action === 'archive',
          disabled: lifecycleReason.trim().length < 3 || !lifecycleConfirmed,
        }}
        confirmLoading={busy}
        onOk={() => void runLifecycle()}
        onCancel={() => setLifecycle(null)}
      >
        {lifecycle && (
          <Space direction='vertical' style={{ width: '100%' }}>
            <Text>
              {lifecycle.plan.code} · {lifecycle.plan.name}
            </Text>
            <Input.TextArea
              rows={3}
              placeholder='Reason (written to the audit trail)'
              value={lifecycleReason}
              onChange={(event) => setLifecycleReason(event.target.value)}
            />
            <Checkbox
              checked={lifecycleConfirmed}
              onChange={(event) => setLifecycleConfirmed(event.target.checked)}
            >
              {lifecycle.action === 'publish'
                ? 'I understand this makes the plan public and buyable.'
                : 'I understand this removes the plan from sale (existing subscribers are unaffected).'}
            </Checkbox>
          </Space>
        )}
      </Modal>
    </div>
  );
}
