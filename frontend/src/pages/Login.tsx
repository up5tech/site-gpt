import { Button, Card, Form, Input, Typography, message } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import { login, setAuthToken } from '../utils/api';

const { Title, Text } = Typography;

export function Login() {
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { login: setToken, isAuthenticated } = useAuth();

  if (isAuthenticated) {
    navigate('/');
    return null;
  }

  const onFinish = async (values: { email: string; password: string }) => {
    setLoading(true);
    try {
      const response = await login(values.email, values.password);
      setAuthToken(response.data.access_token);
      setToken(response.data.access_token);
      message.success('Login successful!');
      navigate('/');
    } catch (error: any) {
      message.error(error.response?.data?.detail || 'Login failed');
    } finally {
      setLoading(false);
    }
  };

  return (
    <div
      style={{
        maxWidth: 480,
        margin: '80px auto',
        padding: '0 24px',
      }}
    >
      <Card
        style={{
          boxShadow: '0 8px 24px rgba(0, 0, 0, 0.08)',
          borderRadius: '16px',
        }}
      >
        <div style={{ textAlign: 'center', marginBottom: 32 }}>
          <Title
            level={2}
            style={{
              marginBottom: 8,
              fontWeight: 700,
              letterSpacing: '-0.5px',
            }}
          >
            Welcome back
          </Title>
          <Text type='secondary'>
            Enter your credentials to access your account
          </Text>
        </div>
        <Form
          name='login'
          onFinish={onFinish}
          layout='vertical'
          size='large'
          autoComplete='off'
        >
          <Form.Item
            name='email'
            label='Email'
            rules={[
              { required: true, message: 'Please input email!' },
              { type: 'email', message: 'Please enter valid email!' },
            ]}
          >
            <Input
              placeholder='your@email.com'
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>
          <Form.Item
            name='password'
            label='Password'
            rules={[{ required: true, message: 'Please input password!' }]}
          >
            <Input.Password
              placeholder='Password'
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>
          <Form.Item style={{ marginBottom: 16 }}>
            <Button
              type='primary'
              htmlType='submit'
              loading={loading}
              block
              style={{
                height: '48px',
                fontSize: '16px',
                fontWeight: '600',
                borderRadius: '8px',
              }}
            >
              Sign in
            </Button>
          </Form.Item>
        </Form>
        <div
          style={{
            textAlign: 'center',
            paddingTop: 16,
            borderTop: '1px solid #f0f0f0',
          }}
        >
          <Text type='secondary'>
            Don't have an account?{' '}
            <Link to='/register' style={{ fontWeight: 600 }}>
              Sign up
            </Link>
          </Text>
        </div>
      </Card>
    </div>
  );
}
