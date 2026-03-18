'use client';

import { useState } from 'react';
import { Upload, FileSpreadsheet } from 'lucide-react';

/**
 * Drag-and-drop file upload component.
 */
export default function FileUpload({ onFile, accept = '.xlsx,.xls,.csv', label = 'Upload file', disabled = false }) {
  const [dragOver, setDragOver] = useState(false);
  const [fileName, setFileName] = useState('');

  function handleDrop(e) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer?.files?.[0];
    if (file) {
      setFileName(file.name);
      onFile(file);
    }
  }

  function handleChange(e) {
    const file = e.target.files?.[0];
    if (file) {
      setFileName(file.name);
      onFile(file);
    }
  }

  return (
    <div
      className={`border-2 border-dashed rounded-xl p-8 text-center transition-colors ${
        dragOver ? 'border-teal-400 bg-teal-50' : 'border-slate-300 bg-white hover:border-slate-400'
      } ${disabled ? 'opacity-50 pointer-events-none' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <FileSpreadsheet className="w-10 h-10 text-slate-400 mx-auto mb-3" />
      <p className="text-sm font-medium text-slate-700 mb-1">{label}</p>
      <p className="text-xs text-slate-500 mb-3">Drag and drop or click to browse</p>
      <input
        type="file"
        accept={accept}
        onChange={handleChange}
        className="hidden"
        id={`file-upload-${label}`}
        disabled={disabled}
      />
      <label
        htmlFor={`file-upload-${label}`}
        className="inline-flex items-center gap-2 px-4 py-2 bg-teal-600 text-white text-sm font-medium rounded-lg cursor-pointer hover:bg-teal-700 transition-colors"
      >
        <Upload className="w-4 h-4" />
        Choose File
      </label>
      {fileName && (
        <p className="text-xs text-teal-600 font-medium mt-3">{fileName}</p>
      )}
    </div>
  );
}
