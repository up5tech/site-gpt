import {
  LogoutOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Dropdown, Layout, MenuProps, Space, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { getInboxStatus, INBOX_STATUS_CHANGED } from '../utils/api';

const { Header, Content } = Layout;
const { Text } = Typography;

interface Props {
  children: React.ReactNode;
}

export function LayoutComponent({ children }: Props) {
  const { isAuthenticated, user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  // The live-agent console is a per-company rollout: with the flag off its
  // whole surface answers 404, so the navigation must not offer it. One tiny
  // read per session answers `{enabled}` without touching the queue.
  const [inboxEnabled, setInboxEnabled] = useState(false);
  // Settings → the live-inbox switch asks for a re-read instead of a reload.
  const [inboxStatusRefresh, setInboxStatusRefresh] = useState(0);

  useEffect(() => {
    const refresh = () => setInboxStatusRefresh((value) => value + 1);
    window.addEventListener(INBOX_STATUS_CHANGED, refresh);
    return () => window.removeEventListener(INBOX_STATUS_CHANGED, refresh);
  }, []);

  useEffect(() => {
    if (!isAuthenticated) {
      setInboxEnabled(false);
      return;
    }
    let cancelled = false;
    getInboxStatus()
      .then((response) => {
        if (!cancelled) setInboxEnabled(response.data.enabled);
      })
      .catch(() => {
        if (!cancelled) setInboxEnabled(false);
      });
    return () => {
      cancelled = true;
    };
  }, [isAuthenticated, inboxStatusRefresh]);

  const menuItems = [
    { key: '/', label: 'Dashboard' },
    { key: '/websites', label: 'Websites' },
    { key: '/playground', label: 'Playground' },
    { key: '/contacts', label: 'Contacts' },
    { key: '/users', label: 'Users' },
    { key: '/documents', label: 'Documents' },
    { key: '/training', label: 'Training' },
    { key: '/handoffs', label: 'Handoffs' },
    ...(inboxEnabled ? [{ key: '/inbox', label: 'Inbox' }] : []),
    { key: '/analytics', label: 'Analytics' },
    { key: '/integrations', label: 'Integrations' },
  ];

  const dropdownItems: MenuProps['items'] = [
    {
      key: 'settings',
      label: 'Settings',
      icon: <SettingOutlined />,
      onClick: () => navigate('/settings'),
    },
    {
      key: 'logout',
      label: 'Logout',
      icon: <LogoutOutlined />,
      onClick: logout,
    },
  ];

  return (
    <Layout style={{ minHeight: '100vh' }}>
      <Header
        className='custom-header'
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: '16px',
        }}
      >
        <div
          style={{
            color: '#000',
            fontSize: '24px',
            fontWeight: '700',
            letterSpacing: '-0.5px',
          }}
        >
          Site GPT
        </div>
        <Space size='large' wrap>
          {isAuthenticated ? (
            <>
              {menuItems.map((item) => (
                <Link
                  key={item.key}
                  to={item.key}
                  style={{
                    fontWeight: location.pathname === item.key ? '600' : '400',
                    borderBottom:
                      location.pathname === item.key
                        ? '2px solid #000'
                        : 'none',
                    paddingBottom: '4px',
                  }}
                >
                  {item.label}
                </Link>
              ))}
              <Dropdown menu={{ items: dropdownItems }} placement='bottomRight'>
                <Text
                  style={{
                    cursor: 'pointer',
                    fontWeight: '500',
                    color: '#000',
                  }}
                >
                  <UserOutlined />
                  &nbsp;{user?.first_name || user?.email || 'User'}
                </Text>
              </Dropdown>
            </>
          ) : (
            <>
              <Link
                to='/login'
                style={{
                  fontWeight: location.pathname === '/login' ? '600' : '400',
                  borderBottom:
                    location.pathname === '/login' ? '2px solid #000' : 'none',
                  paddingBottom: '4px',
                }}
              >
                Login
              </Link>
              <Link
                to='/register'
                style={{
                  fontWeight: location.pathname === '/register' ? '600' : '400',
                  borderBottom:
                    location.pathname === '/register'
                      ? '2px solid #000'
                      : 'none',
                  paddingBottom: '4px',
                }}
              >
                Register
              </Link>
            </>
          )}
        </Space>
      </Header>
      <Content
        style={{
          padding: '32px',
          maxWidth: '1400px',
          margin: '0 auto',
          width: '100%',
        }}
      >
        {children}
      </Content>
    </Layout>
  );
}
