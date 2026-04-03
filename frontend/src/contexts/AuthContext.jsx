import React, { createContext, useContext, useEffect, useState } from 'react';
import { supabase } from '../lib/supabase';

const AuthContext = createContext({});

const deriveRole = (user) => {
  if (!user) return null;

  const metadataRole = user.user_metadata?.role;

  if (metadataRole === 'admin' || metadataRole === 'candidate') {
    return metadataRole;
  }

  return user.email?.includes('admin') ? 'admin' : 'candidate';
};

export const useAuth = () => {
  return useContext(AuthContext);
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [role, setRole] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const initializeAuth = async () => {
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
      } catch (err) {
        console.error('Unexpected error during auth initialization:', err);
      } finally {
        setLoading(false);
      }
    };

    initializeAuth();

    const {
      data: { subscription },
    } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      setRole(deriveRole(session?.user));
      setLoading(false);
    });

    return () => {
      subscription?.unsubscribe();
    };
  }, []);

  const login = async (email, password) => {
    setLoading(true);
    const { data, error } = await supabase.auth.signInWithPassword({
      email,
      password,
    });
    setLoading(false);
    if (error) throw error;
    return data;
  };

  const signup = async ({ email, password, role: selectedRole = 'candidate' }) => {
    setLoading(true);
    const { data, error } = await supabase.auth.signUp({
      email,
      password,
      options: {
        data: {
          role: selectedRole,
        },
      },
    });
    setLoading(false);
    if (error) throw error;
    return data;
  };

  const logout = async () => {
    setLoading(true);
    const { error } = await supabase.auth.signOut();
    setLoading(false);
    if (error) throw error;
  };

  const value = {
    user,
    role,
    isAdmin: role === 'admin',
    isCandidate: role === 'candidate',
    loading,
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
