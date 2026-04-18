import { App, Button, Card, Form, Input, Typography } from 'antd';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type { RegisterRequest } from '../types/api';
import api from '../utils/api';

const { Title, Text } = Typography;

export function Register() {
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const navigate = useNavigate();
  const { isAuthenticated } = useAuth();

  if (isAuthenticated) {
    navigate('/');
    return null;
  }

  const onFinish = async (values: RegisterRequest) => {
    setLoading(true);
    try {
      await api.post('/register', values);
      message.success('Registration successful! Please login.');
      navigate('/login');
    } catch (error: any) {
      message.error(error.response?.data?.detail || 'Registration failed');
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
            Create account
          </Title>
          <Text type='secondary'>Get started with your free account today</Text>
        </div>
        <Form
          name='register'
          onFinish={onFinish}
          layout='vertical'
          size='large'
          autoComplete='off'
        >
          <Form.Item
            name='company_name'
            label='Company Name'
            rules={[{ required: true, message: 'Please input company name!' }]}
          >
            <Input
              placeholder='Your company name'
              style={{ borderRadius: '8px' }}
            />
          </Form.Item>
          <Form.Item
            name='first_name'
            label='First Name'
            rules={[{ required: true, message: 'Please input first name!' }]}
          >
            <Input placeholder='First name' style={{ borderRadius: '8px' }} />
          </Form.Item>
          <Form.Item
            name='last_name'
            label='Last Name'
            rules={[{ required: true, message: 'Please input last name!' }]}
          >
            <Input placeholder='Last name' style={{ borderRadius: '8px' }} />
          </Form.Item>
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
              Create account
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
            Already have an account?{' '}
            <Link to='/login' style={{ fontWeight: 600 }}>
              Sign in
            </Link>
          </Text>
        </div>
      </Card>
    </div>
  );
}
