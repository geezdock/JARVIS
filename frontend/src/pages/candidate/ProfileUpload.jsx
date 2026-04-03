import React from 'react';
import { useRef, useState } from 'react';
import { motion } from 'framer-motion';
import { FileCheck2, Upload } from 'lucide-react';
import toast from 'react-hot-toast';
import api from '../../lib/axios';
import Button from '../../components/ui/Button';
import Card from '../../components/ui/Card';
import { buildResumePath, MAX_RESUME_SIZE_BYTES, RESUME_BUCKET } from '../../lib/resumeStorage';
import { supabase } from '../../lib/supabase';

export default function ProfileUpload() {
  const [file, setFile] = useState(null);
  const [submitting, setSubmitting] = useState(false);
  const [uploadProgress, setUploadProgress] = useState(0);
  const [lastUpload, setLastUpload] = useState(null);
  const inputRef = useRef(null);

  const uploadToSupabaseStorage = async (fileToUpload, uploadPath) => {
    return new Promise((resolve, reject) => {
      const uploadResultPromise = api.post('/candidate/storage/signed-upload', {
        path: uploadPath,
      });

      uploadResultPromise
        .then((response) => {
          if (!response.data?.signedUrl) {
            reject(new Error('Unable to create signed upload URL'));
            return;
          }

          const xhr = new XMLHttpRequest();
          const formData = new FormData();

          xhr.open('PUT', response.data.signedUrl, true);
          xhr.setRequestHeader('x-upsert', 'false');

          formData.append('cacheControl', '3600');
          formData.append('', fileToUpload);

          xhr.upload.addEventListener('progress', (event) => {
            if (event.lengthComputable) {
              setUploadProgress(Math.round((event.loaded / event.total) * 100));
            }
          });

          xhr.onload = () => {
            if (xhr.status >= 200 && xhr.status < 300) {
              resolve();
              return;
            }

            reject(new Error('Unable to upload resume to Supabase Storage'));
          };

          xhr.onerror = () => {
            reject(new Error('Network error while uploading resume'));
          };

          xhr.send(formData);
        })
        .catch(reject);
    });
  };

  const onFileChange = (event) => {
    const selectedFile = event.target.files?.[0];

    if (!selectedFile) {
      setFile(null);
      return;
    }

    const isPdf = selectedFile.type === 'application/pdf';
    if (!isPdf) {
      toast.error('Only PDF files are allowed');
      event.target.value = '';
      return;
    }

    if (selectedFile.size > MAX_RESUME_SIZE_BYTES) {
      toast.error('Resume size should stay under 10MB');
      event.target.value = '';
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

    let uploadedPath = null;
    setUploadProgress(0);

    try {
      setSubmitting(true);
      const {
        data: { session },
        error: userError,
      } = await supabase.auth.getSession();

      if (userError) {
        throw userError;
      }

      const user = session?.user;

      if (!user) {
        throw new Error('You must be signed in to upload a resume');
      }

      uploadedPath = buildResumePath(user.id, file.name);

      await uploadToSupabaseStorage(file, uploadedPath);
      setUploadProgress(100);

      const {
        data: { publicUrl },
      } = supabase.storage.from(RESUME_BUCKET).getPublicUrl(uploadedPath);

      const response = await api.post('/candidate/profile-upload', {
        filename: file.name,
        size: file.size,
        type: file.type,
        filePath: uploadedPath,
        fileUrl: publicUrl,
        submittedAt: new Date().toISOString(),
      });

      setLastUpload(response.data?.upload ?? {
        file_name: file.name,
        file_path: uploadedPath,
        file_url: publicUrl,
        file_size: file.size,
        mime_type: file.type,
      });
      toast.success('Resume uploaded and queued for AI parsing');
      setFile(null);
      if (inputRef.current) {
        inputRef.current.value = '';
      }
    } catch (error) {
      if (uploadedPath) {
        await supabase.storage.from(RESUME_BUCKET).remove([uploadedPath]);
      }

      setUploadProgress(0);
      toast.error(error.message || 'Unable to upload resume right now');
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
            <input ref={inputRef} type="file" accept="application/pdf" className="hidden" onChange={onFileChange} />
          </label>

          {file && (
            <div className="flex items-center gap-2 rounded-xl bg-emerald-100 px-3 py-2 text-sm font-medium text-emerald-700">
              <FileCheck2 size={16} /> {file.name}
            </div>
          )}

          {submitting && (
            <div className="space-y-2 rounded-xl border border-teal-100 bg-teal-50 p-4">
              <div className="flex items-center justify-between text-xs font-semibold uppercase tracking-wide text-teal-800">
                <span>Uploading to Supabase Storage</span>
                <span>{uploadProgress}%</span>
              </div>
              <div className="h-2 overflow-hidden rounded-full bg-teal-100">
                <div
                  className="h-full rounded-full bg-teal-600 transition-all duration-200"
                  style={{ width: `${uploadProgress}%` }}
                />
              </div>
            </div>
          )}

          {lastUpload && !submitting && (
            <div className="space-y-2 rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm text-emerald-900">
              <p className="font-semibold">Upload verified</p>
              <p>
                Stored file: <span className="font-medium">{lastUpload.file_name}</span>
              </p>
              <p className="break-all text-xs text-emerald-800">Path: {lastUpload.file_path}</p>
              {lastUpload.file_url && (
                <a
                  href={lastUpload.file_url}
                  target="_blank"
                  rel="noreferrer"
                  className="inline-flex text-xs font-semibold text-emerald-700 underline-offset-4 hover:underline"
                >
                  Open uploaded file
                </a>
              )}
            </div>
          )}

          <p className="text-xs text-slate-500">
            Your PDF is uploaded directly to Supabase Storage first, then the backend stores the file metadata.
          </p>

          <Button type="submit" disabled={submitting} className="w-full">
            {submitting ? 'Submitting...' : 'Submit Resume'}
          </Button>
        </form>
      </Card>
    </motion.div>
  );
}
