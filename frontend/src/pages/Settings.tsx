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
  ColorPicker,
  Form,
  Input,
  Row,
  Select,
  Space,
  Tabs,
  Typography,
} from 'antd';
import useApp from 'antd/es/app/useApp';
import { useCallback, useEffect, useState } from 'react';
import { useAuth } from '../context/AuthContext';
import { Website } from '../types/api';
import api from '../utils/api';
import { WidgetPreview } from '../components/WidgetPreview';
import {
  WIDGET_VERSION_PLACEHOLDER,
  buildWidgetSnippet,
} from '../utils/widgetSnippet';

const { Title, Text, Paragraph } = Typography;

const APPEARANCE_KEYS = [
  'assistant_name',
  'widget_header_color',
  'widget_footer_color',
  'widget_position',
  'greeting_message',
  'placeholder_text',
  'suggested_questions',
] as const;

const DEFAULT_APPEARANCE = {
  assistant_name: 'Site GPT',
  widget_header_color: '#4c74af',
  widget_footer_color: '#4c74af',
  widget_position: 'bottom-right',
  greeting_message: 'Hi 👋 How can I help you?',
  placeholder_text: 'Type a message...',
  suggested_questions: '',
};

type ColorLike = {
  toHexString?: () => string;
  toRgbString?: () => string;
  toCss?: () => string;
};

// Normalise a value coming from a ColorPicker (string | Color object) into a CSS color.
function colorToCss(v: unknown): string {
  if (!v) return '';
  if (typeof v === 'string') return v;
  if (typeof v === 'object') {
    const color = v as ColorLike;
    if (typeof color.toHexString === 'function') return color.toHexString();
    if (typeof color.toRgbString === 'function') return color.toRgbString();
    if (typeof color.toCss === 'function') return color.toCss();
  }
  return String(v);
}

const asText = (v: unknown, fallback: string): string =>
  typeof v === 'string' && v.trim() ? v : fallback;

function buildPreview(values: Record<string, unknown>) {
  return {
    assistantName: asText(
      values.assistant_name,
      DEFAULT_APPEARANCE.assistant_name,
    ),
    headerColor:
      colorToCss(values.widget_header_color) ||
      DEFAULT_APPEARANCE.widget_header_color,
    footerColor:
      colorToCss(values.widget_footer_color) ||
      DEFAULT_APPEARANCE.widget_footer_color,
    position: asText(
      values.widget_position,
      DEFAULT_APPEARANCE.widget_position,
    ) as 'bottom-left' | 'bottom-right',
    greetingMessage: asText(
      values.greeting_message,
      DEFAULT_APPEARANCE.greeting_message,
    ),
    placeholderText: asText(
      values.placeholder_text,
      DEFAULT_APPEARANCE.placeholder_text,
    ),
    suggestedQuestions: asText(
      values.suggested_questions,
      DEFAULT_APPEARANCE.suggested_questions,
    ),
  };
}

interface AppearanceFormValues {
  [key: string]: unknown;
  assistant_name?: string;
  widget_header_color?: unknown;
  widget_footer_color?: unknown;
  widget_position?: string;
  greeting_message?: string;
  placeholder_text?: string;
  suggested_questions?: string;
}

interface ProfileFormValues {
  first_name: string;
  last_name: string;
  email: string;
  phone?: string;
}

export function Settings() {
  const { user, fetchUser } = useAuth();
  const { message } = useApp();
  const [profileForm] = Form.useForm();
  const [appearanceForm] = Form.useForm();
  const [loading, setLoading] = useState(false);
  const [appearanceLoading, setAppearanceLoading] = useState(false);
  const [websites, setWebsites] = useState<Website[]>([]);
  const [selectedWebsiteId, setSelectedWebsiteId] = useState<string>('');
  const [preview, setPreview] = useState(buildPreview(DEFAULT_APPEARANCE));
  // Cache-busting token for the install snippet: the API publishes the current
  // widget.js content hash, so re-copying the snippet always gets fresh code.
  const [widgetVersion, setWidgetVersion] = useState('');
  const [widgetVersionState, setWidgetVersionState] = useState<
    'loading' | 'ok' | 'missing'
  >('loading');

  const loadWidgetVersion = useCallback(async () => {
    const apiUrl = import.meta.env.VITE_BACKEND_URL || window.location.origin;
    const cleanApiUrl = apiUrl.replace(/\/+$/, '');
    setWidgetVersionState('loading');

    // Two attempts: a single failed HEAD should not silently produce a snippet
    // that cannot bust the widget cache.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const response = await fetch(`${cleanApiUrl}/widget.js`, {
          method: 'HEAD',
        });
        const version = response.headers.get('x-widget-version');
        if (response.ok && version) {
          setWidgetVersion(version);
          setWidgetVersionState('ok');
          return;
        }
      } catch {
        // fall through to the retry
      }
      await new Promise((resolve) => setTimeout(resolve, 500));
    }

    setWidgetVersion('');
    setWidgetVersionState('missing');
  }, []);

  const fetchAppearance = useCallback(async () => {
    try {
      const response = await api.get('/settings');
      const map: Record<string, string> = {};
      (response.data || []).forEach((s: { key: string; value: string }) => {
        map[s.key] = s.value;
      });
      const values = {
        assistant_name: map.assistant_name || 'Site GPT',
        widget_header_color:
          colorToCss(map.widget_header_color) ||
          DEFAULT_APPEARANCE.widget_header_color,
        widget_footer_color:
          colorToCss(map.widget_footer_color) ||
          DEFAULT_APPEARANCE.widget_footer_color,
        widget_position: map.widget_position || 'bottom-right',
        greeting_message:
          map.greeting_message || 'Hi 👋 How can I help you?',
        placeholder_text: map.placeholder_text || 'Type a message...',
        suggested_questions: map.suggested_questions || '',
      };
      appearanceForm.setFieldsValue(values);
      setPreview(buildPreview(values));
    } catch (error) {
      console.error('Fetch settings error', error);
    }
  }, [appearanceForm]);

  const handleAppearanceSubmit = async (values: AppearanceFormValues) => {
    setAppearanceLoading(true);
    try {
      const payload = APPEARANCE_KEYS.map((key) => ({
        key,
        // ColorPicker yields a Color object, not a string — serialise it to a
        // CSS color so we don't persist the literal "[object Object]".
        value:
          key === 'widget_header_color' || key === 'widget_footer_color'
            ? colorToCss(values[key]) ||
              (key === 'widget_header_color'
                ? DEFAULT_APPEARANCE.widget_header_color
                : DEFAULT_APPEARANCE.widget_footer_color)
            : String(values[key] ?? ''),
      }));
      await api.put('/settings', payload);
      message.success('Appearance updated successfully');
    } catch (error) {
      console.error('Update appearance error', error);
      message.error('Failed to update appearance');
    } finally {
      setAppearanceLoading(false);
    }
  };

  const fetchWebsites = useCallback(async () => {
    try {
      const response = await api.get('/websites');
      const items = response.data.items || [];
      setWebsites(items);
      if (items.length > 0) {
        setSelectedWebsiteId((prev) => prev || items[0].id);
      }
    } catch (error) {
      console.error('Fetch websites error', error);
    }
  }, []);

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
    fetchAppearance();
  }, [user, profileForm, fetchWebsites, fetchAppearance]);

  // Ask the API for the current widget.js hash so the install snippet carries a
  // ?v= token that busts its cache as soon as a new widget is deployed.
  useEffect(() => {
    loadWidgetVersion();
  }, [loadWidgetVersion]);

  const handleProfileSubmit = async (values: ProfileFormValues) => {
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

  const getWidgetScript = () =>
    buildWidgetSnippet({
      websiteId: selectedWebsiteId,
      apiUrl: import.meta.env.VITE_BACKEND_URL || window.location.origin,
      version: widgetVersion,
    });

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
                {widgetVersionState === 'missing' && (
                  <Alert
                    style={{ marginBottom: 8 }}
                    type='warning'
                    showIcon
                    message='Could not read the widget version'
                    description={
                      `The API did not return an X-Widget-Version header, so the snippet below ` +
                      `still contains ${WIDGET_VERSION_PLACEHOLDER}. Sites without a version token ` +
                      `can keep running an old widget.js for up to 5 minutes after a deploy — ` +
                      `replace the placeholder with the X-Widget-Version value from GET /widget.js.`
                    }
                    action={
                      <Button size='small' onClick={loadWidgetVersion}>
                        Retry
                      </Button>
                    }
                  />
                )}
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
    {
      key: 'appearance',
      label: (
        <span>
          <SettingOutlined />
          Appearance
        </span>
      ),
      children: (
        <Card variant='borderless' className='premium-card'>
          <Title level={4}>Widget Appearance</Title>
          <Paragraph type='secondary'>
            Customize how the chat widget looks and behaves on your site. These
            settings are fetched automatically by the widget (no script change
            needed).
          </Paragraph>
          <Row gutter={[24, 24]}>
            <Col xs={24} md={13}>
              <Form
                form={appearanceForm}
                layout='vertical'
                onFinish={handleAppearanceSubmit}
                onValuesChange={(_, all) => setPreview(buildPreview(all))}
                style={{ marginTop: 24 }}
              >
                <Form.Item name='assistant_name' label='Assistant Name'>
                  <Input placeholder='Site GPT' />
                </Form.Item>
                <Row gutter={16}>
                  <Col span={12}>
                    <Form.Item name='widget_header_color' label='Header Color'>
                      <ColorPicker showText />
                    </Form.Item>
                  </Col>
                  <Col span={12}>
                    <Form.Item name='widget_footer_color' label='Footer / Input Color'>
                      <ColorPicker showText />
                    </Form.Item>
                  </Col>
                </Row>
                <Form.Item name='widget_position' label='Position'>
                  <Select
                    options={[
                      { label: 'Bottom right', value: 'bottom-right' },
                      { label: 'Bottom left', value: 'bottom-left' },
                    ]}
                  />
                </Form.Item>
                <Form.Item name='greeting_message' label='Greeting Message'>
                  <Input placeholder='Hi 👋 How can I help you?' />
                </Form.Item>
                <Form.Item name='placeholder_text' label='Input Placeholder'>
                  <Input placeholder='Type a message...' />
                </Form.Item>
                <Form.Item
                  name='suggested_questions'
                  label='Suggested Questions'
                  tooltip='One per line. Shown as quick prompts when the chat opens.'
                >
                  <Input.TextArea
                    rows={3}
                    placeholder={'What are your opening hours?\nHow do I get a refund?'}
                  />
                </Form.Item>
                <Form.Item>
                  <Button
                    type='primary'
                    htmlType='submit'
                    icon={<SaveOutlined />}
                    loading={appearanceLoading}
                  >
                    Save Appearance
                  </Button>
                </Form.Item>
              </Form>
            </Col>
            <Col xs={24} md={11}>
              <div style={{ position: 'sticky', top: 24, marginTop: 24 }}>
                <Text strong>Live Preview</Text>
                <Paragraph type='secondary' style={{ fontSize: 12, marginTop: 2 }}>
                  Updates as you edit the form on the left.
                </Paragraph>
                <WidgetPreview {...preview} />
              </div>
            </Col>
          </Row>
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
