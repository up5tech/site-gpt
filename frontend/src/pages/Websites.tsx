import { EyeOutlined } from '@ant-design/icons';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  message,
  Modal,
  Row,
  Space,
  Table,
  Typography,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { Website } from '../types/api';
import api from '../utils/api';

const { Title, Text } = Typography;

export function Websites() {
  const navigate = useNavigate();
  const [data, setData] = useState<Website[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [nameFilter, setNameFilter] = useState('');
  const [urlFilter, setUrlFilter] = useState('');
  const { isAuthenticated } = useAuth();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingWebsite, setEditingWebsite] = useState<Website | null>(null);
  const [form] = Form.useForm();

  const columns: ColumnsType<Website> = [
    {
      title: 'Name',
      dataIndex: 'name',
      key: 'name',
      render: (text) => (
        <Text strong style={{ color: '#111827' }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'URL',
      dataIndex: 'url',
      key: 'url',
    },
    {
      title: 'Description',
      dataIndex: 'description',
      key: 'description',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '14px' }}>
          {text || '—'}
        </Text>
      ),
    },
    {
      title: 'Site Map',
      dataIndex: 'site_map_url',
      key: 'site_map_url',
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <Space size='small'>
          <Button
            type='text'
            icon={<EyeOutlined />}
            onClick={() => navigate(`/websites/${record.id}`)}
          />
          <Button
            type='link'
            onClick={() => handleEdit(record)}
            style={{ padding: 0 }}
          >
            Edit
          </Button>
          <Button
            type='link'
            danger
            onClick={() => handleDelete(record.id)}
            style={{ padding: 0 }}
          >
            Delete
          </Button>
        </Space>
      ),
    },
  ];

  const fetchWebsites = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await api.get('/websites', {
        params: {
          name: nameFilter || undefined,
          url: urlFilter || undefined,
          page,
          limit,
        },
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch websites error', error);
      message.error('Failed to load websites');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchWebsites();
  }, [page, nameFilter, urlFilter, isAuthenticated]);

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/websites/${id}`);
      message.success('Website deleted successfully');
      fetchWebsites();
    } catch (error) {
      console.error('Delete website error', error);
      message.error('Failed to delete website');
    }
  };

  const handleEdit = (website: Website) => {
    setEditingWebsite(website);
    form.setFieldsValue(website);
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingWebsite(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingWebsite) {
        await api.put(`/websites/${editingWebsite.id}`, values);
        message.success('Website updated successfully');
      } else {
        await api.post('/websites', values);
        message.success('Website created successfully');
      }
      setIsModalOpen(false);
      fetchWebsites();
    } catch (error) {
      console.error('Save website error', error);
      message.error('Failed to save website');
    }
  };

  const handleModalCancel = () => {
    setIsModalOpen(false);
    setEditingWebsite(null);
  };

  return (
    <>
      <div style={{ marginBottom: 16 }}>
        <Title
          level={2}
          style={{
            fontWeight: 700,
            marginBottom: 8,
            letterSpacing: '-0.5px',
          }}
        >
          Websites
        </Title>
        <Text type='secondary'>Manage your websites for indexing</Text>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} md={8}>
            <Input.Search
              placeholder='Search by name...'
              onSearch={setNameFilter}
              allowClear
            />
          </Col>
          <Col xs={24} md={8}>
            <Input.Search
              placeholder='Search by URL...'
              onSearch={setUrlFilter}
              allowClear
            />
          </Col>
          <Col xs={24} md={8} style={{ textAlign: 'right' }}>
            <Button type='primary' onClick={handleCreate}>
              Add Website
            </Button>
          </Col>
        </Row>

        <Table
          columns={columns}
          dataSource={data}
          loading={loading}
          pagination={{
            current: page,
            total,
            pageSize: limit,
            onChange: setPage,
          }}
          rowKey='id'
        />
      </Card>

      <Modal
        title={editingWebsite ? 'Edit Website' : 'Add Website'}
        open={isModalOpen}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        width={600}
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Form.Item
            name='name'
            label='Name'
            rules={[{ required: true, message: 'Please enter website name' }]}
          >
            <Input placeholder='Website name' />
          </Form.Item>
          <Form.Item
            name='url'
            label='URL'
            rules={[{ required: true, message: 'Please enter website URL' }]}
          >
            <Input placeholder='https://example.com' />
          </Form.Item>
          <Form.Item name='description' label='Description'>
            <Input.TextArea
              placeholder='Website description (optional)'
              rows={3}
            />
          </Form.Item>
          <Form.Item
            name='site_map_url'
            label='Sitemap URL'
            rules={[{ required: true, message: 'Please enter sitemap URL' }]}
          >
            <Input placeholder='https://example.com/sitemap.xml' />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
