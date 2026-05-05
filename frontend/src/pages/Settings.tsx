import {
  CopyOutlined,
  SaveOutlined,
  SettingOutlined,
  UserOutlined,
} from '@ant-design/icons';
import {
  Alert,
  Button,
  Card,
  Col,
  Form,
  Input,
  Row,
  Select,
  Space,
  Tabs,
  Typography,
} from 'antd';
import useApp from 'antd/es/app/useApp';
import { useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Website } from '../types/api';
import api from '../utils/api';

const { Title, Text, Paragraph } = Typography;

export function Settings() {
  const { user, fetchUser } = useAuth();
  const { message } = useApp();
  const [profileForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [websites, setWebsites] = useState<Website[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string>('');

  useEffect(() => {
    if (user) {
      profileForm.setFieldsValue({
        first_name: user.first_name,
        last_name: user.last_name,
        email: user.email,
        phone: user.phone,
      });
    }
    fetchWebsites();
  }, [user]);

  const fetchWebsites = async () => {
    try {
      const response = await api.get('/websites');
      const items = response.data.items || [];
      setWebsites(items);
      if (items.length > 0 && !selectedWebsiteId) {
        setSelectedWebsiteId(items[0].id);
      }
    } catch (error) {
      console.error('Fetch websites error', error);
    }
  };

  const handleProfileSubmit = async (values: any) => {
    setLoading(true);
    try {
      await api.put('/users/me', values);
      message.success('Profile updated successfully');
      await fetchUser();
    } catch (error) {
      console.error('Update profile error', error);
      message.error('Failed to update profile');
    } finally {
      setLoading(false);
    }
  };

  const getWidgetScript = () => {
    const apiUrl = import.meta.env.VITE_BACKEND_URL || window.location.origin;
    const cleanApiUrl = apiUrl.replace(/\/+$/, '');

    return `<!-- Site GPT Chat Widget -->
<script>
  window.ChatWidgetConfig = {
    website_id: '${selectedWebsiteId}',
    apiUrl: '${cleanApiUrl}/api/chat',
    botName: 'Assistant',
    theme: {
      primaryColor: '#4c74afff',
      backgroundColor: '#ffffff',
    }
  };
</script>
<script src="${cleanApiUrl}/scripts/widget.js" async></script>`;
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    message.success('Copied to clipboard');
  };

  const items = [
    {
      key: 'profile',
      label: (
        <span>
          <UserOutlined />
          Profile
        </span>
      ),
      children: (
        <Card variant='borderless' className='premium-card'>
          <Title level={4}>Profile Information</Title>
          <Paragraph type='secondary'>
            Update your personal information and contact details.
          </Paragraph>
          <Form
            form={profileForm}
            layout='vertical'
            onFinish={handleProfileSubmit}
            style={{ maxWidth: 600, marginTop: 24 }}
          >
            <Row gutter={16}>
              <Col span={12}>
                <Form.Item
                  name='first_name'
                  label='First Name'
                  rules={[
                    { required: true, message: 'Please enter first name' },
                  ]}
                >
                  <Input placeholder='John' />
                </Form.Item>
              </Col>
              <Col span={12}>
                <Form.Item
                  name='last_name'
                  label='Last Name'
                  rules={[
                    { required: true, message: 'Please enter last name' },
                  ]}
                >
                  <Input placeholder='Doe' />
                </Form.Item>
              </Col>
            </Row>
            <Form.Item
              name='email'
              label='Email Address'
              rules={[
                { required: true, message: 'Please enter email' },
                { type: 'email', message: 'Please enter a valid email' },
              ]}
            >
              <Input placeholder='john.doe@example.com' disabled />
            </Form.Item>
            <Form.Item name='phone' label='Phone Number'>
              <Input placeholder='+1 (555) 000-0000' />
            </Form.Item>
            <Form.Item>
              <Button
                type='primary'
                htmlType='submit'
                icon={<SaveOutlined />}
                loading={loading}
              >
                Save Changes
              </Button>
            </Form.Item>
          </Form>
        </Card>
      ),
    },
    {
      key: 'widget',
      label: (
        <span>
          <SettingOutlined />
          Widget
        </span>
      ),
      children: (
        <Card variant='borderless' className='premium-card'>
          <Title level={4}>Chat Widget Integration</Title>
          <Paragraph type='secondary'>
            Copy and paste this script into your website's HTML (usually before
            the &lt;/body&gt; tag) to enable the chat box.
          </Paragraph>

          <Space direction='vertical' size='large' style={{ width: '100%' }}>
            <div style={{ maxWidth: 400 }}>
              <Text strong>Select Website</Text>
              <Select
                style={{ width: '100%', marginTop: 8 }}
                placeholder='Select a website'
                value={selectedWebsiteId}
                onChange={setSelectedWebsiteId}
                options={websites.map((w) => ({ label: w.name, value: w.id }))}
              />
            </div>

            {selectedWebsiteId ? (
              <div style={{ marginTop: 16 }}>
                <div
                  style={{
                    display: 'flex',
                    justifyContent: 'space-between',
                    alignItems: 'center',
                    marginBottom: 8,
                  }}
                >
                  <Text strong>Installation Script</Text>
                  <Button
                    type='link'
                    icon={<CopyOutlined />}
                    onClick={() => copyToClipboard(getWidgetScript())}
                  >
                    Copy Code
                  </Button>
                </div>
                <Input.TextArea
                  value={getWidgetScript()}
                  rows={12}
                  readOnly
                  style={{
                    fontFamily: 'monospace',
                    backgroundColor: '#f8f9fa',
                    fontSize: '13px',
                  }}
                />
                <Alert
                  message='Tip'
                  description='You can customize the widget theme and behavior by modifying the ChatWidgetConfig object in the script.'
                  type='info'
                  showIcon
                  style={{ marginTop: 16 }}
                />
              </div>
            ) : (
              <Alert
                message='No Websites Found'
                description='Please add a website first to generate the widget script.'
                type='warning'
                showIcon
              />
            )}
          </Space>
        </Card>
      ),
    },
  ];

  return (
    <div>
      <div style={{ marginBottom: 24 }}>
        <Title level={2}>Settings</Title>
        <Text type='secondary'>
          Manage your account settings and website integrations.
        </Text>
      </div>

      <Tabs
        defaultActiveKey='profile'
        items={items}
        type='card'
        className='premium-tabs'
      />
    </div>
  );
}
