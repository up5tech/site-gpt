import {
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  KeyOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Breadcrumb,
  Button,
  Card,
  Col,
  Descriptions,
  Form,
  Input,
  Modal,
  Popconfirm,
  Row,
  Space,
  Table,
  Tag,
  Typography,
} from 'antd';
import { DatabaseOutlined } from '@ant-design/icons';
import useApp from 'antd/es/app/useApp';
import type { ColumnsType } from 'antd/es/table';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { EmbedToken, EmbedTokenCreated, Website, WebsitePage } from '../types/api';
import api from '../utils/api';

const { Paragraph, Title, Text } = Typography;

export function WebsiteDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { message } = useApp();
  // The embed-token routes are admin-only on the server; hiding the card keeps a
  // manager from clicking into a 403.
  const { user } = useAuth();
  const isAdmin = user?.role === 'admin';

  const [website, setWebsite] = useState<Website | null>(null);
  const [pages, setPages] = useState<WebsitePage[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPage, setEditingPage] = useState<WebsitePage | null>(null);
  const [startingIngest, setStartingIngest] = useState(false);
  const [embedToken, setEmbedToken] = useState<EmbedToken | null>(null);
  const [tokenBusy, setTokenBusy] = useState(false);
  const [rawToken, setRawToken] = useState('');
  const [tokenModalOpen, setTokenModalOpen] = useState(false);
  const [form] = Form.useForm();

  // Mirrors the API's rule: a `processing` row is only "in flight" until
  // STUCK_INGEST_AFTER (6h) has passed since websites.updated_at. After that the
  // worker is presumed dead and a manual retry must stay possible.
  const STUCK_INGEST_AFTER_MS = 6 * 60 * 60 * 1000;
  const ingestInProgress =
    website?.ingest_status === 'processing' &&
    !!website?.updated_at &&
    Date.now() - new Date(website.updated_at).getTime() <= STUCK_INGEST_AFTER_MS;

  const fetchWebsiteDetail = useCallback(async () => {
    try {
      const response = await api.get(`/websites/${id}`);
      setWebsite(response.data);
    } catch (error) {
      console.error('Fetch website detail error', error);
      message.error('Failed to load website details');
    }
  }, [id, message]);

  const fetchPages = useCallback(async () => {
    setPagesLoading(true);
    try {
      const response = await api.get(`/websites/${id}/pages`, {
        params: { page, limit },
      });
      setPages(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch pages error', error);
      message.error('Failed to load website pages');
    } finally {
      setPagesLoading(false);
    }
  }, [id, limit, page, message]);

  const fetchEmbedToken = useCallback(async () => {
    try {
      const response = await api.get<EmbedToken>(`/websites/${id}/embed-token`);
      setEmbedToken(response.data);
    } catch (error) {
      const status = (error as { response?: { status?: number } }).response?.status;
      // 404 is the normal "nothing has ever been issued" answer.
      if (status === 404) {
        setEmbedToken(null);
        return;
      }
      console.error('Fetch embed token error', error);
    }
  }, [id]);

  const issueEmbedToken = async (mode: 'mint' | 'rotate') => {
    setTokenBusy(true);
    try {
      const url = `/websites/${id}/embed-token${mode === 'rotate' ? '/rotate' : ''}`;
      const response = await api.post<EmbedTokenCreated>(url);
      setEmbedToken(response.data);
      // The raw value exists in this answer only: show it, then never again.
      setRawToken(response.data.token);
      setTokenModalOpen(true);
    } catch (error) {
      const failure = (
        error as { response?: { status?: number; data?: { detail?: string } } }
      ).response;
      if (failure?.status === 409) {
        message.warning(
          failure.data?.detail ||
            'This website already has an active embed token.',
        );
        fetchEmbedToken();
      } else {
        message.error('Failed to issue an embed token');
      }
    } finally {
      setTokenBusy(false);
    }
  };

  const revokeEmbedToken = async () => {
    setTokenBusy(true);
    try {
      await api.delete(`/websites/${id}/embed-token`);
      message.success('Embed token revoked');
      fetchEmbedToken();
    } catch (error) {
      console.error('Revoke embed token error', error);
      message.error('Failed to revoke the embed token');
    } finally {
      setTokenBusy(false);
    }
  };

  useEffect(() => {
    if (id) {
      fetchWebsiteDetail();
      fetchPages();
      if (isAdmin) fetchEmbedToken();
    }
    setLoading(false);
  }, [id, isAdmin, fetchWebsiteDetail, fetchEmbedToken, fetchPages]);

  const handleLoadSitemap = async () => {
    try {
      await api.post(`/websites/${id}/load-site-map`);
      message.success('Sitemap loaded successfully');
      fetchPages();
    } catch (error) {
      console.error('Load sitemap error', error);
      message.error('Failed to load sitemap');
    }
  };

  const handleRunIngest = async () => {
    setStartingIngest(true);
    try {
      await api.post(`/ingest`, null, { params: { website_id: id } });
      message.success('Ingest started successfully');
      fetchWebsiteDetail();
    } catch (error) {
      console.error('Run ingest error', error);
      const failure = (
        error as { response?: { status?: number; data?: { detail?: string } } }
      ).response;
      if (failure?.status === 409) {
        // The API refuses a second crawl while one is running.
        message.warning(
          failure.data?.detail ||
            'An ingest is already running for this website.',
        );
        fetchWebsiteDetail();
      } else {
        message.error('Failed to start ingest');
      }
    } finally {
      setStartingIngest(false);
    }
  };

  const handleAddPage = () => {
    setEditingPage(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleEditPage = (page: WebsitePage) => {
    setEditingPage(page);
    form.setFieldsValue(page);
    setIsModalOpen(true);
  };

  const handleDeletePage = async (pageId: string) => {
    try {
      await api.delete(`/websites/${id}/pages/${pageId}`);
      message.success('Page deleted successfully');
      fetchPages();
    } catch (error) {
      console.error('Delete page error', error);
      message.error('Failed to delete page');
    }
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingPage) {
        await api.put(`/websites/${id}/pages/${editingPage.id}`, values);
        message.success('Page updated successfully');
      } else {
        await api.post(`/websites/${id}/pages`, values);
        message.success('Page added successfully');
      }
      setIsModalOpen(false);
      fetchPages();
    } catch (error) {
      console.error('Save page error', error);
      message.error('Failed to save page');
    }
  };

  const pageColumns: ColumnsType<WebsitePage> = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text) => <Text strong>{text}</Text>,
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
      render: (text) => (
        <a href={text} target='_blank' rel='noopener noreferrer'>
          {text}
        </a>
      ),
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      ellipsis: true,
    },
    {
      title: 'Actions',
      key: 'actions',
      width: 120,
      render: (_, record) => (
        <Space size='small'>
          <Button
            type='text'
            icon={<EditOutlined />}
            onClick={() => handleEditPage(record)}
          />
          <Popconfirm
            title='Delete Page'
            description='Are you sure you want to delete this page?'
            onConfirm={() => handleDeletePage(record.id)}
            okText='Yes'
            cancelText='No'
          >
            <Button type='text' danger icon={<DeleteOutlined />} />
          </Popconfirm>
        </Space>
      ),
    },
  ];

  if (loading) return null;

  return (
    <div style={{ padding: '0 0 24px 0' }}>
      <Breadcrumb
        style={{ marginBottom: 16 }}
        items={[
          { title: <a onClick={() => navigate('/websites')}>Websites</a> },
          { title: website?.name || 'Detail' },
        ]}
      />

      <div
        style={{
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'flex-start',
          marginBottom: 24,
        }}
      >
        <Space direction='vertical' size={0}>
          <Space>
            <Button
              icon={<ArrowLeftOutlined />}
              onClick={() => navigate('/websites')}
              type='text'
            />
            <Title level={2} style={{ margin: 0 }}>
              {website?.name}
            </Title>
          </Space>
          <Text type='secondary' style={{ marginLeft: 40 }}>
            <GlobalOutlined /> {website?.url}
          </Text>
        </Space>
        <Space>
          <Button
            type='primary'
            icon={<ReloadOutlined />}
            onClick={handleLoadSitemap}
          >
            Sync Sitemap
          </Button>
          <Button
            type='primary'
            icon={<DatabaseOutlined />}
            onClick={handleRunIngest}
            loading={startingIngest}
            disabled={startingIngest || ingestInProgress}
            style={{ backgroundColor: '#10b981', borderColor: '#10b981' }}
            title={
              ingestInProgress
                ? 'An ingest is already running for this website'
                : undefined
            }
          >
            {ingestInProgress ? 'Ingesting…' : 'Run Ingest'}
          </Button>
        </Space>
      </div>

      <Row gutter={[24, 24]}>
        <Col span={24}>
          <Card
            title='Website Information'
            variant='borderless'
            className='premium-card'
          >
            <Descriptions
              column={{ xxl: 3, xl: 3, lg: 2, md: 2, sm: 1, xs: 1 }}
            >
              <Descriptions.Item label='Name'>
                {website?.name}
              </Descriptions.Item>
              <Descriptions.Item label='URL'>
                <a
                  href={website?.url}
                  target='_blank'
                  rel='noopener noreferrer'
                >
                  {website?.url}
                </a>
              </Descriptions.Item>
              <Descriptions.Item label='Sitemap URL'>
                <Text copyable>{website?.site_map_url}</Text>
              </Descriptions.Item>
              <Descriptions.Item label='Status'>
                <Tag color={website?.status === 'active' ? 'green' : 'red'}>
                  {website?.status?.toUpperCase()}
                </Tag>
              </Descriptions.Item>
              <Descriptions.Item label='Ingest Status'>
                {(() => {
                  let color = 'default';
                  const s = website?.ingest_status;
                  if (s === 'completed') color = 'success';
                  if (s === 'processing') color = 'processing';
                  if (s === 'failed') color = 'error';
                  return <Tag color={color}>{s?.toUpperCase()}</Tag>;
                })()}
              </Descriptions.Item>
              <Descriptions.Item label='Created At'>
                {website?.created_at
                  ? new Date(website.created_at).toLocaleString()
                  : '-'}
              </Descriptions.Item>
              <Descriptions.Item
                label='Description'
                span={{ xxl: 3, xl: 3, lg: 2, md: 2, sm: 1, xs: 1 }}
              >
                {website?.description || 'No description provided'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

        {isAdmin && (
          <Col span={24}>
            <Card
              title={
                <Space>
                  <KeyOutlined />
                  <span>Embed token</span>
                </Space>
              }
              variant='borderless'
              className='premium-card'
            >
              <Space direction='vertical' size='middle' style={{ width: '100%' }}>
                <Text type='secondary'>
                  A token lets you revoke the snippets you no longer deploy. It
                  is visible in the page source, so it deters casual copying —
                  it does not prove the request came from your site.
                </Text>
                {embedToken ? (
                  <Space wrap>
                    <Tag color={embedToken.active ? 'green' : 'default'}>
                      {embedToken.active ? 'ACTIVE' : 'REVOKED'}
                    </Tag>
                    <Text code>{embedToken.token_prefix}…</Text>
                    <Text type='secondary'>
                      Created{' '}
                      {new Date(embedToken.created_at).toLocaleString()}
                    </Text>
                    {embedToken.last_used_at && (
                      <Text type='secondary'>
                        Last used{' '}
                        {new Date(embedToken.last_used_at).toLocaleString()}
                      </Text>
                    )}
                  </Space>
                ) : (
                  <Text type='secondary'>
                    No token has been issued for this website.
                  </Text>
                )}
                <Space wrap>
                  {embedToken ? (
                    <Button
                      icon={<ReloadOutlined />}
                      loading={tokenBusy}
                      onClick={() => issueEmbedToken('rotate')}
                    >
                      {embedToken.active ? 'Rotate token' : 'Issue new token'}
                    </Button>
                  ) : (
                    <Button
                      type='primary'
                      icon={<KeyOutlined />}
                      loading={tokenBusy}
                      onClick={() => issueEmbedToken('mint')}
                    >
                      Create token
                    </Button>
                  )}
                  {embedToken?.active && (
                    <Popconfirm
                      title='Revoke this token?'
                      description='Every deployed snippet carrying it stops working immediately.'
                      okText='Revoke'
                      okButtonProps={{ danger: true }}
                      cancelText='Cancel'
                      onConfirm={revokeEmbedToken}
                    >
                      <Button danger loading={tokenBusy}>
                        Revoke
                      </Button>
                    </Popconfirm>
                  )}
                </Space>
              </Space>
            </Card>
          </Col>
        )}

        <Col span={24}>
          <Card
            title={
              <div
                style={{
                  display: 'flex',
                  justifyContent: 'space-between',
                  alignItems: 'center',
                }}
              >
                <span>Website Pages</span>
                <Button
                  type='primary'
                  size='small'
                  icon={<PlusOutlined />}
                  onClick={handleAddPage}
                >
                  Add Page
                </Button>
              </div>
            }
            variant='borderless'
            className='premium-card'
          >
            <Table
              columns={pageColumns}
              dataSource={pages}
              loading={pagesLoading}
              rowKey='id'
              pagination={{
                current: page,
                total,
                pageSize: limit,
                onChange: setPage,
                showSizeChanger: false,
              }}
            />
          </Card>
        </Col>
      </Row>

      <Modal
        title={editingPage ? 'Edit Page' : 'Add Page'}
        open={isModalOpen}
        onOk={handleModalOk}
        onCancel={() => setIsModalOpen(false)}
        destroyOnHidden
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Form.Item
            name='name'
            label='Page Name'
            rules={[{ required: true, message: 'Please enter page name' }]}
          >
            <Input placeholder='Home Page' />
          </Form.Item>
          <Form.Item
            name='url'
            label='URL'
            rules={[{ required: true, message: 'Please enter page URL' }]}
          >
            <Input placeholder='https://example.com/page' />
          </Form.Item>
          <Form.Item name='description' label='Description'>
            <Input.TextArea rows={4} placeholder='Page description...' />
          </Form.Item>
        </Form>
      </Modal>

      <Modal
        title='Copy your embed token'
        open={tokenModalOpen}
        onCancel={() => setTokenModalOpen(false)}
        footer={[
          <Button
            key='done'
            type='primary'
            onClick={() => setTokenModalOpen(false)}
          >
            Done
          </Button>,
        ]}
      >
        <Alert
          type='warning'
          showIcon
          style={{ marginBottom: 16 }}
          message='This token is shown once'
          description='Only its hash is stored, so it cannot be retrieved later. If you lose it, rotate the token.'
        />
        <Text code copyable={{ text: rawToken }} style={{ wordBreak: 'break-all' }}>
          {rawToken}
        </Text>
        <Paragraph style={{ marginTop: 16, marginBottom: 0 }}>
          Add it to your install snippet as <Text code>embedToken</Text> inside{' '}
          <Text code>window.ChatWidgetConfig</Text>.
        </Paragraph>
      </Modal>
    </div>
  );
}
