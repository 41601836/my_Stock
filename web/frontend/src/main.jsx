import React from 'react'
import ReactDOM from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <BrowserRouter>
      {/* zoom-root: 全局缩放容器，由 App.jsx 内的 useEffect 动态修改 transform */}
      <div id="zoom-root">
        <App />
      </div>
    </BrowserRouter>
  </React.StrictMode>,
)
