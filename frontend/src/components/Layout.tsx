import {
  LogoutOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import { Dropdown, Layout, MenuProps, Space, Typography } from 'antd';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const { Header, Content } = Layout;
const { Text } = Typography;

interface Props {
  children: React.ReactNode;
}

export function LayoutComponent({ children }: Props) {
  const { isAuthenticated, user, logout } = useAuth();
  const location = useLocation();
  const navigate = useNavigate();

  const menuItems: { key: string; label: string; disabled?: boolean }[] = [
    { key: '/', label: 'Dashboard' },
    { key: '/websites', label: 'Websites' },
    { key: '/playground', label: 'Playground' },
    { key: '/contacts', label: 'Contacts' },
    { key: '/users', label: 'Users' },
    { key: '/documents', label: 'Documents' },
    // V2 pages (plans/PLAN_V2.md). The nav slots exist up front so the header
    // does not jump when each page lands; they render disabled because a link
    // to a route that does not exist yet would be a dead link. Each one is
    // switched back on in the task that creates its page.
    { key: '/training', label: 'Training', disabled: true },
    { key: '/handoffs', label: 'Handoffs', disabled: true },
    { key: '/analytics', label: 'Analytics', disabled: true },
    { key: '/integrations', label: 'Integrations', disabled: true },
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
              {menuItems.map((item) =>
                item.disabled ? (
                  <Text
                    key={item.key}
                    type='secondary'
                    title='Coming soon'
                    style={{ cursor: 'not-allowed' }}
                  >
                    {item.label}
                  </Text>
                ) : (
                  <Link
                    key={item.key}
                    to={item.key}
                    style={{
                      fontWeight:
                        location.pathname === item.key ? '600' : '400',
                      borderBottom:
                        location.pathname === item.key
                          ? '2px solid #000'
                          : 'none',
                      paddingBottom: '4px',
                    }}
                  >
                    {item.label}
                  </Link>
                ),
              )}
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
