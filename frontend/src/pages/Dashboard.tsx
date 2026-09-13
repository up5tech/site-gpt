import {
  ArrowRightOutlined,
  CloudUploadOutlined,
  DatabaseOutlined,
  GlobalOutlined,
  LockOutlined,
  MessageOutlined,
  PlusOutlined,
  SyncOutlined,
  TeamOutlined,
} from '@ant-design/icons';
import { Layout as AntLayout, Button, Card, Col, Empty, List, Row, Statistic, Tag, Typography } from 'antd';
import { Link } from 'react-router-dom';
import { Chat } from '../components/Chat';
import { useAuth } from '../context/AuthContext';
import { UserTable } from '@/components/UserTable';
import { WebsiteTable } from '@/components/WebsiteTable';
import { ChatProvider } from '@/context/ChatContext';
import { getDashboardStats, getRecentConversations } from '@/utils/api';
import type { DashboardStats, RecentConversation } from '@/types/api';
import { useEffect, useState } from 'react';

const { Title, Text } = Typography;

interface StatCardProps {
  icon: React.ReactNode;
  label: string;
  value: number;
  chipBg: string;
  chipFg: string;
  loading?: boolean;
  to?: string;
}

function StatCard({ icon, label, value, chipBg, chipFg, loading, to }: StatCardProps) {
  const card = (
    <Card
      className='premium-card'
      styles={{ body: { padding: '20px 24px' } }}
      style={{
        height: '100%',
        cursor: to ? 'pointer' : 'default',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
        <div
          style={{
            width: 48,
            height: 48,
            borderRadius: 12,
            background: chipBg,
            color: chipFg,
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            fontSize: 22,
            flexShrink: 0,
          }}
        >
          {icon}
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          {loading ? (
            <div
              style={{
                width: 64,
                height: 28,
                borderRadius: 6,
                background: '#e5e7eb',
                marginTop: 2,
              }}
            />
          ) : (
            <Statistic
              value={value}
              valueStyle={{
                fontWeight: 700,
                fontSize: 28,
                color: '#111827',
                lineHeight: 1.1,
              }}
            />
          )}
          <div style={{ color: '#6b7280', fontSize: 13, marginTop: 4 }}>{label}</div>
        </div>
        {to && (
          <ArrowRightOutlined
            className='stat-chevron'
            style={{
              color: '#9ca3af',
              fontSize: 16,
              flexShrink: 0,
              opacity: 0.45,
              transition: 'opacity 0.2s ease, transform 0.2s ease',
            }}
          />
        )}
      </div>
    </Card>
  );

  if (to) {
    return (
      <Link to={to} style={{ textDecoration: 'none' }} aria-label={`${label}: ${value}. Open ${label}`}>
        {card}
      </Link>
    );
  }
  return card;
}

export function Dashboard() {
  const { isAuthenticated, user } = useAuth();

  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [loadingStats, setLoadingStats] = useState(true);
  const [recent, setRecent] = useState<RecentConversation[]>([]);

  useEffect(() => {
    if (!isAuthenticated) return;
    setLoadingStats(true);
    getDashboardStats()
      .then((res) => setStats(res.data))
      .catch((err) => console.error('Dashboard stats error', err))
      .finally(() => setLoadingStats(false));
  }, [isAuthenticated]);

  useEffect(() => {
    if (!isAuthenticated) return;
    getRecentConversations(5)
      .then((res) => setRecent(res.data.items || []))
      .catch((err) => console.error('Recent conversations error', err));
  }, [isAuthenticated]);

  const today = new Date().toLocaleDateString('en-US', {
    weekday: 'long',
    month: 'long',
    day: 'numeric',
  });

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
          <LockOutlined style={{ fontSize: 32, color: '#9ca3af', marginBottom: 12 }} />
          <Title level={3} style={{ marginBottom: 16 }}>
            Access Required
          </Title>
          <Text type='secondary'>
            Please <a href='/login'>login</a> to access your dashboard and manage your
            sites.
          </Text>
        </Card>
      </div>
    );
  }

  return (
    <AntLayout style={{ background: 'transparent' }}>
      {/* Page header */}
      <Row align='bottom' justify='space-between' style={{ marginBottom: 24 }}>
        <Col>
          <Title
            level={2}
            style={{ fontWeight: 700, marginBottom: 4, letterSpacing: '-0.5px' }}
          >
            Welcome back, {user?.first_name || 'there'}
          </Title>
          <Text type='secondary'>
            {today} · Here&apos;s what&apos;s happening with your sites
          </Text>
        </Col>
        <Col>
          <Link to='/websites'>
            <Button type='primary' icon={<PlusOutlined />}>
              Add Website
            </Button>
          </Link>
        </Col>
      </Row>

      {/* Stat cards */}
      <div
        style={{
          display: 'flex',
          flexWrap: 'wrap',
          gap: 24,
          marginBottom: 8,
        }}
      >
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <StatCard
            icon={<GlobalOutlined />}
            label='Total sites'
            value={stats?.total_websites ?? 0}
            chipBg='#111827'
            chipFg='#ffffff'
            loading={loadingStats}
            to='/websites'
          />
        </div>
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <StatCard
            icon={<DatabaseOutlined />}
            label='Indexed pages'
            value={stats?.total_documents ?? 0}
            chipBg='#ecfdf5'
            chipFg='#10b981'
            loading={loadingStats}
            to='/websites'
          />
        </div>
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <StatCard
            icon={<SyncOutlined />}
            label='Ingesting'
            value={stats?.ingesting_websites ?? 0}
            chipBg='#fffbeb'
            chipFg='#d97706'
            loading={loadingStats}
            to='/websites'
          />
        </div>
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <StatCard
            icon={<MessageOutlined />}
            label='Conversations'
            value={stats?.total_chat_messages ?? 0}
            chipBg='#eff6ff'
            chipFg='#3b82f6'
            loading={loadingStats}
            to='/playground?focus=latest'
          />
        </div>
        <div style={{ flex: '1 1 200px', minWidth: 200 }}>
          <StatCard
            icon={<TeamOutlined />}
            label='Team members'
            value={stats?.team_members ?? 0}
            chipBg='#eef2ff'
            chipFg='#6366f1'
            loading={loadingStats}
            to='/users'
          />
        </div>
      </div>

      {/* Recent conversations */}
      <Row gutter={[24, 24]} style={{ marginBottom: 8 }}>
        <Col span={24}>
          <Card
            title={
              <span style={{ fontWeight: 600 }}>
                <MessageOutlined style={{ marginRight: 8, color: '#6b7280' }} />
                Recent conversations
              </span>
            }
            extra={
              <Link to='/playground?focus=latest'>
                <Text type='secondary' style={{ fontSize: 14 }}>
                  View all
                </Text>
              </Link>
            }
            className='premium-card'
          >
            {recent.length === 0 ? (
              <Empty
                image={Empty.PRESENTED_IMAGE_SIMPLE}
                description='No conversations yet'
              />
            ) : (
              <List
                dataSource={recent}
                renderItem={(c: RecentConversation) => (
                  <List.Item
                    style={{ cursor: 'pointer', padding: '10px 4px' }}
                    onClick={() =>
                      (window.location.href = `/playground?website=${c.website_id}&focus=${encodeURIComponent(c.session_id)}`)
                    }
                  >
                    <div style={{ width: '100%' }}>
                      <div
                        style={{
                          display: 'flex',
                          alignItems: 'center',
                          justifyContent: 'space-between',
                          gap: 8,
                        }}
                      >
                        <Text strong ellipsis style={{ maxWidth: '70%' }}>
                          {c.title || 'Chat'}
                        </Text>
                        <Tag color='blue' style={{ margin: 0 }}>
                          {c.website_name}
                        </Tag>
                      </div>
                      <div
                        style={{
                          fontSize: 12,
                          color: '#9ca3af',
                          marginTop: 2,
                        }}
                      >
                        {c.message_count} msgs ·{' '}
                        {new Date(c.last_message_at).toLocaleString()}
                      </div>
                    </div>
                  </List.Item>
                )}
              />
            )}
          </Card>
        </Col>
      </Row>

      {/* Websites + Chat */}
      <Row gutter={[24, 24]} style={{ marginBottom: 8 }}>
        <Col xs={24} lg={15}>
          <Card
            title={
              <span style={{ fontWeight: 600 }}>
                <GlobalOutlined style={{ marginRight: 8, color: '#6b7280' }} />
                Websites
              </span>
            }
            extra={
              <Link to='/websites'>
                <Text type='secondary' style={{ fontSize: 14 }}>
                  View all
                </Text>
              </Link>
            }
            className='premium-card'
            style={{ height: '100%' }}
          >
            <WebsiteTable />
          </Card>
        </Col>

        <Col xs={24} lg={9}>
          <Card
            title={
              <span style={{ fontWeight: 600 }}>
                <CloudUploadOutlined style={{ marginRight: 8, color: '#6b7280' }} />
                Chat with your site
              </span>
            }
            extra={
              <Text type='secondary' style={{ fontSize: 14 }}>
                Ask about indexed content
              </Text>
            }
            className='premium-card'
            style={{ height: '100%' }}
          >
            <ChatProvider>
              <Chat />
            </ChatProvider>
          </Card>
        </Col>
      </Row>

      {/* Team members */}
      <Row gutter={[24, 24]} style={{ marginTop: 16 }}>
        <Col span={24}>
          <Card
            title={
              <span style={{ fontWeight: 600 }}>
                <TeamOutlined style={{ marginRight: 8, color: '#6b7280' }} />
                Team Members
              </span>
            }
            extra={
              <Link to='/users'>
                <Text type='secondary' style={{ fontSize: 14 }}>
                  View all
                </Text>
              </Link>
            }
            className='premium-card'
          >
            <UserTable compact />
          </Card>
        </Col>
      </Row>
    </AntLayout>
  );
}
