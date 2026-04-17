'use client';

import { useState } from 'react';
import {
  useUploadNav,
  useUploadTransactions,
  useUploadEquityHoldings,
  useUploadEtfHoldings,
} from '@/hooks/useAdmin';
import Spinner from '@/components/ui/Spinner';
import {
  Upload,
  FileSpreadsheet,
  CheckCircle,
  AlertTriangle,
  Loader2,
  TrendingUp,
  ArrowLeftRight,
  BarChart2,
  Layers,
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
      className={`border-2 border-dashed rounded-xl p-6 text-center transition-colors ${
        dragOver
          ? 'border-teal-400 bg-teal-50'
          : 'border-slate-300 bg-white hover:border-slate-400'
      } ${disabled ? 'opacity-50 pointer-events-none' : ''}`}
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
    >
      <FileSpreadsheet className="w-8 h-8 text-slate-400 mx-auto mb-2" />
      <p className="text-xs text-slate-500 mb-3">
        Drag and drop or click to browse (.xlsx files)
      </p>
      <input
        type="file"
        accept={accept || '.xlsx,.xls'}
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
        <p className="text-xs text-teal-600 font-medium mt-2 truncate max-w-full px-2">
          {fileName}
        </p>
      )}
    </div>
  );
}

function ProcessingStatus({ status, elapsed, progress }) {
  if (!status || status === 'uploading') return null;
  if (status !== 'processing') return null;

  const { clients_processed = 0, clients_total = 0, current_client = '' } = progress || {};
  const pct = clients_total > 0 ? Math.round((clients_processed / clients_total) * 100) : 0;
  const hasProgress = clients_total > 0;

  return (
    <div className="mt-3 bg-teal-50 border border-teal-200 rounded-xl p-4">
      <div className="flex items-center gap-3">
        <Loader2 className="w-5 h-5 text-teal-600 animate-spin flex-shrink-0" />
        <div className="flex-1 min-w-0">
          <p className="text-sm font-medium text-teal-800">
            {hasProgress
              ? `Processing client ${clients_processed + 1} of ${clients_total}`
              : 'Processing in background...'}
          </p>
          {current_client && (
            <p className="text-xs font-mono text-teal-700 truncate">{current_client}</p>
          )}
        </div>
        <span className="text-xs font-mono text-teal-600 flex-shrink-0">
          {elapsed > 0 ? `${Math.round(elapsed)}s` : '...'}
        </span>
      </div>
      {hasProgress && (
        <div className="mt-3">
          <div className="w-full bg-teal-100 rounded-full h-2 overflow-hidden">
            <div
              className="bg-teal-600 h-2 rounded-full transition-all duration-500 ease-out"
              style={{ width: `${pct}%` }}
            />
          </div>
          <p className="text-xs text-teal-500 mt-1 text-right font-mono">{pct}%</p>
        </div>
      )}
      <p className="text-xs text-teal-600 mt-2">
        You can close this page — processing continues on the server.
      </p>
    </div>
  );
}

function UploadResult({ result, type }) {
  if (!result) return null;

  return (
    <div className="bg-white rounded-xl border border-slate-200 p-4 mt-3">
      <div className="flex items-center gap-2 mb-3">
        <CheckCircle className="w-4 h-4 text-emerald-600" />
        <h3 className="text-sm font-semibold text-slate-800">{type} Upload Complete</h3>
      </div>
      <div className="grid grid-cols-3 gap-2 text-sm">
        <div className="bg-slate-50 rounded-lg p-2">
          <p className="text-xs text-slate-500">Updated</p>
          <p className="text-base font-bold font-mono text-emerald-600">
            {(result.rows_processed || 0).toLocaleString()}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-2">
          <p className="text-xs text-slate-500">Clients</p>
          <p className="text-base font-bold font-mono text-slate-800">
            {result.clients_affected || '--'}
          </p>
        </div>
        <div className="bg-slate-50 rounded-lg p-2">
          <p className="text-xs text-slate-500">Errors</p>
          <p className={`text-base font-bold font-mono ${result.rows_failed > 0 ? 'text-red-600' : 'text-slate-400'}`}>
            {result.rows_failed || 0}
          </p>
        </div>
      </div>
      {result.errors?.length > 0 && (
        <div className="mt-2">
          <p className="text-xs font-semibold text-red-600 mb-1">Errors:</p>
          <div className="max-h-32 overflow-y-auto bg-red-50 rounded-lg p-2 text-xs text-red-700">
            {result.errors.map((err, i) => (
              <p key={i}>{typeof err === 'string' ? err : JSON.stringify(err)}</p>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function UploadSection({ icon: Icon, title, description, color, uploadHook }) {
  const { upload, loading, error, result, status, elapsed, progress } = uploadHook();

  async function handleFile(file) {
    try { await upload(file); } catch { /* error handled by hook */ }
  }

  return (
    <div className="bg-white rounded-xl border border-slate-200 overflow-hidden">
      <div className={`px-5 py-4 border-b border-slate-100 flex items-center gap-3`}>
        <div className={`w-8 h-8 rounded-lg flex items-center justify-center ${color}`}>
          <Icon className="w-4 h-4 text-white" />
        </div>
        <div>
          <h3 className="text-sm font-semibold text-slate-800">{title}</h3>
          <p className="text-xs text-slate-500">{description}</p>
        </div>
      </div>
      <div className="p-5">
        <FileDropZone
          label={title}
          onFile={handleFile}
          disabled={loading}
        />
        {status === 'uploading' && (
          <div className="flex items-center gap-2 mt-3 text-sm text-teal-600">
            <Spinner size="sm" /> Uploading file...
          </div>
        )}
        <ProcessingStatus status={status} elapsed={elapsed} progress={progress} />
        {error && (
          <div className="flex items-center gap-2 mt-3 text-sm text-red-600">
            <AlertTriangle className="w-4 h-4 flex-shrink-0" /> {error}
          </div>
        )}
        <UploadResult result={result} type={title} />
      </div>
    </div>
  );
}

const UPLOAD_SECTIONS = [
  {
    icon: TrendingUp,
    title: 'NAV Report',
    description: 'Daily NAV values, corpus, cash % for all clients',
    color: 'bg-teal-600',
    uploadHook: useUploadNav,
  },
  {
    icon: ArrowLeftRight,
    title: 'Transaction Report',
    description: 'Buy / sell / bonus transactions for all clients',
    color: 'bg-blue-600',
    uploadHook: useUploadTransactions,
  },
  {
    icon: BarChart2,
    title: 'Equity Holding File',
    description: 'BO equity positions — updates prices + reconciliation',
    color: 'bg-violet-600',
    uploadHook: useUploadEquityHoldings,
  },
  {
    icon: Layers,
    title: 'ETF / MF Holding File',
    description: 'Mutual fund & ETF positions — updates ETF prices',
    color: 'bg-amber-600',
    uploadHook: useUploadEtfHoldings,
  },
];

export default function UploadPage() {
  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-800">Upload Data Files</h2>
        <p className="text-sm text-slate-500 mt-1">
          Upload PMS backoffice .xlsx exports. All files are processed in the background —
          you can safely navigate away after uploading.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        {UPLOAD_SECTIONS.map((section) => (
          <UploadSection key={section.title} {...section} />
        ))}
      </div>

      <div className="bg-slate-50 rounded-xl border border-slate-200 p-4">
        <p className="text-xs font-semibold text-slate-600 mb-2">Recommended upload order</p>
        <ol className="text-xs text-slate-500 space-y-1 list-decimal list-inside">
          <li><span className="font-medium text-slate-700">NAV Report</span> — establishes portfolio values and benchmark</li>
          <li><span className="font-medium text-slate-700">Transaction Report</span> — builds holdings from buy/sell history</li>
          <li><span className="font-medium text-slate-700">Equity Holding File</span> — updates equity prices + auto-runs reconciliation</li>
          <li><span className="font-medium text-slate-700">ETF / MF Holding File</span> — populates ETF fund prices (resolves Structural ETF gaps in reconciliation)</li>
        </ol>
      </div>
    </div>
  );
}
