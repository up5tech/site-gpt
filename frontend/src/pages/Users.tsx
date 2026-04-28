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
} from 'antd';
import type { ColumnsType } from 'antd/es/table';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import api from '../utils/api';

const { Title, Text } = Typography;

interface User {
  id: string;
  created_at: string;
  updated_at: string;
  company_id: string;
  email: string;
  phone: string | null;
  first_name: string;
  last_name: string;
  role: string | null;
  status: string | null;
}

export function Users() {
  const [data, setData] = useState<User[]>([]);
  const [loading, setLoading] = useState(false);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [limit] = useState(10);
  const [nameFilter, setNameFilter] = useState('');
  const [emailFilter, setEmailFilter] = useState('');
  const [roleFilter, setRoleFilter] = useState('');
  const { isAuthenticated } = useAuth();

  const [isModalOpen, setIsModalOpen] = useState(false);
  const [editingUser, setEditingUser] = useState<User | null>(null);
  const [form] = Form.useForm();

  const handleEdit = (user: User) => {
    setEditingUser(user);
    form.setFieldsValue(user);
    setIsModalOpen(true);
  };

  const handleDelete = async (id: string) => {
    try {
      await api.delete(`/companies/users/${id}`);
      message.success('User deleted successfully');
      fetchUsers();
    } catch (error) {
      console.error('Delete user error', error);
      message.error('Failed to delete user');
    }
  };

  const handleCreate = () => {
    setEditingUser(null);
    form.resetFields();
    setIsModalOpen(true);
  };

  const columns: ColumnsType<User> = [
    {
      title: 'Email',
      dataIndex: 'email',
      key: 'email',
      render: (text) => (
        <Text strong style={{ color: '#111827' }}>
          {text}
        </Text>
      ),
    },
    {
      title: 'First Name',
      dataIndex: 'first_name',
      key: 'first_name',
    },
    {
      title: 'Last Name',
      dataIndex: 'last_name',
      key: 'last_name',
    },
    {
      title: 'Phone',
      dataIndex: 'phone',
      key: 'phone',
      render: (text) => text || '—',
    },
    {
      title: 'Role',
      dataIndex: 'role',
      key: 'role',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '14px' }}>
          {text || '—'}
        </Text>
      ),
    },
    {
      title: 'Status',
      dataIndex: 'status',
      key: 'status',
      render: (text) => (
        <Text type='secondary' style={{ fontSize: '14px' }}>
          {text || '—'}
        </Text>
      ),
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

  const fetchUsers = async () => {
    if (!isAuthenticated) return;
    setLoading(true);
    try {
      const response = await api.get('/companies/users', {
        params: {
          name: nameFilter || undefined,
          email: emailFilter || undefined,
          role: roleFilter || undefined,
          page,
          limit,
        },
      });
      setData(response.data.items || []);
      setTotal(response.data.total || 0);
    } catch (error) {
      console.error('Fetch users error', error);
      message.error('Failed to load users');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchUsers();
  }, [page, nameFilter, emailFilter, roleFilter, isAuthenticated]);

  const handleModalOk = async () => {
    try {
      const values = await form.validateFields();
      if (editingUser) {
        await api.put(`/companies/users/${editingUser.id}`, values);
        message.success('User updated successfully');
      } else {
        await api.post('/companies/users', values);
        message.success('User created successfully');
      }
      setIsModalOpen(false);
      fetchUsers();
    } catch (error) {
      console.error('Save user error', error);
      message.error('Failed to save user');
    }
  };

  const handleModalCancel = () => {
    setIsModalOpen(false);
    setEditingUser(null);
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
          Users
        </Title>
        <Text type='secondary'>Manage your application users</Text>
      </div>

      <Card>
        <Row gutter={[16, 16]} style={{ marginBottom: 16 }}>
          <Col xs={24} md={6}>
            <Input.Search
              placeholder='Search by name...'
              onSearch={setNameFilter}
              allowClear
            />
          </Col>
          <Col xs={24} md={6}>
            <Input.Search
              placeholder='Search by email...'
              onSearch={setEmailFilter}
              allowClear
            />
          </Col>
          <Col xs={24} md={6}>
            <Select
              placeholder='Filter by role'
              style={{ width: '100%' }}
              allowClear
              onChange={setRoleFilter}
              options={[
                { value: 'admin', label: 'Admin' },
                { value: 'user', label: 'User' },
              ]}
            />
          </Col>
          <Col xs={24} md={6} style={{ textAlign: 'right' }}>
            <Button type='primary' onClick={handleCreate}>
              Add User
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
        title={editingUser ? 'Edit User' : 'Add User'}
        open={isModalOpen}
        onOk={handleModalOk}
        onCancel={handleModalCancel}
        width={600}
      >
        <Form form={form} layout='vertical' style={{ marginTop: 16 }}>
          <Row gutter={16}>
            <Col span={12}>
              <Form.Item
                name='first_name'
                label='First Name'
                rules={[{ required: true, message: 'Please enter first name' }]}
              >
                <Input placeholder='First name' />
              </Form.Item>
            </Col>
            <Col span={12}>
              <Form.Item
                name='last_name'
                label='Last Name'
                rules={[{ required: true, message: 'Please enter last name' }]}
              >
                <Input placeholder='Last name' />
              </Form.Item>
            </Col>
          </Row>
          <Form.Item
            name='email'
            label='Email'
            rules={[
              { required: true, message: 'Please enter email' },
              { type: 'email', message: 'Please enter a valid email' },
            ]}
          >
            <Input placeholder='email@example.com' />
          </Form.Item>
          <Form.Item name='phone' label='Phone'>
            <Input placeholder='Phone number (optional)' />
          </Form.Item>
          <Form.Item name='role' label='Role'>
            <Select placeholder='Select role'>
              <Select.Option value='admin'>Admin</Select.Option>
              <Select.Option value='user'>User</Select.Option>
            </Select>
          </Form.Item>
          <Form.Item name='status' label='Status'>
            <Select placeholder='Select status'>
              <Select.Option value='active'>Active</Select.Option>
              <Select.Option value='inactive'>Inactive</Select.Option>
            </Select>
          </Form.Item>
          {!editingUser && (
            <Form.Item
              name='password'
              label='Password'
              rules={[{ required: true, message: 'Please enter password' }]}
            >
              <Input.Password placeholder='Password' />
            </Form.Item>
          )}
        </Form>
      </Modal>
    </>
  );
}
