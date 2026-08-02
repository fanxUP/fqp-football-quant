import { describe, expect, it, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { LanguageProvider, useLanguage } from './LanguageContext';
import { LANGUAGE_STORAGE_KEY } from './language';

function LanguageProbe() {
  const { language, setLanguage, translate } = useLanguage();
  return (
    <label>
      Language
      <select aria-label="Language" value={language} onChange={(event) => setLanguage(event.target.value as 'zh-CN' | 'en')}>
        <option value="zh-CN">简体中文</option>
        <option value="en">English</option>
      </select>
      <output>{translate('加载失败')}</output>
      <output>{translate('投注台')}</output>
    </label>
  );
}

describe('LanguageProvider', () => {
  beforeEach(() => {
    localStorage.clear();
    document.documentElement.lang = '';
  });

  it('defaults to Simplified Chinese and persists an English selection', async () => {
    const user = userEvent.setup();
    render(<LanguageProvider><LanguageProbe /></LanguageProvider>);

    const selector = screen.getByRole('combobox', { name: 'Language' });
    expect(selector).toHaveValue('zh-CN');
    expect(document.documentElement.lang).toBe('zh-CN');

    await user.selectOptions(selector, 'en');
    expect(document.documentElement.lang).toBe('en');
    expect(localStorage.getItem(LANGUAGE_STORAGE_KEY)).toBe('en');
    expect(screen.getByText('Failed to load')).toBeInTheDocument();
    expect(screen.getByText('Betting terminal')).toBeInTheDocument();
  });
});
