import { App as AntdApp } from 'antd';
import { Route, Routes } from 'react-router-dom';
import './App.less';
import { LayoutComponent } from './components/Layout';
import AuthProvider from './context/AuthContext';
import { ChatProvider } from './context/ChatContext';
import { Dashboard } from './pages/Dashboard';
import { ExtraDocuments } from './pages/ExtraDocuments';
import { Login } from './pages/Login';
import { Register } from './pages/Register';
import { Users } from './pages/Users';
import { WebsiteDetail } from './pages/WebsiteDetail';
import { Websites } from './pages/Websites';

function App() {
  return (
    <AntdApp>
      <AuthProvider>
        <ChatProvider>
          <LayoutComponent>
            <Routes>
              <Route path='/' element={<Dashboard />} />
              <Route path='/websites' element={<Websites />} />
              <Route path='/websites/:id' element={<WebsiteDetail />} />
              <Route path='/users' element={<Users />} />
              <Route path='/documents' element={<ExtraDocuments />} />
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
