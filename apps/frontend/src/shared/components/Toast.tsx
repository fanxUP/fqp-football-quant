import { useState, useEffect, useCallback, createContext, useContext, type ReactNode } from 'react';

type ToastType = 'success' | 'error' | 'warning';

interface ToastItem {
  id: number;
  type: ToastType;
  message: string;
}

interface ToastCtx {
  success: (msg: string) => void;
  error: (msg: string) => void;
  warning: (msg: string) => void;
}

const ToastContext = createContext<ToastCtx | null>(null);

let _nextId = 1;
let _addToast: ((type: ToastType, message: string) => void) | null = null;

/** Imperative API — usable outside React components. */
export const toast = {
  success: (msg: string) => _addToast?.('success', msg),
  error: (msg: string) => _addToast?.('error', msg),
  warning: (msg: string) => _addToast?.('warning', msg),
};

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<ToastItem[]>([]);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = _nextId++;
    setToasts((prev) => [...prev, { id, type, message }]);
    setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
    }, 4000);
  }, []);

  useEffect(() => {
    _addToast = addToast;
    return () => {
      _addToast = null;
    };
  }, [addToast]);

  const ctx: ToastCtx = {
    success: (msg) => addToast('success', msg),
    error: (msg) => addToast('error', msg),
    warning: (msg) => addToast('warning', msg),
  };

  return (
    <ToastContext.Provider value={ctx}>
      {children}
      <div className="fqp-toast-container">
        {toasts.map((t) => (
          <div key={t.id} className={`fqp-toast fqp-toast-${t.type}`}>
            {t.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast(): ToastCtx {
  const ctx = useContext(ToastContext);
  if (!ctx) throw new Error('useToast must be used within ToastProvider');
  return ctx;
}
