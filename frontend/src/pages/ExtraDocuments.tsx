import { Website } from '@/types/api';
import {
  DeleteOutlined,
  FileTextOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Button,
  Card,
  Col,
  Form,
  Input,
  message,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Typography,
  Upload,
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
  website_id?: string;
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
  const [fileList, setFileList] = useState<any[]>([]);
  const [uploading, setUploading] = useState(false);

  // State for websites
  const [websites, setWebsites] = useState<Website[]>([]);
  const [loadingWebsites, setLoadingWebsites] = useState(false);

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
      title: 'Website',
      dataIndex: 'website_id',
      key: 'website_id',
      render: (websiteId) => {
        if (!websiteId) return '—';
        const website = websites.find((w) => w.id === websiteId);
        return (
          <Text type='secondary' style={{ fontSize: '14px' }}>
            {website?.name || '—'}
          </Text>
        );
      },
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
            {attachments.map((att: any) => (
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

  const fetchWebsites = async () => {
    if (!isAuthenticated) return;
    setLoadingWebsites(true);
    try {
      const response = await api.get('/websites', {
        params: {
          page: 1,
          limit: 100, // Get all websites
        },
      });
      setWebsites(response.data.items || []);
    } catch (error) {
      console.error('Fetch websites error', error);
      message.error('Failed to load websites');
    } finally {
      setLoadingWebsites(false);
    }
  };

  useEffect(() => {
    fetchDocuments();
  }, [page, nameFilter, isAuthenticated]);

  useEffect(() => {
    if (isAuthenticated) {
      fetchWebsites();
    }
  }, [isAuthenticated]);

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
    setFileList(
      (document.attachments || []).map((att) => ({
        uid: att.id,
        name: att.filename,
        status: 'done',
        size: att.file_size,
      })),
    );
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingDocument(null);
    form.resetFields();
    setFileList([]);
    setIsModalOpen(true);
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();

      // Get file IDs from uploaded files
      const fileIds: string[] = fileList
        .filter((f: any) => f.response && f.response.file_id)
        .map((f: any) => f.response.file_id);

      const payload = {
        ...values,
        file_ids: fileIds,
        website_id: values.website_id || null, // Ensure null if not selected
      };

      if (editingDocument) {
        await api.put(`/extra_documents/${editingDocument.id}`, payload);
        message.success('Document updated successfully');
      } else {
        await api.post('/extra_documents', payload);
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
    setFileList([]);
  };

  const onRemove = (file: any) => {
    const newFileList = fileList.filter((f) => f.uid !== file.uid);
    setFileList(newFileList);
    return false;
  };

  const handleBeforeUpload = async (file: any) => {
    // Validate file type
    const allowedTypes = [
      'application/pdf',
      'text/plain',
      'application/msword',
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    ];
    if (!allowedTypes.includes(file.type)) {
      message.error('Only PDF, TXT, DOC, and DOCX files are allowed');
      return Upload.LIST_IGNORE;
    }

    // Upload file immediately
    setUploading(true);
    try {
      const formData = new FormData();
      formData.append('file', file);

      const response = await api.post('/uploads', formData, {
        headers: {
          'Content-Type': 'multipart/form-data',
        },
      });

      // Add file to list with response
      const newFile = {
        ...file,
        uid: response.data.file_id,
        response: response.data,
      };
      setFileList((prev) => [...prev, newFile]);
    } catch (error) {
      console.error('Upload file error', error);
      message.error(`Failed to upload ${file.name}`);
    } finally {
      setUploading(false);
    }

    // Return false to prevent default upload
    return false;
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
            name='website_id'
            label='Website'
            tooltip='Optional: Associate this document with a specific website'
          >
            <Select
              placeholder='Select a website (optional)'
              allowClear
              loading={loadingWebsites}
              showSearch
              optionFilterProp='children'
              filterOption={(input, option) =>
                (option?.label ?? '')
                  .toLowerCase()
                  .includes(input.toLowerCase())
              }
              options={websites.map((website) => ({
                label: website.name,
                value: website.id,
              }))}
            />
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
          <Form.Item label='Attachments'>
            <Upload
              beforeUpload={handleBeforeUpload}
              onRemove={onRemove}
              fileList={fileList}
              itemRender={(_: any, file: any) => {
                // console.log(file);
                return (
                  <Space>
                    <FileTextOutlined />
                    {file.name || file.filename || file.response?.filename}
                    <Button
                      type='link'
                      danger
                      onClick={() => onRemove(file)}
                      icon={<DeleteOutlined />}
                    />
                  </Space>
                );
              }}
            >
              <Button icon={<UploadOutlined />} loading={uploading}>
                Click to Upload
              </Button>
            </Upload>
            <div style={{ marginTop: 8, fontSize: '12px', color: '#999' }}>
              Supported formats: PDF, TXT, DOC, DOCX
            </div>
          </Form.Item>
        </Form>
      </Modal>
    </>
  );
}
