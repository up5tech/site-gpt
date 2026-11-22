import { App as AntdApp } from 'antd';
import {
  Navigate,
  Route,
  Routes,
  useLocation,
} from 'react-router-dom';
import './App.less';
import { LayoutComponent } from './components/Layout';
import { PublicLayout } from './components/PublicLayout';
import { ProtectedRoute } from './components/ProtectedRoute';
import AuthProvider from './context/AuthContext';
import { ChatProvider } from './context/ChatContext';
import { Contacts } from './pages/Contacts';
import { Dashboard } from './pages/Dashboard';
import { ExtraDocuments } from './pages/ExtraDocuments';
import { Landing } from './pages/Landing';
import { Login } from './pages/Login';
import { Pricing } from './pages/Pricing';
import { Register } from './pages/Register';
import { Analytics } from './pages/Analytics';
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
];

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
            </Route>

            {/* Old console paths, kept working. */}
            {CONSOLE_PATHS.map((path) => (
              <Route
                key={path}
                path={`/${path}`}
                element={<LegacyConsoleRedirect />}
              />
            ))}

            <Route path='*' element={<Navigate to='/' replace />} />
          </Routes>
        </ChatProvider>
      </AuthProvider>
    </AntdApp>
  );
}

export default App;
