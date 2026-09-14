import { Website } from '@/types/api';
import {
  CloudOutlined,
  DeleteOutlined,
  FileTextOutlined,
  GlobalOutlined,
  UploadOutlined,
} from '@ant-design/icons';
import {
  Button,
  Card,
  Col,
  Divider,
  Form,
  Input,
  message,
  Modal,
  Row,
  Select,
  Space,
  Table,
  Tag,
  Typography,
  Upload,
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../utils/api';
import {
  extractDriveFileId,
  pickGoogleDriveFiles,
} from '../utils/googleDrive';

const { Title, Text } = Typography;

// Optional OAuth client id for the native Google Drive Picker. When empty, the
// user can still paste a publicly-shared Drive link (no token needed).
const DRIVE_CLIENT_ID = import.meta.env.VITE_GOOGLE_DRIVE_CLIENT_ID || '';

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
    source?: string;
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
  const [deletedFileIds, setDeletedFileIds] = useState<string[]>([]);

  // Source-import modals
  const [urlModalOpen, setUrlModalOpen] = useState(false);
  const [urlValue, setUrlValue] = useState('');
  const [urlLoading, setUrlLoading] = useState(false);
  const [driveModalOpen, setDriveModalOpen] = useState(false);
  const [driveLink, setDriveLink] = useState('');
  const [driveToken, setDriveToken] = useState('');
  const [driveLoading, setDriveLoading] = useState(false);

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
                {renderSourceTag(att.source)}
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

  const renderSourceTag = (source?: string) => {
    if (!source || source === 'local') return null;
    if (source === 'url') {
      return (
        <Tag color='blue' style={{ marginLeft: 6 }}>
          URL
        </Tag>
      );
    }
    if (source === 'google_drive') {
      return (
        <Tag color='purple' style={{ marginLeft: 6 }}>
          Drive
        </Tag>
      );
    }
    return (
      <Tag style={{ marginLeft: 6 }}>{source}</Tag>
    );
  };

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
        file_id: att.id, // Store file_id for tracking deletions
        source: att.source,
        response: { filename: att.filename, file_id: att.id, source: att.source },
      })),
    );
    setDeletedFileIds([]); // Reset deleted file IDs
    setIsModalOpen(true);
  };

  const handleCreate = () => {
    setEditingDocument(null);
    form.resetFields();
    setFileList([]);
    setDeletedFileIds([]); // Reset deleted file IDs
    setIsModalOpen(true);
  };

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();

      // Get file IDs from uploaded files
      const fileIds: string[] = fileList
        .filter((f: any) => f.response && f.response.file_id)
        .map((f: any) => f.response.file_id);

      const payload: any = {
        ...values,
        file_ids: fileIds,
        website_id: values.website_id || null, // Ensure null if not selected
      };

      // Add delete_file_ids only when editing and there are deleted files
      if (editingDocument && deletedFileIds.length > 0) {
        payload.delete_file_ids = deletedFileIds;
      }

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
    setDeletedFileIds([]); // Reset deleted file IDs
  };

  const onRemove = (file: any) => {
    // If file has file_id (existing file from database), add to deletedFileIds
    if (file.file_id) {
      setDeletedFileIds((prev) => [...prev, file.file_id]);
    }

    const newFileList = fileList.filter((f) => f.uid !== file.uid);
    setFileList(newFileList);
    return false;
  };

  // --- Source-agnostic import helpers -------------------------------------

  const addFetchedFile = (resp: any, source: string) => {
    setFileList((prev) => [
      ...prev,
      {
        uid: resp.file_id,
        name: resp.filename,
        status: 'done',
        size: resp.file_size,
        response: { ...resp, source },
        source,
      },
    ]);
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
        source: 'local',
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

  const handleUrlSubmit = async () => {
    if (!urlValue.trim()) {
      message.error('Please enter a URL');
      return;
    }
    setUrlLoading(true);
    try {
      const { data } = await api.post('/uploads/url', { url: urlValue.trim() });
      addFetchedFile(data, 'url');
      message.success(`Added ${data.filename} from URL`);
      setUrlValue('');
      setUrlModalOpen(false);
    } catch (error) {
      console.error('URL import error', error);
      message.error('Failed to fetch file from URL');
    } finally {
      setUrlLoading(false);
    }
  };

  const handleDriveSubmit = async () => {
    const fileId = extractDriveFileId(driveLink);
    if (!fileId) {
      message.error('Invalid Google Drive link');
      return;
    }
    setDriveLoading(true);
    try {
      const { data } = await api.post('/uploads/google-drive', {
        file_id: fileId,
        access_token: driveToken || '',
      });
      addFetchedFile(data, 'google_drive');
      message.success(`Added ${data.filename} from Google Drive`);
      setDriveLink('');
      setDriveToken('');
      setDriveModalOpen(false);
    } catch (error) {
      console.error('Drive import error', error);
      message.error('Failed to import from Google Drive');
    } finally {
      setDriveLoading(false);
    }
  };

  const handleDrivePick = async () => {
    if (!DRIVE_CLIENT_ID) return;
    setDriveLoading(true);
    try {
      const docs = await pickGoogleDriveFiles(DRIVE_CLIENT_ID);
      for (const d of docs) {
        const { data } = await api.post('/uploads/google-drive', {
          file_id: d.id,
          access_token: d.token,
        });
        addFetchedFile(data, 'google_drive');
      }
      if (docs.length) {
        message.success(`Added ${docs.length} file(s) from Google Drive`);
        setDriveModalOpen(false);
      }
    } catch (error: any) {
      console.error('Drive picker error', error);
      message.error(error?.message || 'Google Drive picker failed');
    } finally {
      setDriveLoading(false);
    }
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
            <Space wrap style={{ marginBottom: 8 }}>
              <Upload
                beforeUpload={handleBeforeUpload}
                onRemove={onRemove}
                fileList={fileList.filter((f) => f.source === 'local')}
                showUploadList={false}
              >
                <Button icon={<UploadOutlined />} loading={uploading}>
                  Click to Upload
                </Button>
              </Upload>
              <Button
                icon={<GlobalOutlined />}
                onClick={() => setUrlModalOpen(true)}
              >
                From URL
              </Button>
              <Button
                icon={<CloudOutlined />}
                onClick={() => setDriveModalOpen(true)}
              >
                From Google Drive
              </Button>
            </Space>
            {/* Render ALL files (local + url + drive) here, with source badges */}
            <div style={{ marginTop: 8 }}>
              {fileList.length === 0 && (
                <Text type='secondary' style={{ fontSize: '12px' }}>
                  No files yet
                </Text>
              )}
              <Space direction='vertical' style={{ width: '100%' }}>
                {fileList.map((file) => (
                  <Space key={file.uid}>
                    <FileTextOutlined />
                    {file.name || file.filename || file.response?.filename}
                    {renderSourceTag(file.source || file.response?.source)}
                    <Button
                      type='link'
                      danger
                      onClick={() => onRemove(file)}
                      icon={<DeleteOutlined />}
                    />
                  </Space>
                ))}
              </Space>
            </div>
            <div style={{ marginTop: 8, fontSize: '12px', color: '#999' }}>
              Supported formats: PDF, TXT, DOC, DOCX
            </div>
          </Form.Item>
        </Form>
      </Modal>

      {/* URL import modal */}
      <Modal
        title='Add from URL'
        open={urlModalOpen}
        onOk={handleUrlSubmit}
        onCancel={() => setUrlModalOpen(false)}
        okText='Add'
        confirmLoading={urlLoading}
      >
        <Input
          placeholder='https://example.com/file.pdf'
          value={urlValue}
          onChange={(e) => setUrlValue(e.target.value)}
          onPressEnter={handleUrlSubmit}
        />
        <div style={{ marginTop: 8, fontSize: '12px', color: '#999' }}>
          The file is downloaded and stored like a normal upload.
        </div>
      </Modal>

      {/* Google Drive import modal */}
      <Modal
        title='Add from Google Drive'
        open={driveModalOpen}
        onOk={handleDriveSubmit}
        onCancel={() => setDriveModalOpen(false)}
        okText='Add link'
        confirmLoading={driveLoading}
      >
        <Space direction='vertical' style={{ width: '100%' }}>
          {DRIVE_CLIENT_ID && (
            <Button
              icon={<CloudOutlined />}
              onClick={handleDrivePick}
              loading={driveLoading}
              block
            >
              Pick from Google Drive
            </Button>
          )}
          {DRIVE_CLIENT_ID && (
            <Divider plain style={{ margin: '4px 0' }}>
              or paste a share link
            </Divider>
          )}
          <Input
            placeholder='https://drive.google.com/file/d/.../view'
            value={driveLink}
            onChange={(e) => setDriveLink(e.target.value)}
          />
          <Input.Password
            placeholder='Access token (optional, for private files)'
            value={driveToken}
            onChange={(e) => setDriveToken(e.target.value)}
          />
          <div style={{ fontSize: '12px', color: '#999' }}>
            Publicly shared links work without a token.
          </div>
        </Space>
      </Modal>
    </>
  );
}
