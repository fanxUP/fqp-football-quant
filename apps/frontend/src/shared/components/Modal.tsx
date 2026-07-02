import { useEffect, useCallback, type ReactNode } from 'react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}

export default function Modal({ open, onClose, title, children, footer }: ModalProps) {
  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    },
    [onClose],
  );

  useEffect(() => {
    if (open) {
      document.addEventListener('keydown', handleKeyDown);
      document.body.style.overflow = 'hidden';
    }
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      document.body.style.overflow = '';
    };
  }, [open, handleKeyDown]);

  if (!open) return null;

  return (
    <div className="fqp-modal-overlay" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div className="fqp-modal">
        <div className="fqp-modal-header">{title}</div>
        <div className="fqp-modal-body">{children}</div>
        {footer && <div className="fqp-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
