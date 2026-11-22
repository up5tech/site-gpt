import { Alert, Button, Card, Col, Descriptions, Progress, Row, Skeleton, Space, Tag, Typography } from 'antd';
import { useCallback, useEffect, useState } from 'react';
import { useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type { BillingSummary, BillingUsage, PublicPlan } from '../types/api';
import {
  getApiErrorMessage,
  getBillingStatus,
  getBillingSummary,
  getBillingUsage,
  getPlans,
  openBillingPortal,
  startBillingCheckout,
} from '../utils/api';
import { useDocumentTitle } from '../utils/useDocumentTitle';

const { Title, Paragraph, Text } = Typography;

type LoadState = 'loading' | 'ready' | 'error' | 'off';

const STATUS_TAG: Record<string, { color: string; label: string }> = {
  active: { color: 'green', label: 'Active' },
  trialing: { color: 'blue', label: 'Trial' },
  past_due: { color: 'orange', label: 'Payment past due' },
  unpaid: { color: 'red', label: 'Unpaid' },
  canceled: { color: 'red', label: 'Canceled' },
  incomplete: { color: 'default', label: 'Incomplete' },
  paused: { color: 'default', label: 'Paused' },
};

function formatDate(value: string | null): string {
  if (!value) return '—';
  return new Date(value).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  });
}

/**
 * One usage row. `limit === null` means the plan does not enforce this
 * resource, so the raw count is shown instead of a made-up ceiling. Nothing on
 * this page derives a limit on the client: both numbers come from
 * `GET /api/billing/usage`.
 */
function UsageRow({ label, used, limit }: { label: string; used: number; limit: number | null }) {
  return (
    <div style={{ marginBottom: 16 }}>
      <Space
        style={{ width: '100%', justifyContent: 'space-between' }}
        align='baseline'
      >
        <Text strong>{label}</Text>
        <Text type='secondary'>
          {limit === null ? `${used} used` : `${used} of ${limit}`}
        </Text>
      </Space>
      {limit !== null && (
        <Progress
          percent={limit > 0 ? Math.min(100, Math.round((used / limit) * 100)) : 0}
          showInfo={false}
          status={used >= limit ? 'exception' : 'normal'}
        />
      )}
    </div>
  );
}

/**
 * The console billing page (V5 F3, task V5-32). It reports the mirrored Stripe
 * state and the company's usage; it never claims a plan is paid because a
 * browser returned from Checkout — only a verified webhook moves that state,
 * and until it arrives the row still reads `incomplete`.
 */
export function Billing() {
  useDocumentTitle('Billing — Site GPT');
  const { user } = useAuth();
  const [searchParams] = useSearchParams();
  const [state, setState] = useState<LoadState>('loading');
  const [summary, setSummary] = useState<BillingSummary | null>(null);
  const [usage, setUsage] = useState<BillingUsage | null>(null);
  const [plans, setPlans] = useState<PublicPlan[]>([]);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const isAdmin = user?.role === 'admin';
  const checkoutResult = searchParams.get('checkout');

  const load = useCallback(async () => {
    setState('loading');
    try {
      const status = await getBillingStatus();
      if (!status.data.enabled) {
        setState('off');
        return;
      }
      const [summaryResponse, usageResponse, plansResponse] = await Promise.all([
        getBillingSummary(),
        getBillingUsage(),
        getPlans(),
      ]);
      setSummary(summaryResponse.data);
      setUsage(usageResponse.data);
      setPlans(plansResponse.data.plans ?? []);
      setState('ready');
    } catch {
      setState('error');
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const startCheckout = async (planCode: string) => {
    setActionError(null);
    setBusy(true);
    try {
      const response = await startBillingCheckout(planCode);
      window.location.assign(response.data.url);
    } catch (error) {
      setActionError(
        getApiErrorMessage(error, 'We could not start checkout. Please try again.'),
      );
      setBusy(false);
    }
  };

  const openPortal = async () => {
    setActionError(null);
    setBusy(true);
    try {
      const response = await openBillingPortal();
      window.location.assign(response.data.url);
    } catch (error) {
      setActionError(
        getApiErrorMessage(error, 'We could not open the billing portal. Please try again.'),
      );
      setBusy(false);
    }
  };

  if (state === 'loading') {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  if (state === 'off') {
    return (
      <div>
        <Title level={2}>Billing</Title>
        <Alert
          type='info'
          showIcon
          message='Billing is not enabled for this deployment'
          description='This instance does not use paid subscriptions. Plans, checkout and the billing portal are unavailable, and your current limits are unchanged.'
        />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div>
        <Title level={2}>Billing</Title>
        <Alert
          type='error'
          showIcon
          message='Billing is temporarily unavailable'
          description='We could not load your subscription state. Please try again shortly.'
          action={<Button onClick={() => void load()}>Retry</Button>}
        />
      </div>
    );
  }

  const status = summary?.status ? STATUS_TAG[summary.status] : null;
  const payable = plans.filter((plan) => plan.self_serve_checkout);

  return (
    <div>
      <Title level={2}>Billing</Title>
      <Paragraph type='secondary'>
        Your subscription is confirmed by Stripe and mirrored here. Changes made in
        the Stripe billing portal appear after Stripe notifies us.
      </Paragraph>

      {checkoutResult === 'success' && (
        <Alert
          type='info'
          showIcon
          style={{ marginBottom: 16 }}
          message='Confirming your payment with Stripe'
          description='Checkout finished, but the plan becomes active only once Stripe’s signed confirmation reaches us — usually within a few seconds. Refresh this page to check again.'
        />
      )}
      {checkoutResult === 'cancelled' && (
        <Alert
          type='warning'
          showIcon
          style={{ marginBottom: 16 }}
          message='Checkout was cancelled'
          description='No payment was taken and your current plan is unchanged.'
        />
      )}
      {actionError && (
        <Alert
          type='error'
          showIcon
          style={{ marginBottom: 16 }}
          message={actionError}
          closable
          onClose={() => setActionError(null)}
        />
      )}

      <Row gutter={[16, 16]}>
        <Col xs={24} lg={14}>
          <Card className='premium-card' title='Plan'>
            {!summary?.has_billing_account ? (
              <Alert
                type='info'
                showIcon
                message='No subscription yet'
                description='This company has no billing account. Choose a plan below to start a Stripe-hosted checkout.'
              />
            ) : (
              <Descriptions column={1} size='small'>
                <Descriptions.Item label='Plan'>
                  {summary.plan_code ?? '—'}
                  {summary.interval ? ` (${summary.interval}ly)` : ''}
                </Descriptions.Item>
                <Descriptions.Item label='Status'>
                  {status ? <Tag color={status.color}>{status.label}</Tag> : '—'}
                </Descriptions.Item>
                <Descriptions.Item label='Renews / ends'>
                  {formatDate(summary.current_period_end)}
                  {summary.cancel_at_period_end && (
                    <Text type='secondary'> — cancels at period end</Text>
                  )}
                </Descriptions.Item>
              </Descriptions>
            )}
            {isAdmin ? (
              <Space wrap style={{ marginTop: 8 }}>
                <Button
                  onClick={() => void openPortal()}
                  disabled={!summary?.has_billing_account || busy}
                >
                  Manage in Stripe
                </Button>
              </Space>
            ) : (
              <Text type='secondary'>
                A company admin manages the subscription.
              </Text>
            )}
          </Card>

          {isAdmin && payable.length > 0 && (
            <Card
              className='premium-card'
              title={summary?.has_billing_account ? 'Change plan' : 'Choose a plan'}
              style={{ marginTop: 16 }}
            >
              <Space direction='vertical' style={{ width: '100%' }}>
                {payable.map((plan) => (
                  <Space
                    key={plan.code}
                    style={{ width: '100%', justifyContent: 'space-between' }}
                    wrap
                  >
                    <span>
                      <Text strong>{plan.name}</Text>
                      {plan.code === summary?.plan_code && (
                        <Tag style={{ marginLeft: 8 }}>Current</Tag>
                      )}
                    </span>
                    <Button
                      disabled={busy || plan.code === summary?.plan_code}
                      onClick={() => void startCheckout(plan.code)}
                    >
                      Select
                    </Button>
                  </Space>
                ))}
              </Space>
              <Paragraph type='secondary' style={{ marginTop: 12, marginBottom: 0 }}>
                Payment is entered on Stripe’s hosted page; card details never
                reach Site GPT.
              </Paragraph>
            </Card>
          )}
          {isAdmin && plans.length === 0 && (
            <Alert
              style={{ marginTop: 16 }}
              type='info'
              showIcon
              message='Plans are being finalised'
              description='No plan is published for sale yet, so there is nothing to buy. Your current limits stay in place.'
            />
          )}
        </Col>

        <Col xs={24} lg={10}>
          <Card className='premium-card' title='Usage'>
            {usage === null ? (
              <Text type='secondary'>Usage is unavailable.</Text>
            ) : (
              <>
                <UsageRow
                  label='Websites'
                  used={usage.websites.used}
                  limit={usage.websites.limit}
                />
                <UsageRow
                  label='Team members'
                  used={usage.seats.used}
                  limit={usage.seats.limit}
                />
                <Paragraph type='secondary' style={{ marginBottom: 0 }}>
                  {usage.enforced
                    ? 'Ceilings are the stricter of your plan and your own settings.'
                    : 'No plan ceiling is being enforced right now, so your existing limits apply.'}
                </Paragraph>
              </>
            )}
          </Card>
        </Col>
      </Row>
    </div>
  );
}
