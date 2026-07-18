import { describe, expect, it } from 'vitest';

const nodeFsSpecifier = 'node:fs';
const { readFileSync } = await import(nodeFsSpecifier);
const runtimeProcess = (globalThis as typeof globalThis & {
  process: { cwd: () => string };
}).process;
const stylesheet = readFileSync(
  `${runtimeProcess.cwd()}/src/features/betting-terminal/SportteryBettingTerminal.css`,
  'utf8',
);

describe('SportteryBettingTerminal visual semantics', () => {
  it('uses stable red and green backgrounds for single and pass flags', () => {
    expect(stylesheet).toContain('--st-single-bg: #d63b49;');
    expect(stylesheet).toContain('--st-pass-bg: #087a5b;');
    expect(stylesheet).toMatch(/\.sporttery-market-flags span\.is-single\s*{[^}]*background:\s*var\(--st-single-bg\)/);
    expect(stylesheet).toMatch(/\.sporttery-market-flags span\.is-pass\s*{[^}]*background:\s*var\(--st-pass-bg\)/);
    expect(stylesheet).toMatch(/\.sporttery-play-flags \.is-single\s*{[^}]*background:\s*var\(--st-single-bg\)/);
    expect(stylesheet).toMatch(/\.sporttery-play-flags \.is-pass\s*{[^}]*background:\s*var\(--st-pass-bg\)/);
  });

  it('keeps positive handicap red and negative handicap green after theme overrides', () => {
    expect(stylesheet).toMatch(/span\.is-positive\s*{[^}]*color:\s*var\(--st-handicap-positive\)/);
    expect(stylesheet).toMatch(/span\.is-negative\s*{[^}]*color:\s*var\(--st-handicap-negative\)/);
    expect(stylesheet).toContain('--st-handicap-positive: #ff6b73;');
    expect(stylesheet).toContain('--st-handicap-negative: #2fc39b;');
  });

  it('keeps the score market on a five-column grid at every breakpoint', () => {
    expect(stylesheet).toMatch(/\.sporttery-score-grid\s*{[^}]*grid-template-columns:\s*repeat\(5,/);
    expect(stylesheet).not.toMatch(/\.sporttery-score-grid\s*{[^}]*grid-template-columns:\s*repeat\(4,/);
    expect(stylesheet).toMatch(/\.sporttery-score-grid \.is-score-wide\s*{[^}]*grid-column:\s*span 3/);
  });

  it('keeps betting dialogs fixed to the viewport inside the animated page container', () => {
    expect(stylesheet).toMatch(/\.fqp-page-transition:has\(\.sporttery-dialog-backdrop\)\s*{[^}]*transform:\s*none !important/);
    expect(stylesheet).toMatch(/\.fqp-page-transition:has\(\.sporttery-dialog-backdrop\)\s*{[^}]*animation:\s*none !important/);
  });
});
