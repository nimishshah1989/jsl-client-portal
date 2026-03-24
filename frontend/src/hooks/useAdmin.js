'use client';

import { useState, useCallback } from 'react';
import { apiFetch, apiGet, apiPost } from '@/lib/api';

/**
 * Hook for NAV file upload.
 */
export function useUploadNav() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const upload = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await apiPost('/admin/upload-nav', formData);
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message || 'Upload failed');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { upload, loading, error, result };
}

/**
 * Hook for transaction file upload.
 */
export function useUploadTransactions() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const upload = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await apiPost('/admin/upload-transactions', formData);
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message || 'Upload failed');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { upload, loading, error, result };
}

/**
 * Hook for client list.
 */
export function useClients() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet('/admin/clients');
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to load clients');
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, error, refetch: fetch };
}

/**
 * Hook for creating a single client.
 */
export function useCreateClient() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const create = useCallback(async (clientData) => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiPost('/admin/clients', clientData);
      return result;
    } catch (err) {
      setError(err.message || 'Failed to create client');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { create, loading, error };
}

/**
 * Hook for bulk client creation.
 */
export function useBulkCreate() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [result, setResult] = useState(null);

  const bulkCreate = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await apiPost('/admin/clients/bulk-create', formData);
      setResult(data);
      return data;
    } catch (err) {
      setError(err.message || 'Bulk create failed');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { bulkCreate, loading, error, result };
}

/**
 * Hook for upload log history.
 */
export function useUploadLog() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const fetch = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await apiGet('/admin/upload-log');
      setData(result);
    } catch (err) {
      setError(err.message || 'Failed to load upload log');
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, error, refetch: fetch };
}

/**
 * Hook for triggering risk recomputation.
 */
export function useRecomputeRisk() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const recompute = useCallback(async (clientId = null) => {
    setLoading(true);
    setError(null);
    try {
      const body = clientId ? { client_id: clientId } : {};
      const result = await apiPost('/admin/recompute-risk', body);
      return result;
    } catch (err) {
      setError(err.message || 'Recomputation failed');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { recompute, loading, error };
}

/**
 * Hook for data status (last upload + last data date).
 */
export function useDataStatus() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const fetch = useCallback(async () => {
    setLoading(true);
    try {
      const result = await apiGet('/admin/data-status');
      setData(result);
    } catch {
      // silent
    } finally {
      setLoading(false);
    }
  }, []);

  return { data, loading, refetch: fetch };
}

/**
 * Hook for impersonating a client (view their dashboard).
 */
export function useImpersonate() {
  const [loading, setLoading] = useState(false);

  const impersonate = useCallback(async (clientId) => {
    setLoading(true);
    try {
      const result = await apiPost(`/admin/impersonate/${clientId}`, {});
      return result;
    } catch (err) {
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { impersonate, loading };
}

/**
 * Hook for file upload preview.
 */
export function useUploadPreview() {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [preview, setPreview] = useState(null);

  const getPreview = useCallback(async (file) => {
    setLoading(true);
    setError(null);
    setPreview(null);
    try {
      const formData = new FormData();
      formData.append('file', file);
      const data = await apiPost('/admin/upload-preview', formData);
      setPreview(data);
      return data;
    } catch (err) {
      setError(err.message || 'Preview failed');
      throw err;
    } finally {
      setLoading(false);
    }
  }, []);

  return { getPreview, loading, error, preview };
}
