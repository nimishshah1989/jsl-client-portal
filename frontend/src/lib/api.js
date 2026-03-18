/**
 * API fetch wrapper for the JSL Client Portal.
 * Prepends /api, includes credentials for httpOnly cookies,
 * handles 401 redirects and error extraction.
 */

const API_BASE = '/api';

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

export async function apiFetch(url, options = {}) {
  const fullUrl = `${API_BASE}${url}`;

  const config = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...options.headers,
    },
    ...options,
  };

  // Remove Content-Type for FormData (file uploads)
  if (config.body instanceof FormData) {
    delete config.headers['Content-Type'];
  }

  const response = await fetch(fullUrl, config);

  if (response.status === 401) {
    if (
      typeof window !== 'undefined' &&
      !url.includes('/auth/login') &&
      !url.includes('/auth/me') &&
      !window.location.pathname.startsWith('/login')
    ) {
      window.location.href = '/login';
    }
    throw new ApiError('Unauthorized', 401, null);
  }

  if (!response.ok) {
    let errorData = null;
    let errorMessage = `Request failed with status ${response.status}`;

    try {
      errorData = await response.json();
      errorMessage = errorData.detail || errorData.message || errorMessage;
    } catch {
      // Response body is not JSON
    }

    throw new ApiError(errorMessage, response.status, errorData);
  }

  // Handle 204 No Content
  if (response.status === 204) {
    return null;
  }

  return response.json();
}

export function apiGet(url) {
  return apiFetch(url, { method: 'GET' });
}

export function apiPost(url, body) {
  return apiFetch(url, {
    method: 'POST',
    body: body instanceof FormData ? body : JSON.stringify(body),
  });
}

export function apiPut(url, body) {
  return apiFetch(url, {
    method: 'PUT',
    body: JSON.stringify(body),
  });
}

export function apiDelete(url) {
  return apiFetch(url, { method: 'DELETE' });
}
