import { Button, Layout, Space } from 'antd';
import { Link, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';

const { Header, Content } = Layout;

interface Props {
  children: React.ReactNode;
}

export function LayoutComponent({ children }: Props) {
  const { isAuthenticated, logout } = useAuth();
  const location = useLocation();

  const menuItems = [
    { key: '/', label: 'Dashboard' },
    { key: '/websites', label: 'Websites' },
    { key: '/users', label: 'Users' },
    { key: '/documents', label: 'Documents' },
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
              <Button onClick={logout} type='text'>
                Logout
              </Button>
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
