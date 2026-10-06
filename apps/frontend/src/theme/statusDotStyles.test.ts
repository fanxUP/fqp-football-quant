import { describe, expect, it } from 'vitest';

const nodeFsSpecifier = 'node:fs';
const { readFileSync } = await import(nodeFsSpecifier);
const runtimeProcess = (globalThis as typeof globalThis & {
  process: { cwd: () => string };
}).process;
const stylesheet = readFileSync(
  `${runtimeProcess.cwd()}/src/theme/red_black_tech_tokens.css`,
  'utf8',
);

describe('status dot visual semantics', () => {
  it('renders informational and disabled task states as visible dots', () => {
    expect(stylesheet).toMatch(
      /\.fqp-status-dot-info\s*{[^}]*background:\s*var\(--fqp-info\)/,
    );
    expect(stylesheet).toMatch(
      /\.fqp-status-dot-disabled\s*{[^}]*background:\s*var\(--fqp-text-muted\)/,
    );
  });
});
