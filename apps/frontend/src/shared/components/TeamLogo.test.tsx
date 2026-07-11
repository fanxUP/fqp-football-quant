import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TeamLogo from './TeamLogo';

describe('TeamLogo', () => {
  it('renders the locally bundled crest without circular cropping', () => {
    render(<TeamLogo nameCn="汉坎" size={48} />);

    const crest = screen.getByRole('img', { name: '汉坎' });
    expect(crest).toHaveAttribute('src', '/team-crests/500-861.png');
    expect(crest).toHaveStyle({ objectFit: 'contain', borderRadius: '0' });
    expect(crest.parentElement).toHaveStyle({ borderRadius: '0' });
  });
});
