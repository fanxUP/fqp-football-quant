import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import { initializeTheme } from './app/ThemeContext';
import './theme/red_black_tech_tokens.css';
import './theme/appearance.css';
import './features/command-center/command-center.css';
import './theme/tokens/base.css';
import './theme/themes/redline-quant.css';
import './theme/themes/polar-lab.css';

initializeTheme();

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
