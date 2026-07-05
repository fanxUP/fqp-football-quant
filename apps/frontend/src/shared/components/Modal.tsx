import { useEffect, useCallback, useState, type ReactNode } from 'react';

interface ModalProps {
  open: boolean;
  onClose: () => void;
  title: string;
  children: ReactNode;
  footer?: ReactNode;
}

export default function Modal({ open, onClose, title, children, footer }: ModalProps) {
  const [closing, setClosing] = useState(false);

  const doClose = useCallback(() => {
    setClosing(true);
    setTimeout(() => {
      setClosing(false);
      onClose();
    }, 200); // matches fqpModalOut duration
  }, [onClose]);

  const handleKeyDown = useCallback(
    (e: KeyboardEvent) => {
      if (e.key === 'Escape') doClose();
    },
    [doClose],
  );

  useEffect(() => {
    if (open) {
      setClosing(false);
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
    <div
      className={`fqp-modal-overlay${closing ? ' fqp-modal-closing' : ''}`}
      onClick={(e) => e.target === e.currentTarget && doClose()}
    >
      <div className={`fqp-modal${closing ? ' fqp-modal-closing' : ''}`}>
        <div className="fqp-modal-header">{title}</div>
        <div className="fqp-modal-body">{children}</div>
        {footer && <div className="fqp-modal-footer">{footer}</div>}
      </div>
    </div>
  );
}
