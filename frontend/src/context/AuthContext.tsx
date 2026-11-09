import React, { createContext, useContext, useEffect, useState } from 'react';
import { api } from '../services/api';
import { User } from '../types';

interface AuthContextType {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  login: (email: string, password: string) => Promise<void>;
  register: (email: string, password: string, fullName?: string) => Promise<void>;
  logout: () => void;
}

const AuthContext = createContext<AuthContextType | undefined>(undefined);

export const AuthProvider: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const [user, setUser] = useState<User | null>(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const token = localStorage.getItem('katha_access_token');
    if (!token) {
      setIsLoading(false);
      return;
    }

    api
      .getMe()
      .then((userData) => {
        setUser(userData);
      })
      .catch(() => {
        localStorage.removeItem('katha_access_token');
        localStorage.removeItem('katha_refresh_token');
        setUser(null);
      })
      .finally(() => {
        setIsLoading(false);
      });
  }, []);

  const login = async (email: string, password: string) => {
    const res = await api.login(email, password);
    localStorage.setItem('katha_access_token', res.access_token);
    localStorage.setItem('katha_refresh_token', res.refresh_token);
    setUser(res.user);
  };

  const register = async (email: string, password: string, fullName?: string) => {
    const res = await api.register(email, password, fullName);
    localStorage.setItem('katha_access_token', res.access_token);
    localStorage.setItem('katha_refresh_token', res.refresh_token);
    setUser(res.user);
  };

  const logout = () => {
    localStorage.removeItem('katha_access_token');
    localStorage.removeItem('katha_refresh_token');
    setUser(null);
    window.location.href = '/login';
  };

  return (
    <AuthContext.Provider
      value={{
        user,
        isAuthenticated: !!user,
        isLoading,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
};

