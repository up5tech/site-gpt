import { App as AntdApp } from 'antd';
import { Route, Routes } from 'react-router-dom';
import './App.less';
import { LayoutComponent } from './components/Layout';
import { ProtectedRoute } from './components/ProtectedRoute';
import AuthProvider from './context/AuthContext';
import { ChatProvider } from './context/ChatContext';
import { Dashboard } from './pages/Dashboard';
import { ExtraDocuments } from './pages/ExtraDocuments';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Settings } from './pages/Settings';
import { Users } from './pages/Users';
import { WebsiteDetail } from './pages/WebsiteDetail';
import { Websites } from './pages/Websites';
import { Playground } from './pages/Playground';

function App() {
  return (
    <AntdApp>
      <AuthProvider>
        <ChatProvider>
          <LayoutComponent>
            <Routes>
              <Route
                path='/'
                element={
                  <ProtectedRoute>
                    <Dashboard />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/websites'
                element={
                  <ProtectedRoute>
                    <Websites />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/websites/:id'
                element={
                  <ProtectedRoute>
                    <WebsiteDetail />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/playground'
                element={
                  <ProtectedRoute>
                    <Playground />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/users'
                element={
                  <ProtectedRoute>
                    <Users />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/documents'
                element={
                  <ProtectedRoute>
                    <ExtraDocuments />
                  </ProtectedRoute>
                }
              />
              <Route
                path='/settings'
                element={
                  <ProtectedRoute>
                    <Settings />
                  </ProtectedRoute>
                }
              />
              <Route path='/register' element={<Register />} />
              <Route path='/login' element={<Login />} />
            </Routes>
          </LayoutComponent>
        </ChatProvider>
      </AuthProvider>
    </AntdApp>
  );
}

export default App;
