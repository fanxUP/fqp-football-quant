import { useState, useEffect, useCallback, createContext, useContext, useRef, type ReactNode } from 'react';

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
  const [exitingIds, setExitingIds] = useState<Set<number>>(new Set());
  const timersRef = useRef<Map<number, ReturnType<typeof setTimeout>>>(new Map());

  const removeToast = useCallback((id: number) => {
    // Start exit animation
    setExitingIds((prev) => new Set(prev).add(id));
    // Remove after animation completes
    const timer = setTimeout(() => {
      setToasts((prev) => prev.filter((t) => t.id !== id));
      setExitingIds((prev) => {
        const next = new Set(prev);
        next.delete(id);
        return next;
      });
      timersRef.current.delete(id);
    }, 300);
    timersRef.current.set(id, timer);
  }, []);

  const addToast = useCallback((type: ToastType, message: string) => {
    const id = _nextId++;
    setToasts((prev) => [...prev, { id, type, message }]);
    // Auto-dismiss after 4s
    const timer = setTimeout(() => {
      removeToast(id);
    }, 4000);
    timersRef.current.set(id, timer);
  }, [removeToast]);

  useEffect(() => {
    _addToast = addToast;
    return () => {
      _addToast = null;
      // Cleanup all timers
      timersRef.current.forEach((t) => clearTimeout(t));
      timersRef.current.clear();
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
          <div
            key={t.id}
            className={`fqp-toast fqp-toast-${t.type}${exitingIds.has(t.id) ? ' exiting' : ''}`}
          >
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
