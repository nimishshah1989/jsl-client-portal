'use client';

import { useState } from 'react';
import { useUploadNav, useUploadTransactions } from '@/hooks/useAdmin';
import Spinner from '@/components/ui/Spinner';
import {
  Upload,
  FileSpreadsheet,
  CheckCircle,
  AlertTriangle,
  Loader2,
} from 'lucide-react';

function FileDropZone({ label, accept, onFile, disabled }) {
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
        dragOver
          ? 'border-teal-400 bg-teal-50'
          : 'border-slate-300 bg-white hover:border-slate-400'
      } ${disabled ? 'opacity-50 pointer-events-none' : ''}`}
      onDragOver={(e) => {
        e.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <FileSpreadsheet className="w-10 h-10 text-slate-400 mx-auto mb-3" />
      <p className="text-sm font-medium text-slate-700 mb-1">{label}</p>
      <p className="text-xs text-slate-500 mb-3">
        Drag and drop or click to browse (.xlsx files)
      </p>
      <input
        type="file"
        accept={accept || '.xlsx,.xls,.csv'}
        onChange={handleChange}
        className="hidden"
        id={`file-${label}`}
        disabled={disabled}
      />
      <label
        htmlFor={`file-${label}`}
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

function ProcessingStatus({ status, elapsed }) {
  if (!status || status === 'uploading') return null;

  if (status === 'processing') {
    return (
      <div className="flex items-center gap-3 mt-4 bg-teal-50 border border-teal-200 rounded-xl p-4">
        <Loader2 className="w-5 h-5 text-teal-600 animate-spin" />
        <div>
          <p className="text-sm font-medium text-teal-800">
            Processing in background...
          </p>
          <p className="text-xs text-teal-600">
            {elapsed > 0 ? `${Math.round(elapsed)}s elapsed` : 'Starting...'} — You can close this page. Processing will continue on the server.
          </p>
        </div>
      </div>
    );
  }

  return null;
}

function UploadResult({ result, type }) {
  if (!result) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-5 mt-4">
      <div className="flex items-center gap-2 mb-3">
        <CheckCircle className="w-5 h-5 text-emerald-600" />
        <h3 className="font-semibold text-slate-800">{type} Upload Complete</h3>
      </div>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-sm">
        <div className="bg-slate-50 rounded-lg p-3">
          <p className="text-xs text-slate-500">Rows Processed</p>
          <p className="text-lg font-bold font-mono text-emerald-600">
            {(result.rows_processed || 0).toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-3">
          <p className="text-xs text-slate-500">Clients Affected</p>
          <p className="text-lg font-bold font-mono text-slate-800">
            {result.clients_affected || '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-3">
          <p className="text-xs text-slate-500">Rows Failed</p>
          <p
            className={`text-lg font-bold font-mono ${
              result.rows_failed > 0 ? 'text-red-600' : 'text-slate-800'
            }`}
          >
            {result.rows_failed || 0}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-3">
          <p className="text-xs text-slate-500">Duration</p>
          <p className="text-lg font-bold font-mono text-slate-800">
            {result.elapsed_seconds
              ? `${Math.round(result.elapsed_seconds)}s`
              : '--'}
          </p>
        </div>
      </div>
      {result.errors && result.errors.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-semibold text-red-600 mb-1">Errors:</p>
          <div className="max-h-40 overflow-y-auto bg-red-50 rounded-lg p-3 text-xs text-red-700">
            {result.errors.map((err, i) => (
              <p key={i}>
                {typeof err === 'string' ? err : JSON.stringify(err)}
              </p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

export default function UploadPage() {
  const {
    upload: uploadNav,
    loading: navLoading,
    error: navError,
    result: navResult,
    status: navStatus,
    elapsed: navElapsed,
  } = useUploadNav();
  const {
    upload: uploadTxn,
    loading: txnLoading,
    error: txnError,
    result: txnResult,
    status: txnStatus,
    elapsed: txnElapsed,
  } = useUploadTransactions();

  async function handleNavUpload(file) {
    try {
      await uploadNav(file);
    } catch {
      // Error handled by hook
    }
  }

  async function handleTxnUpload(file) {
    try {
      await uploadTxn(file);
    } catch {
      // Error handled by hook
    }
  }

  return (
    <div className="space-y-6">
      <h2 className="text-xl font-bold text-slate-800">Upload Data Files</h2>
      <p className="text-sm text-slate-500">
        Upload the PMS backoffice .xlsx exports. The system will parse, validate,
        and ingest data for all clients found in the file. Processing happens in
        the background — you can safely navigate away.
      </p>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {/* NAV Upload */}
        <div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">
            NAV Report
          </h3>
          <FileDropZone
            label="Upload NAV Report (.xlsx)"
            onFile={handleNavUpload}
            disabled={navLoading}
          />
          {navStatus === 'uploading' && (
            <div className="flex items-center gap-2 mt-3 text-sm text-teal-600">
              <Spinner size="sm" /> Uploading file...
            </div>
          )}
          <ProcessingStatus status={navStatus} elapsed={navElapsed} />
          {navError && (
            <div className="flex items-center gap-2 mt-3 text-sm text-red-600">
              <AlertTriangle className="w-4 h-4" /> {navError}
            </div>
          )}
          <UploadResult result={navResult} type="NAV" />
        </div>

        {/* Transaction Upload */}
        <div>
          <h3 className="text-sm font-semibold text-slate-700 mb-2">
            Transaction Report
          </h3>
          <FileDropZone
            label="Upload Transaction Report (.xlsx)"
            onFile={handleTxnUpload}
            disabled={txnLoading}
          />
          {txnStatus === 'uploading' && (
            <div className="flex items-center gap-2 mt-3 text-sm text-teal-600">
              <Spinner size="sm" /> Uploading file...
            </div>
          )}
          <ProcessingStatus status={txnStatus} elapsed={txnElapsed} />
          {txnError && (
            <div className="flex items-center gap-2 mt-3 text-sm text-red-600">
              <AlertTriangle className="w-4 h-4" /> {txnError}
            </div>
          )}
          <UploadResult result={txnResult} type="Transaction" />
        </div>
      </div>
    </div>
  );
}
