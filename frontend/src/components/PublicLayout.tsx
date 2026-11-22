import { Alert, Button } from 'antd';
import { useEffect, useState } from 'react';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
import type { PublicConfig } from '../types/api';
import { getPublicConfig } from '../utils/api';
import './PublicLayout.less';

const NAV = [
  { to: '/', label: 'Product' },
  { to: '/pricing', label: 'Pricing' },
];

/**
 * The public marketing shell (V5 F1, task V5-10).
 *
 * Deliberately separate from `LayoutComponent`: an anonymous visitor must never
 * inherit the admin navigation, and the console's menu is built from
 * authenticated-only state. Everything here renders without a JWT and without
 * any API call beyond the optional pricing read a page makes itself.
 */
export function PublicLayout() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  const year = new Date().getFullYear();
  // Operator-set display values only (V5-43); a failed read simply hides them.
  const [config, setConfig] = useState<PublicConfig | null>(null);

  useEffect(() => {
    let cancelled = false;
    getPublicConfig()
      .then((response) => {
        if (!cancelled) setConfig(response.data);
      })
      .catch(() => {
        if (!cancelled) setConfig(null);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className='marketing'>
      <a className='marketing-skip-link' href='#main'>
        Skip to content
      </a>
      {config?.status_message && (
        <div className='marketing-banner' role='status'>
          <Alert
            type='info'
            showIcon
            style={{ marginTop: 16 }}
            message={config.status_message}
          />
        </div>
      )}
      <header className='marketing-header'>
        <Link to='/' className='marketing-brand' aria-label='Site GPT home'>
          Site GPT
        </Link>
        <nav className='marketing-nav' aria-label='Main'>
          {NAV.map((item) => (
            <Link
              key={item.to}
              to={item.to}
              className='marketing-nav-link'
              aria-current={location.pathname === item.to ? 'page' : undefined}
            >
              {item.label}
            </Link>
          ))}
        </nav>
        <div className='marketing-actions'>
          {isAuthenticated ? (
            <Link to='/app'>
              <Button type='primary'>Go to app</Button>
            </Link>
          ) : (
            <>
              <Link to='/login' className='marketing-nav-link'>
                Sign in
              </Link>
              <Link to='/register'>
                <Button type='primary'>Get started</Button>
              </Link>
            </>
          )}
        </div>
      </header>

      <main id='main' className='marketing-main'>
        <Outlet />
      </main>

      <footer className='marketing-footer'>
        <span>
          © {year} Site GPT
          {config?.support_email && (
            <>
              {' · '}
              <a href={`mailto:${config.support_email}`}>
                {config.support_email}
              </a>
            </>
          )}
        </span>
        <nav className='marketing-footer-nav' aria-label='Footer'>
          <Link to='/'>Product</Link>
          <Link to='/pricing'>Pricing</Link>
          {isAuthenticated ? (
            <Link to='/app'>Console</Link>
          ) : (
            <>
              <Link to='/login'>Sign in</Link>
              <Link to='/register'>Create account</Link>
            </>
          )}
        </nav>
      </footer>
    </div>
  );
}
