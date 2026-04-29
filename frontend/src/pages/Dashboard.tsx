import { Layout as AntLayout, Card, Col, Row, Typography } from 'antd';
import { Chat } from '../components/Chat';
import { useAuth } from '../context/AuthContext';
// ChatProvider wrapped in App.tsx, no local needed
import { UserTable } from '@/components/UserTable';
import { WebsiteTable } from '@/components/WebsiteTable';
import { ChatProvider } from '@/context/ChatContext';

const { Title, Text } = Typography;

export function Dashboard() {
  const { isAuthenticated } = useAuth();

  if (!isAuthenticated) {
    return (
      <div
        style={{
          textAlign: 'center',
          padding: '80px 24px',
          maxWidth: 480,
          margin: '0 auto',
        }}
      >
        <Card style={{ borderRadius: '16px' }}>
          <Title level={3} style={{ marginBottom: 16 }}>
            Access Required
          </Title>
          <Text type='secondary'>
            Please <a href='/login'>login</a> to access your dashboard and
            manage your sites.
          </Text>
        </Card>
      </div>
    );
  }

  return (
    <AntLayout style={{ background: 'transparent' }}>
      <Row gutter={[32, 32]}>
        <Col span={24}>
          <div style={{ marginBottom: 8 }}>
            <Title
              level={2}
              style={{
                fontWeight: 700,
                marginBottom: 8,
                letterSpacing: '-0.5px',
              }}
            >
              Dashboard
            </Title>
            <Text type='secondary'>
              Manage your sites and chat with your data
            </Text>
          </div>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title={<div style={{ fontWeight: 600 }}>Websites</div>}
            style={{ height: '100%' }}
          >
            <WebsiteTable />
          </Card>
        </Col>

        <Col xs={24} lg={12}>
          <Card
            title={<div style={{ fontWeight: 600 }}>Your Users</div>}
            style={{ height: '100%' }}
          >
            <UserTable />
          </Card>
        </Col>

        <Col span={24}>
          <Card
            title={<div style={{ fontWeight: 600 }}>Chat with your site</div>}
            extra={
              <Text type='secondary' style={{ fontSize: 14 }}>
                Ask questions about your indexed content
              </Text>
            }
          >
            <ChatProvider>
              <Chat />
            </ChatProvider>
          </Card>
        </Col>
      </Row>
    </AntLayout>
  );
}
