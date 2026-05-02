import {
  ArrowLeftOutlined,
  DeleteOutlined,
  EditOutlined,
  GlobalOutlined,
  PlusOutlined,
  ReloadOutlined,
} from '@ant-design/icons';
import {
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
import { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Website, WebsitePage } from '../types/api';
import api from '../utils/api';

const { Title, Text } = Typography;

export function WebsiteDetail() {
  const { id } = useParams<{ id: string }>();
  const navigate = useNavigate();
  const { message } = useApp();

  const [website, setWebsite] = useState<Website | null>(null);
  const [pages, setPages] = useState<WebsitePage[]>([]);
  const [loading, setLoading] = useState(true);
  const [pagesLoading, setPagesLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingPage, setEditingPage] = useState<WebsitePage | null>(null);
  const [form] = Form.useForm();

  const fetchWebsiteDetail = async () => {
    try {
      const response = await api.get(`/websites/${id}`);
      setWebsite(response.data);
    } catch (error) {
      console.error('Fetch website detail error', error);
      message.error('Failed to load website details');
    }
  };

  const fetchPages = async () => {
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
  };

  useEffect(() => {
    if (id) {
      fetchWebsiteDetail();
      fetchPages();
    }
    setLoading(false);
  }, [id, page]);

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
    try {
      await api.post(`/ingest`, null, { params: { website_id: id } });
      message.success('Ingest started successfully');
      fetchWebsiteDetail();
    } catch (error) {
      console.error('Run ingest error', error);
      message.error('Failed to start ingest');
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
            style={{ backgroundColor: '#10b981', borderColor: '#10b981' }}
          >
            Run Ingest
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
              <Descriptions.Item label='Description' span={3}>
                {website?.description || 'No description provided'}
              </Descriptions.Item>
              <Descriptions.Item label='Created At'>
                {website?.created_at
                  ? new Date(website.created_at).toLocaleString()
                  : '-'}
              </Descriptions.Item>
            </Descriptions>
          </Card>
        </Col>

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
    </div>
  );
}
