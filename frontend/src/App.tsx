import { App as AntdApp, Button, Result } from 'antd';
import {
  Link,
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';
import './App.less';
import { LayoutComponent } from './components/Layout';
import { PublicLayout } from './components/PublicLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import AuthProvider, { useAuth } from './context/AuthContext';
import { ChatProvider } from './context/ChatContext';
import { Contacts } from './pages/Contacts';
import { Dashboard } from './pages/Dashboard';
import { ExtraDocuments } from './pages/ExtraDocuments';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { Pricing } from './pages/Pricing';
import { Register } from './pages/Register';
import { Analytics } from './pages/Analytics';
import { Billing } from './pages/Billing';
import { Handoffs } from './pages/Handoffs';
import { Inbox } from './pages/Inbox';
import { Integrations } from './pages/Integrations';
import { Settings } from './pages/Settings';
import { Training } from './pages/Training';
import { Users } from './pages/Users';
import { WebsiteDetail } from './pages/WebsiteDetail';
import { Websites } from './pages/Websites';
import { Playground } from './pages/Playground';

/**
 * Console pages keep their old top-level paths as redirects into `/app`
 * (V5-10, decision D1). A bookmark, a link inside an email or a widget admin
 * deep link therefore still lands on the same page after the dashboard moved,
 * and `ProtectedRoute` still remembers where the visitor was going.
 */
const CONSOLE_PATHS = [
  'websites',
  'websites/:id',
  'playground',
  'contacts',
  'users',
  'documents',
  'integrations',
  'analytics',
  'handoffs',
  'inbox',
  'training',
  'settings',
  'billing',
];

/**
 * The console's own 404, rendered inside the admin shell (V5-10). A mistyped
 * `/app/...` URL keeps its path so the typo is visible, and the visitor keeps
 * the console navigation instead of being thrown out to the marketing site.
 */
function ConsoleNotFound() {
  const location = useLocation();
  return (
    <Result
      status='404'
      title='Page not found'
      subTitle={`${location.pathname} is not a console page.`}
      extra={
        <Link to='/app'>
          <Button type='primary'>Back to dashboard</Button>
        </Link>
      }
    />
  );
}

/**
 * The global catch-all. A signed-in visitor who mistypes a console URL is sent
 * into the console (keeping the path, so `/app/<typo>` shows the console's 404)
 * rather than being silently dropped on the marketing landing page; an
 * anonymous visitor still lands on the public home page.
 */
function NotFoundRedirect() {
  const { isAuthenticated } = useAuth();
  const location = useLocation();
  if (isAuthenticated) {
    return (
      <Navigate
        to={`/app${location.pathname}${location.search}${location.hash}`}
        replace
      />
    );
  }
  return <Navigate to='/' replace />;
}

function LegacyConsoleRedirect() {
  const location = useLocation();
  return (
    <Navigate
      to={`/app${location.pathname}${location.search}${location.hash}`}
      replace
    />
  );
}

function App() {
  return (
    <AntdApp>
      <AuthProvider>
        <ChatProvider>
          <Routes>
            {/* Public marketing shell (V5 F1): readable without auth. */}
            <Route element={<PublicLayout />}>
              <Route path='/' element={<Landing />} />
              <Route path='/pricing' element={<Pricing />} />
              <Route path='/register' element={<Register />} />
              <Route path='/login' element={<Login />} />
            </Route>

            {/* Authenticated console. */}
            <Route
              path='/app'
              element={
                <ProtectedRoute>
                  <LayoutComponent />
                </ProtectedRoute>
              }
            >
              <Route index element={<Dashboard />} />
              <Route path='websites' element={<Websites />} />
              <Route path='websites/:id' element={<WebsiteDetail />} />
              <Route path='playground' element={<Playground />} />
              <Route path='contacts' element={<Contacts />} />
              <Route path='users' element={<Users />} />
              <Route path='documents' element={<ExtraDocuments />} />
              <Route path='integrations' element={<Integrations />} />
              <Route path='analytics' element={<Analytics />} />
              <Route path='handoffs' element={<Handoffs />} />
              <Route path='inbox' element={<Inbox />} />
              <Route path='training' element={<Training />} />
              <Route path='settings' element={<Settings />} />
              <Route path='billing' element={<Billing />} />
              {/* Unknown `/app/...` paths stay in the console shell. */}
              <Route path='*' element={<ConsoleNotFound />} />
            </Route>

            {/* Old console paths, kept working. */}
            {CONSOLE_PATHS.map((path) => (
              <Route
                key={path}
                path={`/${path}`}
                element={<LegacyConsoleRedirect />}
              />
            ))}

            <Route path='*' element={<NotFoundRedirect />} />
          </Routes>
        </ChatProvider>
      </AuthProvider>
    </AntdApp>
  );
}

export default App;
