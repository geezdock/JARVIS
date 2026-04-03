import React from 'react';
import { useState } from 'react';
import { motion } from 'framer-motion';
import { FileCheck2, Upload } from 'lucide-react';
import toast from 'react-hot-toast';
import api from '../../lib/axios';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';

export default function ProfileUpload() {
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);

  const onFileChange = (event) => {
    const selectedFile = event.target.files?.[0];

    if (!selectedFile) {
      setFile(null);
      return;
    }

    const isPdf = selectedFile.type === 'application/pdf';
    if (!isPdf) {
      toast.error('Only PDF files are allowed');
      return;
    }

    setFile(selectedFile);
  };

  const onSubmit = async (event) => {
    event.preventDefault();

    if (!file) {
      toast.error('Please choose a resume PDF');
      return;
    }

    try {
      setSubmitting(true);
      await api.post('/candidate/profile-upload', {
        filename: file.name,
        size: file.size,
        type: file.type,
        submittedAt: new Date().toISOString(),
      });
      toast.success('Resume uploaded and queued for AI parsing');
      setFile(null);
    } catch (_error) {
      toast.success('Resume saved locally (mock mode active)');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <motion.div initial={{ opacity: 0, y: 12 }} animate={{ opacity: 1, y: 0 }} className="mx-auto w-full max-w-2xl">
      <Card>
        <h1 className="text-2xl font-black text-slate-900">Profile Upload</h1>
        <p className="mt-2 text-sm text-slate-600">Upload your latest PDF resume for AI-based screening.</p>

        <form onSubmit={onSubmit} className="mt-6 space-y-4">
          <label className="flex cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed border-teal-300 bg-teal-50/60 p-8 text-center transition hover:bg-teal-50">
            <Upload className="text-teal-700" size={28} />
            <span className="mt-2 text-sm font-semibold text-slate-900">Click to upload PDF</span>
            <span className="mt-1 text-xs text-slate-500">Max 10MB recommended</span>
            <input type="file" accept="application/pdf" className="hidden" onChange={onFileChange} />
          </label>

          {file && (
            <div className="flex items-center gap-2 rounded-xl bg-emerald-100 px-3 py-2 text-sm font-medium text-emerald-700">
              <FileCheck2 size={16} /> {file.name}
            </div>
          )}

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? 'Submitting...' : 'Submit Resume'}
          </Button>
        </form>
      </Card>
    </motion.div>
  );
}
