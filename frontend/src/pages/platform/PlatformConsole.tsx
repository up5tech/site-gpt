import { Alert, Button, Layout, Menu, Result, Spin, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../../context/AuthContext';
import { getPlatformSession } from '../../utils/api';
import { useDocumentTitle } from '../../utils/useDocumentTitle';
import { AuditSection } from './AuditSection';
import { CompaniesSection } from './CompaniesSection';
import { OverviewSection } from './OverviewSection';
import { PlansSection } from './PlansSection';
import { SettingsSection } from './SettingsSection';
import { SubscriptionsSection } from './SubscriptionsSection';

const { Header, Content } = Layout;
const { Text } = Typography;

const SECTIONS = [
  { key: 'overview', label: 'Overview' },
  { key: 'companies', label: 'Companies' },
  { key: 'plans', label: 'Plans & pricing' },
  { key: 'subscriptions', label: 'Subscriptions' },
  { key: 'settings', label: 'Settings' },
  { key: 'audit', label: 'Audit' },
];

type Gate = 'loading' | 'ready' | 'forbidden' | 'missing' | 'error';

/**
 * The platform-owner console (V5 F5). Deliberately its own shell: it is not
 * `/app`, it does not inherit tenant navigation, and an ordinary company admin
 * who signs in is refused by `GET /api/platform/session`. The whole surface is
 * a 404 while `PLATFORM_CONSOLE_ENABLED` is false.
 */
export function PlatformConsole() {
  useDocumentTitle('Platform — Site GPT');
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [gate, setGate] = useState<Gate>('loading');
  const [active, setActive] = useState('overview');

  useEffect(() => {
    let cancelled = false;
    getPlatformSession()
      .then(() => {
        if (!cancelled) setGate('ready');
      })
      .catch((error: unknown) => {
        if (cancelled) return;
        const status = (
          error as { response?: { status?: number } }
        )?.response?.status;
        if (status === 404) setGate('missing');
        else if (status === 401 || status === 403) setGate('forbidden');
        else setGate('error');
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (gate === 'loading') {
    return (
      <div style={{ padding: 64, textAlign: 'center' }}>
        <Spin size='large' />
      </div>
    );
  }

  if (gate === 'forbidden') {
    return (
      <Result
        status='403'
        title='Operator access required'
        subTitle='This console is limited to separately provisioned platform owners. A company admin account is not enough.'
        extra={
          <Link to='/app'>
            <Button type='primary'>Back to the app</Button>
          </Link>
        }
      />
    );
  }

  if (gate === 'missing') {
    return (
      <Result
        status='404'
        title='Platform console is not enabled'
        subTitle='This deployment has not opened the operator control plane.'
        extra={
          <Link to='/'>
            <Button type='primary'>Back to the site</Button>
          </Link>
        }
      />
    );
  }

  if (gate === 'error') {
    return (
      <Result
        status='error'
        title='Platform console unavailable'
        subTitle='The session could not be checked. Try again shortly.'
        extra={
          <Link to='/app'>
            <Button type='primary'>Back to the app</Button>
          </Link>
        }
      />
    );
  }

  return (
    <Layout style={{ minHeight: '100vh', background: '#f6f6f7' }}>
      <Header
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          flexWrap: 'wrap',
          gap: 16,
          background: '#111',
          padding: '0 24px',
        }}
      >
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 16 }}>
          <span style={{ color: '#fff', fontSize: 20, fontWeight: 700 }}>
            Site GPT · Platform
          </span>
          <Text style={{ color: '#bbb', fontSize: 13 }}>
            {user?.email ?? ''}
          </Text>
        </div>
        <div style={{ display: 'flex', gap: 12 }}>
          <Link to='/app' style={{ color: '#ddd' }}>
            Tenant console
          </Link>
          <Link
            to='/'
            style={{ color: '#ddd' }}
            onClick={(event) => {
              event.preventDefault();
              logout();
              navigate('/');
            }}
          >
            Log out
          </Link>
        </div>
      </Header>
      <Menu
        mode='horizontal'
        selectedKeys={[active]}
        items={SECTIONS}
        onClick={({ key }) => setActive(key)}
        style={{ background: '#fff', padding: '0 16px' }}
      />
      <Content
        style={{
          padding: '24px',
          maxWidth: 1440,
          width: '100%',
          margin: '0 auto',
        }}
      >
        <Alert
          type='warning'
          showIcon
          style={{ marginBottom: 16 }}
          message='Operator surface'
          description='Actions here cross company boundaries and are written to the append-only audit trail. Stripe remains the source of truth for subscription state.'
        />
        {active === 'overview' && <OverviewSection />}
        {active === 'companies' && <CompaniesSection />}
        {active === 'plans' && <PlansSection />}
        {active === 'subscriptions' && <SubscriptionsSection />}
        {active === 'settings' && <SettingsSection />}
        {active === 'audit' && <AuditSection />}
      </Content>
    </Layout>
  );
}
