import { useEffect, useState } from 'react';
function read() { return document.documentElement.dataset.motion === 'off' || (typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches); }
export default function useReducedMotion() {
  const [reduced, setReduced] = useState(read);
  useEffect(() => {
    const query = typeof matchMedia !== 'undefined' ? matchMedia('(prefers-reduced-motion: reduce)') : null;
    const update = () => setReduced(read());
    query?.addEventListener('change', update);
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-motion'] });
    return () => { query?.removeEventListener('change', update); observer.disconnect(); };
  }, []);
  return reduced;
}
