export const RESUME_BUCKET = 'resumes';
export const MAX_RESUME_SIZE_BYTES = 10 * 1024 * 1024;

export const sanitizeResumeFileName = (fileName) =>
  fileName
    .trim()
    .replace(/\s+/g, '-')
    .replace(/[^a-zA-Z0-9._-]/g, '_');

export const buildResumePath = (userId, fileName) => {
  const safeFileName = sanitizeResumeFileName(fileName);
  const timestamp = Date.now();

  return `${userId}/${timestamp}-${safeFileName}`;
};
