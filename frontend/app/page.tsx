'use client'

type PriceUpdate = {
  ticker: string
  price: number
  previous_price: number
  change_percent: number
  direction: 'up' | 'down' | 'flat'
  timestamp: number
}

type WatchlistRow = {
  ticker: string
  price: number | null
  previous_price: number | null
  change_percent: number | null
  timestamp: number | null
}

type Position = {
  ticker: string
  quantity: number
  avg_cost: number
  current_price: number
  market_value: number
  unrealized_pnl: number
}

type PortfolioSummary = {
  cash_balance: number
  positions: Position[]
  market_value: number
  total_value: number
}

import { useEffect, useMemo, useState } from 'react'

const money = (value: number) => `$${Number(value || 0).toFixed(2)}`

function buildPath(values: number[], width: number, height: number): string {
  if (!values.length) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const spread = Math.max(max - min, 0.0001)

  return values
    .map((value, idx) => {
      const x = (idx / Math.max(values.length - 1, 1)) * width
      const y = height - ((value - min) / spread) * height
      return `${idx === 0 ? 'M' : 'L'}${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

export default function Page() {
  const [status, setStatus] = useState<'green' | 'yellow' | 'red'>('red')
  const [selectedTicker, setSelectedTicker] = useState('AAPL')
  const [watchlist, setWatchlist] = useState<WatchlistRow[]>([])
  const [prices, setPrices] = useState<Record<string, PriceUpdate>>({})
  const [history, setHistory] = useState<Record<string, number[]>>({})
  const [portfolio, setPortfolio] = useState<PortfolioSummary | null>(null)
  const [tradeTicker, setTradeTicker] = useState('AAPL')
  const [tradeQty, setTradeQty] = useState('1')
  const [tradeResult, setTradeResult] = useState('')
  const [chatInput, setChatInput] = useState('')
  const [chatLog, setChatLog] = useState<Array<{ role: 'user' | 'assistant'; text: string }>>([])

  const selectedHistory = useMemo(() => history[selectedTicker] || [], [history, selectedTicker])

  useEffect(() => {
    setTradeTicker(selectedTicker)
  }, [selectedTicker])

  async function refreshWatchlist() {
    const response = await fetch('/api/watchlist')
    const data = await response.json()
    setWatchlist(data.tickers || [])
  }

  async function refreshPortfolio() {
    const response = await fetch('/api/portfolio')
    const data = await response.json()
    setPortfolio(data)
  }

  useEffect(() => {
    void refreshWatchlist()
    void refreshPortfolio()
    const timer = setInterval(() => void refreshPortfolio(), 5000)
    return () => clearInterval(timer)
  }, [])

  useEffect(() => {
    setStatus('yellow')
    const source = new EventSource('/api/stream/prices')

    source.onopen = () => setStatus('green')
    source.onerror = () => setStatus('red')
    source.onmessage = (event) => {
      const batch = JSON.parse(event.data) as Record<string, PriceUpdate>
      setPrices((prev) => ({ ...prev, ...batch }))
      setHistory((prev) => {
        const next = { ...prev }
        for (const [ticker, update] of Object.entries(batch)) {
          const values = [...(next[ticker] || []), Number(update.price)]
          next[ticker] = values.slice(-240)
        }
        return next
      })
    }

    return () => source.close()
  }, [])

  async function submitTrade(side: 'buy' | 'sell') {
    const ticker = tradeTicker.trim().toUpperCase()
    const quantity = Number(tradeQty)

    const response = await fetch('/api/portfolio/trade', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ ticker, quantity, side }),
    })

    const payload = await response.json()
    if (!response.ok) {
      setTradeResult(payload.detail || 'Trade failed')
      return
    }

    setTradeResult(`${side.toUpperCase()} ${quantity} ${ticker} @ ${money(payload.trade.price)}`)
    setPortfolio(payload.portfolio)
  }

  async function sendChat() {
    const message = chatInput.trim()
    if (!message) return

    setChatInput('')
    setChatLog((prev) => [...prev, { role: 'user', text: message }])

    const response = await fetch('/api/chat', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ message }),
    })

    const payload = await response.json()
    setChatLog((prev) => {
      const next = [...prev, { role: 'assistant', text: payload.message || 'No response.' }]
      if (payload.trades?.length) {
        next.push({
          role: 'assistant',
          text: `Executed trades: ${payload.trades.map((t: any) => `${t.side} ${t.quantity} ${t.ticker}`).join(', ')}`,
        })
      }
      if (payload.watchlist_changes?.length) {
        next.push({
          role: 'assistant',
          text: `Watchlist updates: ${payload.watchlist_changes.map((c: any) => `${c.action} ${c.ticker}`).join(', ')}`,
        })
      }
      if (payload.errors?.length) {
        next.push({ role: 'assistant', text: `Notes: ${payload.errors.join(' | ')}` })
      }
      return next
    })

    setPortfolio(payload.portfolio)
    void refreshWatchlist()
  }

  const chartPath = buildPath(selectedHistory.slice(-120), 600, 220)
  const selectedDirection = prices[selectedTicker]?.direction
  const chartStroke = selectedDirection === 'down' ? '#f87171' : '#34d399'

  return (
    <>
      <header className="topbar">
        <div className="brand">FinAlly</div>
        <div className="stats">
          <div>
            Total Value <strong>{money(portfolio?.total_value || 0)}</strong>
          </div>
          <div>
            Cash <strong>{money(portfolio?.cash_balance || 0)}</strong>
          </div>
          <div className="statusWrap">
            Connection <span className={`dot ${status}`}></span>
          </div>
        </div>
      </header>

      <main className="grid">
        <section className="panel watchlistPanel">
          <h2>Watchlist</h2>
          <div>
            {watchlist.map((row) => {
              const update = prices[row.ticker]
              const values = history[row.ticker] || []
              const sparkPath = buildPath(values.slice(-30), 120, 22)
              const change = update?.change_percent
              const flashClass = update?.direction === 'up' ? 'flashUp' : update?.direction === 'down' ? 'flashDown' : ''

              return (
                <button
                  key={row.ticker}
                  className={`watchRow ${flashClass}`}
                  onClick={() => setSelectedTicker(row.ticker)}
                  type="button"
                >
                  <strong>{row.ticker}</strong>
                  <span>{update ? money(update.price) : '-'}</span>
                  <span className={change && change < 0 ? 'down' : 'up'}>{change == null ? '-' : `${change.toFixed(2)}%`}</span>
                  <svg className="sparkline" viewBox="0 0 120 22" preserveAspectRatio="none">
                    <path d={sparkPath} fill="none" stroke="#209dd7" strokeWidth="1.5" />
                  </svg>
                </button>
              )
            })}
          </div>
        </section>

        <section className="panel chartPanel">
          <h2>{selectedTicker}</h2>
          <svg className="mainChart" viewBox="0 0 600 220" preserveAspectRatio="none">
            <path d={chartPath} fill="none" stroke={chartStroke} strokeWidth="2.2" />
          </svg>
        </section>

        <section className="panel tradePanel">
          <h2>Trade</h2>
          <div className="tradeRow">
            <input value={tradeTicker} onChange={(e) => setTradeTicker(e.target.value.toUpperCase())} placeholder="Ticker" />
            <input value={tradeQty} onChange={(e) => setTradeQty(e.target.value)} type="number" min="0.0001" step="0.1" />
            <button className="btn buy" onClick={() => void submitTrade('buy')} type="button">Buy</button>
            <button className="btn sell" onClick={() => void submitTrade('sell')} type="button">Sell</button>
          </div>
          <div className="muted">{tradeResult}</div>
        </section>

        <section className="panel positionsPanel">
          <h2>Positions</h2>
          <table>
            <thead>
              <tr>
                <th>Ticker</th>
                <th>Qty</th>
                <th>Avg</th>
                <th>Last</th>
                <th>P&amp;L</th>
              </tr>
            </thead>
            <tbody>
              {(portfolio?.positions || []).map((position) => (
                <tr key={position.ticker}>
                  <td>{position.ticker}</td>
                  <td>{position.quantity.toFixed(3)}</td>
                  <td>{money(position.avg_cost)}</td>
                  <td>{money(position.current_price)}</td>
                  <td className={position.unrealized_pnl < 0 ? 'down' : 'up'}>{money(position.unrealized_pnl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section className="panel heatmapPanel">
          <h2>Heatmap</h2>
          <div className="heatmap">
            {(portfolio?.positions || []).map((position) => {
              const total = Math.max(portfolio?.market_value || 1, 1)
              const size = Math.max(20, Math.round((position.market_value / total) * 100))
              const bg = position.unrealized_pnl >= 0 ? 'rgba(52,211,153,0.22)' : 'rgba(248,113,113,0.22)'

              return (
                <div key={position.ticker} className="heatbox" style={{ background: bg, minHeight: `${size}px` }}>
                  <strong>{position.ticker}</strong>
                  <br />
                  {money(position.market_value)}
                </div>
              )
            })}
          </div>
        </section>

        <section className="panel chatPanel">
          <h2>AI Assistant</h2>
          <div className="chatLog">
            {chatLog.map((entry, idx) => (
              <div key={idx} className={`chatMsg ${entry.role}`}>
                {entry.role === 'user' ? 'You' : 'FinAlly'}: {entry.text}
              </div>
            ))}
          </div>
          <div className="chatRow">
            <input
              value={chatInput}
              onChange={(e) => setChatInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  void sendChat()
                }
              }}
              placeholder="Ask FinAlly..."
            />
            <button className="btn" onClick={() => void sendChat()} type="button">Send</button>
          </div>
        </section>
      </main>
    </>
  )
}
