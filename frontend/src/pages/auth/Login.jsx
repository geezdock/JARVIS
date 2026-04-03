import React from 'react';
import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { motion } from 'framer-motion';
import toast from 'react-hot-toast';
import { useAuth } from '../../contexts/AuthContext';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import Input from '../../components/ui/Input';

export default function Login() {
  const { login } = useAuth();
  const navigate = useNavigate();
  const [form, setForm] = useState({ email: '', password: '' });
  const [submitting, setSubmitting] = useState(false);

  const onChange = (event) => {
    const { name, value } = event.target;
    setForm((prev) => ({ ...prev, [name]: value }));
  };

  const validate = () => {
    if (!form.email.includes('@')) {
      toast.error('Enter a valid email');
      return false;
    }

    if (form.password.length < 6) {
      toast.error('Password must be at least 6 characters');
      return false;
    }

    return true;
  };

  const onSubmit = async (event) => {
    event.preventDefault();
    if (!validate()) return;

    try {
      setSubmitting(true);
      const data = await login(form.email.trim(), form.password);
      const loginRole =
        data?.user?.user_metadata?.role || (data?.user?.email?.includes('admin') ? 'admin' : 'candidate');
      const destination = loginRole === 'admin' ? '/admin' : '/candidate';
      toast.success('Logged in successfully');
      navigate(destination, { replace: true });
    } catch (error) {
      toast.error(error.message || 'Unable to login');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <motion.div
      initial={{ opacity: 0, y: 20 }}
      animate={{ opacity: 1, y: 0 }}
      className="mx-auto w-full max-w-md"
    >
      <Card>
        <h1 className="text-2xl font-black text-slate-900">Welcome back</h1>
        <p className="mt-2 text-sm text-slate-600">Sign in to continue your recruitment workflow.</p>

        <form className="mt-6 space-y-4" onSubmit={onSubmit}>
          <div>
            <label htmlFor="email" className="mb-1.5 block text-sm font-medium text-slate-700">
              Email
            </label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder="name@company.com"
              value={form.email}
              onChange={onChange}
              required
            />
          </div>

          <div>
            <label htmlFor="password" className="mb-1.5 block text-sm font-medium text-slate-700">
              Password
            </label>
            <Input
              id="password"
              name="password"
              type="password"
              placeholder="Enter password"
              value={form.password}
              onChange={onChange}
              required
            />
          </div>

          <Button className="w-full" type="submit" disabled={submitting}>
            {submitting ? 'Signing in...' : 'Login'}
          </Button>
        </form>

        <p className="mt-4 text-sm text-slate-600">
          New user?{' '}
          <Link to="/signup" className="font-semibold text-teal-700 hover:text-teal-800">
            Create account
          </Link>
        </p>
      </Card>
    </motion.div>
  );
}
