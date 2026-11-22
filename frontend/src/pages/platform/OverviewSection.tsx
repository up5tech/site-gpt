import { Alert, Card, Col, Row, Skeleton, Space, Statistic, Tag, Typography } from 'antd';
import { useEffect, useState } from 'react';
import type { PlatformAuditEvent, PlatformOverview } from '../../types/api';
import { getPlatformAudit, getPlatformOverview } from '../../utils/api';
import { formatDateTime, platformErrorMessage } from './shared';

const { Title, Paragraph, Text } = Typography;

export function OverviewSection() {
  const [overview, setOverview] = useState<PlatformOverview | null>(null);
  const [recent, setRecent] = useState<PlatformAuditEvent[]>([]);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    Promise.all([getPlatformOverview(), getPlatformAudit(5)])
      .then(([overviewResponse, auditResponse]) => {
        if (cancelled) return;
        setOverview(overviewResponse.data);
        setRecent(auditResponse.data.events);
      })
      .catch((reason: unknown) => {
        if (!cancelled) {
          setError(platformErrorMessage(reason, 'Could not load the overview.'));
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return <Alert type='error' showIcon message={error} />;
  }
  if (!overview) {
    return <Skeleton active paragraph={{ rows: 6 }} />;
  }

  return (
    <div>
      <Title level={3}>Overview</Title>
      <Paragraph type='secondary'>
        Mirrored state only. Subscription status comes from verified Stripe
        webhooks; nothing here can mark a subscription paid.
      </Paragraph>
      <Row gutter={[16, 16]}>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title='Companies' value={overview.companies} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title='Websites' value={overview.websites} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title='Active users' value={overview.active_users} />
          </Card>
        </Col>
        <Col xs={12} md={6}>
          <Card>
            <Statistic title='Published plans' value={overview.published_plans} />
          </Card>
        </Col>
      </Row>
      <Card style={{ marginTop: 16 }} title='Subscriptions by status'>
        {Object.keys(overview.subscriptions).length === 0 ? (
          <Text type='secondary'>No subscription rows yet.</Text>
        ) : (
          <Space wrap>
            {Object.entries(overview.subscriptions).map(([status, count]) => (
              <Tag key={status} color={status === 'active' ? 'green' : 'default'}>
                {status}: {count}
              </Tag>
            ))}
          </Space>
        )}
      </Card>
      <Card style={{ marginTop: 16 }} title='Recent operator activity'>
        {recent.length === 0 ? (
          <Text type='secondary'>No audit rows yet.</Text>
        ) : (
          <Space direction='vertical' style={{ width: '100%' }}>
            {recent.map((event) => (
              <div key={event.id}>
                <Text strong>{event.action}</Text>{' '}
                <Text type='secondary'>
                  {event.target_type}
                  {event.target_id ? ` · ${event.target_id}` : ''} ·{' '}
                  {formatDateTime(event.created_at)}
                </Text>
              </div>
            ))}
          </Space>
        )}
      </Card>
    </div>
  );
}
