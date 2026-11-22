import { Button } from 'antd';
import { Link, Outlet, useLocation } from 'react-router-dom';
import { useAuth } from '../context/AuthContext';
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

  return (
    <div className='marketing'>
      <a className='marketing-skip-link' href='#main'>
        Skip to content
      </a>
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
        <span>© {year} Site GPT</span>
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
