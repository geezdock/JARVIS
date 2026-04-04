import axios from 'axios';
import { supabase } from './supabase';

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000',
  headers: {
    'Content-Type': 'application/json',
  },
  timeout: 12000,
});

api.interceptors.request.use(
  async (config) => {
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (session?.access_token) {
      config.headers.Authorization = `Bearer ${session.access_token}`;
    }

    return config;
  },
  (error) => Promise.reject(error),
);

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error?.response?.status;
    const detail = error?.response?.data?.detail;
    const message = error?.response?.data?.message;
    const networkError = error?.message;

    let errorMsg = 'Unexpected API error';

    if (status === 401) {
      errorMsg = detail || 'Unauthorized: 401 - Your session has expired or is invalid.';
    } else if (status === 403) {
      errorMsg = detail || 'Forbidden: 403 - You do not have permission to perform this action.';
    } else if (status === 404) {
      errorMsg = detail || 'Not Found: 404 - The requested resource was not found.';
    } else if (status === 500) {
      errorMsg = detail || 'Server Error: 500 - The server encountered an error. Check backend logs.';
    } else if (status) {
      errorMsg = detail || message || `HTTP ${status} Error: ${error?.response?.statusText || 'Unknown'}`;
    } else if (networkError?.includes('timeout')) {
      errorMsg = '408 Timeout: Request took too long. Backend may not be responding.';
    } else if (networkError?.includes('CORS')) {
      errorMsg = 'CORS Error: Backend or frontend URL mismatch. Check that server is running.';
    } else if (networkError?.includes('ERR_FAILED') || networkError?.includes('connect')) {
      errorMsg = 'Network Error: Cannot connect to backend at ' + api.defaults.baseURL;
    } else {
      errorMsg = detail || message || networkError || 'Unexpected API error';
    }

    return Promise.reject(new Error(errorMsg));
  },
);

export default api;
