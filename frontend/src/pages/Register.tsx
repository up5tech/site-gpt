import { App, Button, Card, Form, Input, Typography } from 'antd';
import { useEffect, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type { PublicPlan, RegisterRequest } from '../types/api';
import {
  getApiErrorMessage,
  getPlans,
  login as requestLogin,
  register as requestRegister,
} from '../utils/api';
import { useDocumentTitle } from '../utils/useDocumentTitle';

const { Title, Text } = Typography;

/**
 * Plan-aware registration (V5-12).
 *
 * The `?plan=` value is a *display choice*, never an entitlement: it is matched
 * against the public catalog only so the page can say which plan the visitor
 * picked, and it is never sent to `POST /api/register`. An unknown or stale
 * code therefore cannot upgrade anything — it is simply ignored. Paid checkout
 * (Wave 2) is what starts a subscription, and only a verified Stripe webhook
 * ever changes plan state.
 */
export function Register() {
  useDocumentTitle('Create account — Site GPT');
  const { message } = App.useApp();
  const [loading, setLoading] = useState(false);
  const [params] = useSearchParams();
  const [selectedPlan, setSelectedPlan] = useState<PublicPlan | null>(null);
  const [planNotice, setPlanNotice] = useState<string | null>(null);
  const navigate = useNavigate();
  const { isAuthenticated, login } = useAuth();
  const requestedPlan = (params.get('plan') ?? '').trim();

  useEffect(() => {
    if (!requestedPlan) {
      setSelectedPlan(null);
      setPlanNotice(null);
      return;
    }
    let cancelled = false;
    getPlans()
      .then((response) => {
        if (cancelled) return;
        const match = (response.data.plans ?? []).find(
          (plan) => plan.code.toLowerCase() === requestedPlan.toLowerCase(),
        );
        if (match) {
          setSelectedPlan(match);
          setPlanNotice(null);
        } else {
          setSelectedPlan(null);
          setPlanNotice(
            'The plan you selected is no longer available. You can still create a standard account.',
          );
        }
      })
      .catch(() => {
        if (cancelled) return;
        setSelectedPlan(null);
        setPlanNotice(
          'We could not load the selected plan. You can still create a standard account.',
        );
      });
    return () => {
      cancelled = true;
    };
  }, [requestedPlan]);

  if (isAuthenticated) {
    navigate('/app', { replace: true });
    return null;
  }

  const onFinish = async (values: RegisterRequest) => {
    setLoading(true);
    try {
      await requestRegister(values);
      // Sign the new admin straight in so the funnel ends in the console rather
      // than on a login form. Any failure here falls back to the login page.
      try {
        const response = await requestLogin(values.email, values.password);
        login(response.data.access_token);
        message.success('Registration successful!');
        navigate('/app', { replace: true });
      } catch {
        message.success('Registration successful! Please sign in.');
        navigate('/login', { replace: true });
      }
    } catch (error) {
      message.error(getApiErrorMessage(error, 'Registration failed'));
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className='marketing-form'>
      <Title level={1}>Create account</Title>
      <Text className='marketing-form-intro'>
        Start with your company account. You can change plans later.
      </Text>

      {selectedPlan && (
        <div className='marketing-selected-plan'>
          Selected plan: <strong>{selectedPlan.name}</strong> —{' '}
          {selectedPlan.description}
        </div>
      )}
      {planNotice && (
        <div className='marketing-selected-plan' role='status'>
          {planNotice}
        </div>
      )}

      <Card>
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
