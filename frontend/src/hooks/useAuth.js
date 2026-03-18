'use client';

import { useState, useEffect, useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { apiFetch } from '@/lib/api';

/**
 * Authentication hook for JSL Client Portal.
 * Manages user state, login, logout, and auth checks.
 */
export function useAuth() {
  const router = useRouter();
  const [user, setUser] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const checkAuth = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiFetch('/auth/me');
      setUser(data);
      setError(null);
      return data;
    } catch (err) {
      setUser(null);
      if (err.status !== 401) {
        setError(err.message);
      }
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  // Don't auto-check on mount — dashboard layout calls checkAuth explicitly.
  // This prevents 401 loops on the login page.

  const login = useCallback(async (username, password) => {
    setLoading(true);
    setError(null);
    try {
      const data = await apiFetch('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      setUser(data);
      // Use full page navigation to ensure the cookie is picked up
      window.location.href = data.is_admin ? '/admin' : '/dashboard';
      return data;
    } catch (err) {
      setError(err.message || 'Login failed. Please check your credentials.');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await apiFetch('/auth/logout', { method: 'POST' });
    } catch {
      // Logout even if API fails
    } finally {
      setUser(null);
      router.push('/login');
    }
  }, [router]);

  const changePassword = useCallback(async (oldPassword, newPassword) => {
    setError(null);
    try {
      await apiFetch('/auth/change-password', {
        method: 'POST',
        body: JSON.stringify({
          old_password: oldPassword,
          new_password: newPassword,
        }),
      });
      return true;
    } catch (err) {
      setError(err.message || 'Password change failed.');
      throw err;
    }
  }, []);

  return {
    user,
    loading,
    error,
    isAuthenticated: !!user,
    isAdmin: user?.is_admin || false,
    login,
    logout,
    checkAuth,
    changePassword,
  };
}
