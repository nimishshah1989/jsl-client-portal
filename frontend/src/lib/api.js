/**
 * API fetch wrapper for the JSL Client Portal.
 * Prepends /api, includes credentials for httpOnly cookies,
 * handles 401 redirects and error extraction.
 */

const API_BASE = '/api';

function getCsrfToken() {
  if (typeof document === 'undefined') return null;
  const match = document.cookie.match(/(?:^|;\s*)csrf_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

export class ApiError extends Error {
  constructor(message, status, data) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.data = data;
  }
}

/**
 * Fetch a CSRF token from the backend so the cookie is set before the
 * first state-changing request. Used by the login flow (H1: CSRF default-deny
 * means /api/auth/login itself requires a CSRF token).
 */
export async function ensureCsrfToken() {
  if (typeof document === 'undefined') return null;
  if (getCsrfToken()) return getCsrfToken();
  try {
    const res = await fetch(`${API_BASE}/auth/csrf`, {
      method: 'GET',
      credentials: 'include',
    });
    if (!res.ok) return null;
    const data = await res.json().catch(() => null);
    return data?.csrf_token || getCsrfToken();
  } catch {
    return null;
  }
}

export async function apiFetch(url, options = {}) {
  const fullUrl = `${API_BASE}${url}`;

  const csrfHeaders = {};
  const method = (options.method || 'GET').toUpperCase();
  if (method !== 'GET' && method !== 'HEAD' && method !== 'OPTIONS') {
    // H1: CSRF default-deny — every unsafe-method request needs a token,
    // including unauthenticated calls like /auth/login. If the cookie isn't
    // present yet, fetch one transparently before sending the request.
    let csrf = getCsrfToken();
    if (!csrf) {
      csrf = await ensureCsrfToken();
    }
    if (csrf) csrfHeaders['X-CSRF-Token'] = csrf;
  }

  const config = {
    credentials: 'include',
    headers: {
      'Content-Type': 'application/json',
      ...csrfHeaders,
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
    let detail = 'Unauthorized';
    try {
      const body = await response.json();
      detail = body.detail || detail;
    } catch {
      // no JSON body
    }
    if (
      typeof window !== 'undefined' &&
      !url.includes('/auth/login') &&
      !url.includes('/auth/me') &&
      !window.location.pathname.startsWith('/login')
    ) {
      window.location.href = '/login';
    }
    throw new ApiError(detail, 401, null);
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
