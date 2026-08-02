import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { DEFAULT_LANGUAGE, isAppLanguage, LANGUAGE_STORAGE_KEY, type AppLanguage } from './language';

interface LanguageContextValue {
  language: AppLanguage;
  setLanguage: (language: AppLanguage) => void;
}

const defaultValue: LanguageContextValue = {
  language: DEFAULT_LANGUAGE,
  setLanguage: () => undefined,
};

const LanguageContext = createContext<LanguageContextValue>(defaultValue);

function loadLanguage(): AppLanguage {
  try {
    const savedLanguage = localStorage.getItem(LANGUAGE_STORAGE_KEY);
    return isAppLanguage(savedLanguage) ? savedLanguage : DEFAULT_LANGUAGE;
  } catch {
    return DEFAULT_LANGUAGE;
  }
}

export function LanguageProvider({ children }: { children: ReactNode }) {
  const [language, setLanguage] = useState<AppLanguage>(loadLanguage);

  useEffect(() => {
    document.documentElement.lang = language;
    localStorage.setItem(LANGUAGE_STORAGE_KEY, language);
  }, [language]);

  const value = useMemo(() => ({ language, setLanguage }), [language]);
  return <LanguageContext.Provider value={value}>{children}</LanguageContext.Provider>;
}

export function useLanguage(): LanguageContextValue {
  return useContext(LanguageContext);
}
