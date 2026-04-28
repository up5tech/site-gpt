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
import { useAuth } from '../context/AuthContext';
import api from '../utils/api';

const { Title, Text } = Typography;

interface ExtraDocument {
  id: string;
  created_at: string;
  updated_at: string;
  name: string;
  content: string;
  company_id: string;
  attachments?: Array<{
    id: string;
    filename: string;
    file_size: number;
    file_type: string;
  }>;
}

export function ExtraDocuments() {
  const [data, setData] = useState<ExtraDocument[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [nameFilter, setNameFilter] = useState('');
  const { isAuthenticated } = useAuth();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingDocument, setEditingDocument] = useState<ExtraDocument | null>(
    null,
  );
  const [form] = Form.useForm();

  const columns: ColumnsType<ExtraDocument> = [
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
      title: 'Content',
      dataIndex: 'content',
      key: 'content',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '14px' }}>
          {text ? `${text.substring(0, 100)}...` : '—'}
        </Text>
      ),
    },
    {
      title: 'Attachments',
      dataIndex: 'attachments',
      key: 'attachments',
      render: (attachments) => {
        if (!attachments || attachments.length === 0) return '—';
        return (
          <Space size='small'>
            {attachments.map((att) => (
              <span key={att.id} style={{ fontSize: '12px' }}>
                📎 {att.filename}
              </span>
            ))}
          </Space>
        );
      },
    },
    {
      title: 'Actions',
      key: 'actions',
      render: (_, record) => (
        <Space size='middle'>
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

  const fetchDocuments = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await api.get('/extra_documents', {
        params: {
          page,
          limit,
        },
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch documents error', error);
      message.error('Failed to load documents');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [page, nameFilter, isAuthenticated]);

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/extra_documents/${id}`);
      message.success('Document deleted successfully');
      fetchDocuments();
    } catch (error) {
      console.error('Delete document error', error);
      message.error('Failed to delete document');
    }
  };

  const handleEdit = (document: ExtraDocument) => {
    setEditingDocument(document);
    form.setFieldsValue(document);
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingDocument(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingDocument) {
        await api.put(`/extra_documents/${editingDocument.id}`, values);
        message.success('Document updated successfully');
      } else {
        await api.post('/extra_documents', values);
        message.success('Document created successfully');
      }
      setIsModalOpen(false);
      fetchDocuments();
    } catch (error) {
      console.error('Save document error', error);
      message.error('Failed to save document');
    }
  };

  const handleModalCancel = () => {
    setIsModalOpen(false);
    setEditingDocument(null);
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
          Documents
        </Title>
        <Text type='secondary'>
          Manage extra documents for your knowledge base
        </Text>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} md={12}>
            <Input.Search
              placeholder='Search by name...'
              onSearch={setNameFilter}
              allowClear
            />
          </Col>
          <Col xs={24} md={12} style={{ textAlign: 'right' }}>
            <Button type='primary' onClick={handleCreate}>
              Add Document
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
        title={editingDocument ? 'Edit Document' : 'Add Document'}
        open={isModalOpen}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        width={600}
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Form.Item
            name='name'
            label='Name'
            rules={[{ required: true, message: 'Please enter document name' }]}
          >
            <Input placeholder='Document name' />
          </Form.Item>
          <Form.Item
            name='content'
            label='Content'
            rules={[
              { required: true, message: 'Please enter document content' },
            ]}
          >
            <Input.TextArea placeholder='Document content' rows={6} />
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
