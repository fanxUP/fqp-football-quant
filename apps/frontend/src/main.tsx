import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './theme/red_black_tech_tokens.css';
import './theme/themes.css';
import './theme/appearance.css';
import './theme/tokens/base.css';
import './theme/themes/redline-quant.css';
import './theme/themes/black-gold-terminal.css';
import './theme/themes/polar-lab.css';
import './theme/themes/deep-navy.css';

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
