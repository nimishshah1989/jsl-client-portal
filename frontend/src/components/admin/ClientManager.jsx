'use client';

import { useState } from 'react';
import { useCreateClient } from '@/hooks/useAdmin';
import Button from '@/components/ui/Button';
import { UserPlus } from 'lucide-react';

/**
 * Create/edit client credentials form.
 */
export default function ClientManager({ onCreated }) {
  const { create, loading, error } = useCreateClient();
  const [form, setForm] = useState({
    name: '',
    client_code: '',
    username: '',
    password: '',
    email: '',
    phone: '',
  });

  function handleChange(field, value) {
    setForm((prev) => ({ ...prev, [field]: value }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    try {
      await create({
        ...form,
        username: form.username.toLowerCase().trim(),
      });
      setForm({ name: '', client_code: '', username: '', password: '', email: '', phone: '' });
      if (onCreated) onCreated();
    } catch {
      // Error handled by hook
    }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5">
      <div className="flex items-center gap-2 mb-4">
        <UserPlus className="w-5 h-5 text-teal-600" />
        <h3 className="text-base font-semibold text-slate-800">Create Client</h3>
      </div>

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-lg p-3 mb-4 text-sm text-red-600">
          {error}
        </div>
      )}

      <form onSubmit={handleSubmit} className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          { key: 'name', label: 'Full Name', type: 'text', required: true },
          { key: 'client_code', label: 'Client Code (UCC)', type: 'text', required: true },
          { key: 'username', label: 'Username', type: 'text', required: true },
          { key: 'password', label: 'Password', type: 'text', required: true },
          { key: 'email', label: 'Email', type: 'email', required: false },
          { key: 'phone', label: 'Phone', type: 'tel', required: false },
        ].map((field) => (
          <div key={field.key}>
            <label className="block text-xs font-medium text-slate-700 mb-1">
              {field.label} {field.required && <span className="text-red-500">*</span>}
            </label>
            <input
              type={field.type}
              value={form[field.key]}
              onChange={(e) => handleChange(field.key, e.target.value)}
              required={field.required}
              className="w-full border border-slate-300 rounded-lg px-3 py-2 text-sm text-slate-800 focus:ring-2 focus:ring-teal-500 focus:border-teal-500"
            />
          </div>
        ))}
        <div className="md:col-span-2">
          <Button type="submit" variant="primary" size="md" loading={loading}>
            Create Client
          </Button>
        </div>
      </form>
    </div>
  );
}
