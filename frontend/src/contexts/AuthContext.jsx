import React, { createContext, useCallback, useContext, useEffect, useState } from 'react';
import { hasSupabaseConfig, supabase, supabaseConfigError } from '../lib/supabase';

const AuthContext = createContext({});
const INTERVIEW_LOCK_STORAGE_KEY = 'jarvis.interviewLock';

const deriveRole = (user) => {
  if (!user) return null;

  const metadataRole = user.user_metadata?.role;

  if (metadataRole === 'admin' || metadataRole === 'candidate') {
    return metadataRole;
  }

  return user.email?.includes('admin') ? 'admin' : 'candidate';
};

const deriveDisplayName = (user) => {
  if (!user) return null;

  const firstName = user.user_metadata?.first_name?.trim();
  const lastName = user.user_metadata?.last_name?.trim();

  if (firstName && lastName) {
    return `${firstName} ${lastName}`;
  }

  if (firstName) {
    return firstName;
  }

  if (lastName) {
    return lastName;
  }

  return user.user_metadata?.full_name?.trim() || null;
};

export const useAuth = () => {
  return useContext(AuthContext);
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [role, setRole] = useState(null);
  const [displayName, setDisplayName] = useState(null);
  const [loading, setLoading] = useState(true);
  const [interviewLock, setInterviewLock] = useState(() => {
    try {
      const raw = window.sessionStorage.getItem(INTERVIEW_LOCK_STORAGE_KEY);
      if (!raw) {
        return null;
      }
      const parsed = JSON.parse(raw);
      if (!parsed || !parsed.active || !parsed.sessionId) {
        return null;
      }
      return {
        active: true,
        sessionId: String(parsed.sessionId),
        startedAt: parsed.startedAt || new Date().toISOString(),
      };
    } catch (_error) {
      return null;
    }
  });

  const persistInterviewLock = useCallback((value) => {
    if (!value || !value.active) {
      window.sessionStorage.removeItem(INTERVIEW_LOCK_STORAGE_KEY);
      return;
    }
    window.sessionStorage.setItem(INTERVIEW_LOCK_STORAGE_KEY, JSON.stringify(value));
  }, []);

  const startInterviewLock = useCallback((sessionId) => {
    const lock = {
      active: true,
      sessionId: String(sessionId),
      startedAt: new Date().toISOString(),
    };
    setInterviewLock(lock);
    persistInterviewLock(lock);
  }, [persistInterviewLock]);

  const clearInterviewLock = useCallback(() => {
    setInterviewLock(null);
    persistInterviewLock(null);
  }, [persistInterviewLock]);

  useEffect(() => {
    const initializeAuth = async () => {
      if (!hasSupabaseConfig) {
        setLoading(false);
        return;
      }

      try {
        const {
          data: { session },
          error,
        } = await supabase.auth.getSession();

        if (error) {
          console.error('Error fetching session:', error.message);
        }

        setUser(session?.user ?? null);
        setRole(deriveRole(session?.user));
        setDisplayName(deriveDisplayName(session?.user));
      } catch (err) {
        console.error('Unexpected error during auth initialization:', err);
      } finally {
        setLoading(false);
      }
    };

    initializeAuth();

    if (!hasSupabaseConfig) {
      return () => {};
    }

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setRole(deriveRole(session?.user));
      setDisplayName(deriveDisplayName(session?.user));
      setLoading(false);
    });

    return () => {
      subscription?.unsubscribe();
    };
  }, []);

  const login = async (email, password) => {
    if (!hasSupabaseConfig) {
      throw new Error(supabaseConfigError);
    }

    setLoading(true);
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    setLoading(false);
    if (error) throw error;
    return data;
  };

  const signup = async ({
    email,
    password,
    role: selectedRole = 'candidate',
    firstName = '',
    lastName = '',
  }) => {
    if (!hasSupabaseConfig) {
      throw new Error(supabaseConfigError);
    }

    setLoading(true);
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          role: selectedRole,
          first_name: firstName,
          last_name: lastName,
          full_name: [firstName, lastName].filter(Boolean).join(' '),
        },
      },
    });
    setLoading(false);
    if (error) throw error;
    return data;
  };

  const logout = async () => {
    if (!hasSupabaseConfig) {
      throw new Error(supabaseConfigError);
    }

    setLoading(true);
    const { error } = await supabase.auth.signOut();
    setLoading(false);
    if (error) throw error;
  };

  const value = {
    user,
    role,
    displayName,
    isAdmin: role === 'admin',
    isCandidate: role === 'candidate',
    loading,
    interviewLock,
    startInterviewLock,
    clearInterviewLock,
    login,
    signup,
    logout,
  };

  return (
    <AuthContext.Provider value={value}>
      {children}
    </AuthContext.Provider>
  );
};
