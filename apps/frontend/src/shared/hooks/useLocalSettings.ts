import { useState, useEffect, useCallback } from 'react';
import type { FqpSettings } from '../../core/types';
import { DEFAULT_SETTINGS } from '../../core/types';

const STORAGE_KEY = 'fqp-settings';

function load(): FqpSettings {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) {
      const parsed = JSON.parse(raw);
      return { ...DEFAULT_SETTINGS, ...parsed };
    }
  } catch {
    // corrupted — fall through to defaults
  }
  return { ...DEFAULT_SETTINGS };
}

function save(settings: FqpSettings) {
  localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
}

export function useLocalSettings() {
  const [settings, setSettings] = useState<FqpSettings>(load);

  useEffect(() => {
    save(settings);
  }, [settings]);

  const updateSetting = useCallback(
    <K extends keyof FqpSettings>(key: K, value: FqpSettings[K]) => {
      setSettings((prev) => ({ ...prev, [key]: value }));
    },
    [],
  );

  const resetSettings = useCallback(() => {
    setSettings({ ...DEFAULT_SETTINGS });
    localStorage.removeItem(STORAGE_KEY);
  }, []);

  return { settings, updateSetting, resetSettings };
}
