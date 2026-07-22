import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import TeamName from './TeamName';

describe('TeamName', () => {
  it('pairs every rendered team name with its local crest', () => {
    render(<TeamName name="汉坎" />);

    expect(screen.getByText('汉坎')).toBeInTheDocument();
    expect(screen.getByRole('img', { name: '汉坎' })).toHaveAttribute('src', '/team-crests/500-861.png');
  });
});
