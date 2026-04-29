import {
  createContext,
  ReactNode,
  useContext,
  useEffect,
  useState,
} from 'react';
import api, { clearAuthToken, getAuthToken, setAuthToken } from '../utils/api';

interface AuthContextType {
  token: string | null;
  user: any | null;
  login: (token: string) => void;
  logout: () => void;
  fetchUser: () => Promise<void>;
  isAuthenticated: boolean;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within AuthProvider');
  }
  return context;
};

interface Props {
  children: ReactNode;
}

export default function AuthProvider({ children }: Props) {
  const [token, setToken] = useState<string | null>(null);
  const [user, setUser] = useState<any | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const savedToken = getAuthToken();
    if (savedToken) {
      setToken(savedToken);
      fetchUser();
    }
    setLoading(false);
  }, []);

  const fetchUser = async () => {
    try {
      const response = await api.get('/users/me');
      setUser(response.data);
    } catch (error) {
      console.error('Failed to fetch user:', error);
      clearAuthToken();
      setToken(null);
      setUser(null);
    }
  };

  const login = (newToken: string) => {
    setAuthToken(newToken);
    setToken(newToken);
    fetchUser();
  };

  const logout = () => {
    clearAuthToken();
    setToken(null);
    setUser(null);
  };

  const value = {
    token,
    user,
    login,
    logout,
    fetchUser,
    isAuthenticated: !!token,
  };

  return (
    <AuthContext.Provider value={value}>
      {!loading && children}
    </AuthContext.Provider>
  );
}
