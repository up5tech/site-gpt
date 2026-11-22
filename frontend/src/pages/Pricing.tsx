import { Alert, Button, Card, Skeleton, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import type { PublicPlan } from '../types/api';
import { getPlans } from '../utils/api';
import { useDocumentTitle } from '../utils/useDocumentTitle';

const { Title, Paragraph, Text } = Typography;

type LoadState = 'loading' | 'ready' | 'error';

/**
 * Price display is derived from the server's integer minor units. Nothing on
 * this page invents, rounds or hardcodes an amount: `price_minor`, the currency
 * and the cadence all come from `GET /api/plans`.
 */
export function formatPlanPrice(plan: PublicPlan): string {
  const amount = plan.price_minor / 100;
  const fractionDigits = plan.price_minor % 100 === 0 ? 0 : 2;
  try {
    return new Intl.NumberFormat(undefined, {
      style: 'currency',
      currency: plan.currency,
      minimumFractionDigits: fractionDigits,
      maximumFractionDigits: fractionDigits,
    }).format(amount);
  } catch {
    // An unknown currency code is a catalog misconfiguration; show the number
    // with the code instead of silently labelling it with the wrong symbol.
    return `${amount.toFixed(fractionDigits)} ${plan.currency}`;
  }
}

const PERIOD_LABEL: Record<string, string> = {
  month: 'per month',
  year: 'per year',
};

export function Pricing() {
  useDocumentTitle('Pricing — Site GPT');
  const [state, setState] = useState<LoadState>('loading');
  const [plans, setPlans] = useState<PublicPlan[]>([]);

  useEffect(() => {
    let cancelled = false;
    getPlans()
      .then((response) => {
        if (cancelled) return;
        setPlans(response.data.plans ?? []);
        setState('ready');
      })
      .catch(() => {
        if (cancelled) return;
        setState('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <section className='marketing-section' aria-labelledby='pricing-title'>
      <div className='marketing-section-heading'>
        <Title level={1} id='pricing-title'>
          Pricing
        </Title>
        <Paragraph>
          Every plan is described from the server's catalog, so what you read
          here is exactly what the product enforces.
        </Paragraph>
      </div>

      {state === 'loading' && <Skeleton active paragraph={{ rows: 5 }} />}

      {state === 'error' && (
        <Alert
          type='error'
          showIcon
          message='Pricing is temporarily unavailable'
          description='We could not load the plan catalog. Please try again shortly, or create an account to start with the standard plan.'
        />
      )}

      {state === 'ready' && plans.length === 0 && (
        <Alert
          type='info'
          showIcon
          message='Plans are being finalised'
          description='The plan catalog has no published plan yet, so there is no price to show. You can create an account now; billing stays disabled until an approved plan is available.'
        />
      )}

      {state === 'ready' && plans.length > 0 && (
        <div className='marketing-plans'>
          {plans.map((plan) => (
            <Card key={plan.code} className='marketing-plan' bordered>
              <Title level={2}>{plan.name}</Title>
              <Paragraph>{plan.description}</Paragraph>
              <div>
                <span className='marketing-price'>
                  {formatPlanPrice(plan)}
                </span>
                <span className='marketing-price-period'>
                  {' '}
                  {PERIOD_LABEL[plan.interval] ?? plan.interval}
                </span>
              </div>
              {plan.features.length > 0 && (
                <ul>
                  {plan.features.map((feature) => (
                    <li key={feature}>• {feature}</li>
                  ))}
                </ul>
              )}
              {plan.limits.length > 0 && (
                <ul className='marketing-limits'>
                  {plan.limits.map((limit) => (
                    <li key={limit.key}>
                      {limit.key.replace(/_/g, ' ')}: {limit.value}
                    </li>
                  ))}
                </ul>
              )}
              <div className='marketing-plan-cta'>
                {plan.self_serve_checkout ? (
                  <Link to={`/register?plan=${encodeURIComponent(plan.code)}`}>
                    <Button type='primary' block>
                      Choose {plan.name}
                    </Button>
                  </Link>
                ) : (
                  <Text type='secondary'>Available on request.</Text>
                )}
              </div>
            </Card>
          ))}
        </div>
      )}

      {state !== 'error' && (
        <div style={{ marginTop: 32 }}>
          <Text type='secondary'>
            Already have an account? <Link to='/login'>Sign in</Link>.
          </Text>
        </div>
      )}
    </section>
  );
}
