import React, { useState, useEffect, useRef } from 'react'
import { 
  Shield, 
  Activity, 
  Users, 
  Ban, 
  AlertTriangle, 
  Terminal, 
  Play, 
  Square, 
  Sliders, 
  Search, 
  Settings as SettingsIcon,
  RefreshCw, 
  Cpu, 
  CheckCircle,
  HelpCircle,
  Database,
  Flame,
  User,
  ExternalLink,
  ChevronRight
} from 'lucide-react'
import { 
  LineChart, 
  Line, 
  XAxis, 
  YAxis, 
  CartesianGrid, 
  Tooltip, 
  Legend, 
  ResponsiveContainer, 
  PieChart, 
  Pie, 
  Cell 
} from 'recharts'

export default function App() {
  // Websocket state
  const [isConnected, setIsConnected] = useState(false)
  const [lastUpdated, setLastUpdated] = useState("")

  // Gateway Statistics
  const [stats, setStats] = useState({
    total_requests: 0,
    blocked_requests: 0,
    suspicious_clients: 0,
    active_clients: 0,
    requests_per_sec: 0.0
  })

  // Active Clients & Logs
  const [activeClients, setActiveClients] = useState([])
  const [recentLogs, setRecentLogs] = useState([])
  const [riskDistribution, setRiskDistribution] = useState({
    NORMAL: 100.0,
    SUSPICIOUS: 0.0,
    BLOCKED: 0.0
  })

  // Simulator telemetry
  const [simulator, setSimulator] = useState({
    running: false,
    sim_type: "NORMAL",
    elapsed_seconds: 0,
    stats: {
      requests_generated: 0,
      requests_allowed: 0,
      requests_throttled: 0,
      requests_blocked: 0,
      current_rate: 2.0
    }
  })

  // Selected Client Details
  const [selectedClient, setSelectedClient] = useState(null)
  
  // Real-time Traffic Chart History
  const [chartData, setChartData] = useState([])

  // Logs stream
  const [logsFeed, setLogsFeed] = useState([])

  // Filtering logs
  const [logFilterClient, setLogFilterClient] = useState("")
  const [logFilterDecision, setLogFilterDecision] = useState("")
  const [logFilterPath, setLogFilterPath] = useState("")

  // Simulator controls
  const [simType, setSimType] = useState("NORMAL")
  const [simRps, setSimRps] = useState(2)
  const [simDuration, setSimDuration] = useState(60)
  const [simClientsCount, setSimClientsCount] = useState(5)
  const [simEndpoint, setSimEndpoint] = useState("/backend/products")

  // System Configurations
  const [gatewayConfig, setGatewayConfig] = useState({
    base_rate_limit: 100,
    token_bucket_capacity: 100,
    refill_rate_secs: 60.0,
    risk_threshold_throttle: 30,
    risk_threshold_high_throttle: 60,
    risk_threshold_severe_throttle: 80,
    risk_threshold_block: 95
  })
  
  const [editableConfig, setEditableConfig] = useState({ ...gatewayConfig })
  const [configSuccessMsg, setConfigSuccessMsg] = useState("")

  // WebSocket Ref
  const wsRef = useRef(null)

  // Auto scroll logs
  const logsEndRef = useRef(null)

  // API base URL
  const backendBaseUrl = window.location.origin.includes("localhost") 
    ? "http://localhost:8000" 
    : window.location.origin.replace("3000", "8000") // handle docker port mappings

  const wsUrl = backendBaseUrl.replace("http://", "ws://") + "/ws/dashboard"

  // Fetch initial config
  const fetchConfig = async () => {
    try {
      const res = await fetch(`${backendBaseUrl}/api/config`)
      if (res.ok) {
        const data = await res.json()
        setGatewayConfig(data)
        setEditableConfig(data)
      }
    } catch (e) {
      console.error("Error fetching system configuration:", e)
    }
  }

  // Connect WebSockets
  useEffect(() => {
    fetchConfig()

    const connectWS = () => {
      console.log("Connecting to WebSocket:", wsUrl)
      const ws = new WebSocket(wsUrl)
      wsRef.current = ws

      ws.onopen = () => {
        console.log("WebSocket connected successfully.")
        setIsConnected(true)
      }

      ws.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data)
          
          if (data.event === "dashboard_update") {
            setStats(data.stats)
            setActiveClients(data.active_clients)
            setRiskDistribution(data.risk_distribution)
            setSimulator(data.simulator)
            setLastUpdated(data.timestamp)
            
            // Sync selected client detail if one is selected
            if (selectedClient) {
              const updated = data.active_clients.find(c => c.client_id === selectedClient.client_id)
              if (updated) {
                setSelectedClient(updated)
              } else {
                // client is no longer active (silent)
                // we keep selected client, but set requests/min to 0
                setSelectedClient(prev => ({ ...prev, requests_per_min: 0, status: "NORMAL" }))
              }
            }

            // Append logs
            if (data.recent_logs && data.recent_logs.length > 0) {
              setRecentLogs(data.recent_logs)
            }

            // Update real-time chart data
            setChartData(prev => {
              const timeStr = data.timestamp.split(" ")[1] || data.timestamp
              const newPoint = {
                time: timeStr,
                requests: data.stats.requests_per_sec,
                blocked: data.active_clients.filter(c => c.status === "BLOCKED").length // approximate blocked count
              }
              const updated = [...prev, newPoint]
              if (updated.length > 25) {
                updated.shift()
              }
              return updated
            })
          } 
          
          else if (data.event === "new_log") {
            setLogsFeed(prev => {
              const updated = [data.log, ...prev]
              if (updated.length > 100) {
                updated.pop()
              }
              return updated
            })
          }
        } catch (e) {
          console.error("Failed to parse websocket event:", e)
        }
      }

      ws.onerror = (e) => {
        console.error("WebSocket error:", e)
      }

      ws.onclose = () => {
        console.log("WebSocket disconnected. Retrying in 3 seconds...")
        setIsConnected(false)
        setTimeout(connectWS, 3000)
      }
    }

    connectWS()

    return () => {
      if (wsRef.current) {
        wsRef.current.close()
      }
    }
  }, [])

  // Trigger API to start/stop simulator
  const handleStartSimulation = async () => {
    try {
      const res = await fetch(`${backendBaseUrl}/api/simulation/start`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          type: simType,
          requests_per_sec: parseFloat(simRps),
          duration: parseInt(simDuration),
          num_clients: parseInt(simClientsCount),
          target_endpoint: simEndpoint
        })
      })
      if (res.ok) {
        console.log("Simulation start command issued.")
      }
    } catch (e) {
      console.error("Error starting simulation:", e)
    }
  }

  const handleStopSimulation = async () => {
    try {
      await fetch(`${backendBaseUrl}/api/simulation/stop`, { method: "POST" })
      console.log("Simulation stop command issued.")
    } catch (e) {
      console.error("Error stopping simulation:", e)
    }
  }

  // Update backend configurations
  const handleSaveConfig = async () => {
    try {
      const res = await fetch(`${backendBaseUrl}/api/config`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(editableConfig)
      })
      if (res.ok) {
        setGatewayConfig(editableConfig)
        setConfigSuccessMsg("Configuration saved successfully!")
        setTimeout(() => setConfigSuccessMsg(""), 3000)
      }
    } catch (e) {
      console.error("Error saving config:", e)
    }
  }

  // Handle client click to select
  const selectClient = (client) => {
    setSelectedClient(client)
  }

  // Helper colors mapping
  const getStatusColor = (status) => {
    switch (status) {
      case "NORMAL":
        return "text-cyber-success border-cyber-success bg-cyber-success/10"
      case "MONITORED":
        return "text-cyber-primary border-cyber-primary bg-cyber-primary/10"
      case "THROTTLED":
        return "text-cyber-warning border-cyber-warning bg-cyber-warning/10"
      case "BLOCKED":
        return "text-cyber-danger border-cyber-danger bg-cyber-danger/10"
      default:
        return "text-gray-400 border-gray-400 bg-gray-400/10"
    }
  }

  const getDecisionColor = (decision) => {
    switch (decision) {
      case "ALLOW":
        return "text-cyber-success font-semibold"
      case "THROTTLE":
        return "text-cyber-warning font-semibold"
      case "BLOCK":
        return "text-cyber-danger font-semibold font-bold animate-pulse"
      default:
        return "text-gray-400"
    }
  }

  const getRiskColor = (score) => {
    if (score < 30) return "text-cyber-success"
    if (score < 60) return "text-cyber-primary"
    if (score < 80) return "text-cyber-warning"
    return "text-cyber-danger font-semibold"
  }

  // Filter logs logic
  const filteredLogs = logsFeed.filter(log => {
    if (logFilterClient && !log.client_id.toLowerCase().includes(logFilterClient.toLowerCase())) return false
    if (logFilterDecision && log.decision !== logFilterDecision) return false
    if (logFilterPath && !log.path.toLowerCase().includes(logFilterPath.toLowerCase())) return false
    return true
  })

  // Format pie chart data
  const pieData = [
    { name: 'Normal', value: riskDistribution.NORMAL || 0, color: '#10b981' },
    { name: 'Suspicious', value: riskDistribution.SUSPICIOUS || 0, color: '#f59e0b' },
    { name: 'Blocked', value: riskDistribution.BLOCKED || 0, color: '#ef4444' }
  ].filter(d => d.value > 0)

  return (
    <div className="min-h-screen bg-cyber-bg px-4 py-6 text-cyber-text antialiased">
      {/* HEADER SECTION */}
      <header className="mb-6 flex flex-col items-center justify-between border-b border-cyber-border pb-4 md:flex-row">
        <div className="flex items-center gap-3">
          <div className="relative rounded-lg bg-cyber-primary/20 p-2 text-cyber-primary border border-cyber-primary/30 shadow-[0_0_15px_rgba(56,189,248,0.25)]">
            <Shield className="h-8 w-8 animate-pulse" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight text-white md:text-3xl">
              Sentinel<span className="text-cyber-primary">Gate</span>
            </h1>
            <p className="text-xs text-slate-400 tracking-wider">ADAPTIVE SECURITY GATEWAY & DESTRUCTION HUB</p>
          </div>
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-4 md:mt-0">
          <div className="flex items-center gap-2 rounded-md bg-cyber-card border border-cyber-border px-3 py-1.5 text-xs">
            <Cpu className="h-4 w-4 text-cyber-primary" />
            <span className="text-slate-400">Gateway Nodes:</span>
            <span className="font-mono text-emerald-400 font-semibold">2 Active</span>
          </div>

          <div className="flex items-center gap-2 rounded-md bg-cyber-card border border-cyber-border px-3 py-1.5 text-xs">
            <span className={`inline-block h-2 w-2 rounded-full ${isConnected ? "bg-cyber-success animate-ping" : "bg-cyber-danger"}`}></span>
            <span className="text-slate-400">Control Link:</span>
            <span className={`font-semibold ${isConnected ? "text-cyber-success" : "text-cyber-danger"}`}>
              {isConnected ? "ONLINE" : "OFFLINE"}
            </span>
          </div>

          <span className="font-mono text-xs text-slate-500">
            SEC_OPS: {lastUpdated ? lastUpdated : "POLLING..."}
          </span>
        </div>
      </header>

      {/* OVERVIEW STATS CARDS */}
      <section className="mb-6 grid grid-cols-2 gap-4 sm:grid-cols-4 lg:grid-cols-5">
        <div className="rounded-lg border border-cyber-border bg-cyber-card p-4 transition-all hover:border-cyber-primary/40">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>TOTAL TELEMETRY</span>
            <Activity className="h-4 w-4 text-cyber-primary" />
          </div>
          <p className="text-2xl font-bold font-mono text-white tracking-tight">
            {stats.total_requests.toLocaleString()}
          </p>
          <span className="text-[10px] text-slate-500 font-mono">Requests processed</span>
        </div>

        <div className="rounded-lg border border-cyber-border bg-cyber-card p-4 transition-all hover:border-cyber-danger/40">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>ATTACKS DEFEATED</span>
            <Ban className="h-4 w-4 text-cyber-danger" />
          </div>
          <p className="text-2xl font-bold font-mono text-cyber-danger tracking-tight">
            {stats.blocked_requests.toLocaleString()}
          </p>
          <span className="text-[10px] text-slate-500 font-mono">Malicious requests blocked</span>
        </div>

        <div className="rounded-lg border border-cyber-border bg-cyber-card p-4 transition-all hover:border-cyber-warning/40">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>SUSPICIOUS CLIENTS</span>
            <AlertTriangle className="h-4 w-4 text-cyber-warning" />
          </div>
          <p className="text-2xl font-bold font-mono text-cyber-warning tracking-tight">
            {stats.suspicious_clients}
          </p>
          <span className="text-[10px] text-slate-500 font-mono">Threat Index &gt; 30</span>
        </div>

        <div className="rounded-lg border border-cyber-border bg-cyber-card p-4 transition-all hover:border-cyber-success/40">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>ACTIVE CLIENTS</span>
            <Users className="h-4 w-4 text-cyber-success" />
          </div>
          <p className="text-2xl font-bold font-mono text-cyber-success tracking-tight">
            {stats.active_clients}
          </p>
          <span className="text-[10px] text-slate-500 font-mono">Interacting in 60s</span>
        </div>

        <div className="col-span-2 rounded-lg border border-cyber-border bg-cyber-card p-4 sm:col-span-4 lg:col-span-1 transition-all hover:border-cyber-primary/40">
          <div className="flex items-center justify-between text-xs text-slate-400 mb-1">
            <span>INCOMING BANDWIDTH</span>
            <RefreshCw className="h-4 w-4 text-cyber-primary animate-spin-slow" />
          </div>
          <p className="text-2xl font-bold font-mono text-white tracking-tight">
            {stats.requests_per_sec.toFixed(1)} <span className="text-xs text-slate-400">RPS</span>
          </p>
          <span className="text-[10px] text-slate-500 font-mono">System-wide requests/sec</span>
        </div>
      </section>

      {/* TOP GRID: GRAPH & RISK DISTRIBUTION */}
      <section className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Real-time Traffic Graph */}
        <div className="lg:col-span-8 rounded-lg border border-cyber-border bg-cyber-card p-4 flex flex-col">
          <h2 className="text-sm font-semibold tracking-wide text-white uppercase mb-4 flex items-center gap-2">
            <Activity className="h-4 w-4 text-cyber-primary" /> Live Gateway Telemetry Stream
          </h2>
          <div className="h-[280px] w-full flex-grow">
            <ResponsiveContainer width="100%" height="100%">
              <LineChart data={chartData} margin={{ top: 10, right: 10, left: -20, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
                <XAxis dataKey="time" stroke="#64748b" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                <YAxis stroke="#64748b" style={{ fontSize: 10, fontFamily: 'monospace' }} />
                <Tooltip 
                  contentStyle={{ backgroundColor: '#111622', border: '1px solid #1e293b', color: '#e2e8f0', borderRadius: '6px' }}
                  labelStyle={{ color: '#38bdf8', fontWeight: 'bold' }}
                />
                <Legend style={{ fontSize: 12 }} />
                <Line type="monotone" name="Global Requests/Sec" dataKey="requests" stroke="#38bdf8" strokeWidth={2} dot={false} activeDot={{ r: 4 }} />
                <Line type="monotone" name="Blocked Clients" dataKey="blocked" stroke="#ef4444" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          </div>
        </div>

        {/* Risk Distribution Pie Chart */}
        <div className="lg:col-span-4 rounded-lg border border-cyber-border bg-cyber-card p-4 flex flex-col justify-between">
          <div>
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase mb-4 flex items-center gap-2">
              <Shield className="h-4 w-4 text-cyber-primary" /> Threat Level Distribution
            </h2>
            <div className="flex justify-center h-[180px]">
              {pieData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%">
                  <PieChart>
                    <Pie
                      data={pieData}
                      cx="50%"
                      cy="50%"
                      innerRadius={60}
                      outerRadius={80}
                      paddingAngle={5}
                      dataKey="value"
                    >
                      {pieData.map((entry, index) => (
                        <Cell key={`cell-${index}`} fill={entry.color} />
                      ))}
                    </Pie>
                    <Tooltip contentStyle={{ backgroundColor: '#111622', border: '1px solid #1e293b' }} />
                  </PieChart>
                </ResponsiveContainer>
              ) : (
                <div className="flex items-center justify-center text-slate-500 text-xs">
                  Awaiting Telemetry...
                </div>
              )}
            </div>
          </div>
          
          <div className="grid grid-cols-3 gap-2 border-t border-cyber-border pt-4 text-center text-xs">
            <div>
              <div className="font-bold text-cyber-success">{riskDistribution.NORMAL}%</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Normal</div>
            </div>
            <div>
              <div className="font-bold text-cyber-warning">{riskDistribution.SUSPICIOUS}%</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Suspicious</div>
            </div>
            <div>
              <div className="font-bold text-cyber-danger">{riskDistribution.BLOCKED}%</div>
              <div className="text-[10px] text-slate-500 uppercase tracking-wide">Blocked</div>
            </div>
          </div>
        </div>
      </section>

      {/* MIDDLE GRID: ACTIVE CLIENTS TABLE & CLIENT DETAIL PANEL */}
      <section className="mb-6 grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Clients Table */}
        <div className="lg:col-span-8 rounded-lg border border-cyber-border bg-cyber-card p-4 flex flex-col">
          <div className="mb-4 flex items-center justify-between">
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase flex items-center gap-2">
              <Users className="h-4 w-4 text-cyber-primary" /> Active Clients Threat Registry
            </h2>
            <span className="rounded-full bg-cyber-primary/10 px-2 py-0.5 text-xs text-cyber-primary border border-cyber-primary/20">
              {activeClients.length} tracked
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse">
              <thead>
                <tr className="border-b border-cyber-border text-xs text-slate-400 uppercase tracking-wide">
                  <th className="pb-3 pl-2">Client ID/IP</th>
                  <th className="pb-3 text-right">Traffic/Min</th>
                  <th className="pb-3 text-right">Error Rate</th>
                  <th className="pb-3 text-center">Threat Index</th>
                  <th className="pb-3 text-center">Status</th>
                  <th className="pb-3 text-right">Rate Limit</th>
                  <th className="pb-3 text-right pr-2">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-cyber-border text-xs font-mono">
                {activeClients.length > 0 ? (
                  activeClients.map((client) => (
                    <tr 
                      key={client.client_id} 
                      className={`hover:bg-cyber-cardlight transition-colors cursor-pointer ${selectedClient?.client_id === client.client_id ? "bg-cyber-primary/5" : ""}`}
                      onClick={() => selectClient(client)}
                    >
                      <td className="py-3 pl-2 text-white font-semibold flex items-center gap-1.5">
                        <User className="h-3 w-3 text-slate-400" />
                        {client.client_id}
                      </td>
                      <td className="py-3 text-right text-slate-300 font-bold">{client.requests_per_min} rpm</td>
                      <td className="py-3 text-right text-slate-300">{(client.error_rate * 100).toFixed(0)}%</td>
                      <td className={`py-3 text-center font-bold ${getRiskColor(client.risk_score)}`}>
                        {client.risk_score}
                      </td>
                      <td className="py-3 text-center">
                        <span className={`inline-block px-2 py-0.5 rounded border text-[10px] uppercase font-bold tracking-wider ${getStatusColor(client.status)}`}>
                          {client.status}
                        </span>
                      </td>
                      <td className="py-3 text-right text-slate-300">{client.current_limit}</td>
                      <td className="py-3 text-right pr-2">
                        <button 
                          className="text-cyber-primary hover:text-white hover:underline flex items-center gap-1 ml-auto text-[10px]"
                          onClick={(e) => {
                            e.stopPropagation()
                            selectClient(client)
                          }}
                        >
                          Inspect <ChevronRight className="h-3. w-3" />
                        </button>
                      </td>
                    </tr>
                  ))
                ) : (
                  <tr>
                    <td colSpan="7" className="py-8 text-center text-slate-500 font-sans">
                      No active client traffic recorded. Start a simulator load to generate metrics.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Client Detail Side Panel */}
        <div className="lg:col-span-4 rounded-lg border border-cyber-border bg-cyber-card p-4 flex flex-col justify-between">
          {selectedClient ? (
            <div className="flex flex-col h-full justify-between">
              <div>
                <div className="mb-4 flex items-center justify-between border-b border-cyber-border pb-2">
                  <div className="flex items-center gap-2">
                    <User className="h-4 w-4 text-cyber-primary" />
                    <span className="font-semibold text-white tracking-wide">{selectedClient.client_id}</span>
                  </div>
                  <button 
                    className="text-[10px] text-slate-500 hover:text-white"
                    onClick={() => setSelectedClient(null)}
                  >
                    Clear
                  </button>
                </div>

                {/* Threat index gauge */}
                <div className="mb-4 text-center rounded bg-cyber-bg p-3 border border-cyber-border">
                  <span className="text-[10px] text-slate-500 block uppercase tracking-wide">Threat Severity Score</span>
                  <span className={`text-4xl font-extrabold font-mono block my-1 ${getRiskColor(selectedClient.risk_score)}`}>
                    {selectedClient.risk_score}<span className="text-xs text-slate-400">/100</span>
                  </span>
                  <span className={`inline-block px-2.5 py-0.5 rounded border text-[9px] uppercase font-bold tracking-wider ${getStatusColor(selectedClient.status)}`}>
                    {selectedClient.status}
                  </span>
                </div>

                {/* Metrics detail */}
                <div className="space-y-2 text-xs">
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Client Rate Limit:</span>
                    <span className="text-white font-mono">{selectedClient.current_limit}</span>
                  </div>
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Requests / min:</span>
                    <span className="text-white font-mono">{selectedClient.requests_per_min} rpm</span>
                  </div>
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Error Frequency:</span>
                    <span className="text-white font-mono">{(selectedClient.error_rate * 100).toFixed(0)}%</span>
                  </div>
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Burstiness Coefficient:</span>
                    <span className="text-white font-mono">{selectedClient.burstiness.toFixed(4)}</span>
                  </div>
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Unique Targets Hit:</span>
                    <span className="text-white font-mono">{selectedClient.unique_endpoints} endpoints</span>
                  </div>
                  <div className="flex justify-between border-b border-cyber-border/40 pb-1">
                    <span className="text-slate-400">Last Telemetry Ping:</span>
                    <span className="text-slate-300 font-mono text-[10px]">{selectedClient.last_activity.split(" ")[1] || selectedClient.last_activity}</span>
                  </div>
                </div>

                {/* Triggers/Reasons */}
                <div className="mt-4">
                  <span className="text-[10px] text-slate-500 uppercase tracking-wide block mb-1">Threat Assessment Diagnostics</span>
                  <div className="space-y-1.5">
                    {selectedClient.reasons && selectedClient.reasons.length > 0 ? (
                      selectedClient.reasons.map((r, i) => (
                        <div key={i} className="flex items-start gap-1 text-[11px] text-cyber-warning bg-cyber-warning/5 border border-cyber-warning/10 rounded p-1.5">
                          <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
                          <span>{r}</span>
                        </div>
                      ))
                    ) : (
                      <div className="flex items-center gap-1.5 text-[11px] text-cyber-success bg-cyber-success/5 border border-cyber-success/10 rounded p-1.5">
                        <CheckCircle className="h-3 w-3" />
                        <span>Client behavior aligns with normal thresholds. No flags.</span>
                      </div>
                    )}
                  </div>
                </div>
              </div>
              
              <div className="mt-4 pt-4 border-t border-cyber-border text-center">
                <span className="text-[10px] text-slate-500 uppercase block mb-2">Manual Firewall Actions</span>
                <button 
                  className={`w-full py-1.5 rounded text-xs font-semibold ${
                    selectedClient.status === "BLOCKED" 
                    ? "bg-emerald-600 hover:bg-emerald-500 text-white" 
                    : "bg-red-950 hover:bg-red-900 text-red-200 border border-red-800"
                  }`}
                  onClick={async () => {
                    // In a production WAF, we would trigger a manual block/unblock.
                    // For the simulator, we can simulate an immediate action by setting/clearing risk.
                    try {
                      // Trigger a dynamic risk jump by generating target requests or config
                      console.log("Manual firewall override triggered.")
                    } catch (e) {
                      console.error(e)
                    }
                  }}
                >
                  {selectedClient.status === "BLOCKED" ? "PROVISION IMMEDIATE UNBLOCK" : "MANUALLY NULLIFY / ISOLATE CLIENT"}
                </button>
              </div>
            </div>
          ) : (
            <div className="flex flex-col items-center justify-center text-center h-full py-8 text-slate-500">
              <Shield className="h-10 w-10 text-slate-700 mb-2" />
              <p className="text-xs">Select an active client from the threat registry table to view real-time behavioral features and diagnostics.</p>
            </div>
          )}
        </div>
      </section>

      {/* BOTTOM GRID: REAL-TIME LOG TERMINAL & SIMULATION / LIMIT CONFIG */}
      <section className="grid grid-cols-1 gap-6 lg:grid-cols-12">
        {/* Terminal logs */}
        <div className="lg:col-span-7 rounded-lg border border-cyber-border bg-cyber-card p-4 flex flex-col h-[400px]">
          <div className="mb-4 flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase flex items-center gap-2">
              <Terminal className="h-4 w-4 text-cyber-primary" /> Gateway Real-time Log Feed
            </h2>
            
            {/* Filtering */}
            <div className="flex flex-wrap items-center gap-2">
              <div className="relative">
                <input 
                  type="text" 
                  placeholder="Filter client..." 
                  className="bg-cyber-bg border border-cyber-border rounded px-2 py-1 text-[10px] w-24 focus:outline-none focus:border-cyber-primary"
                  value={logFilterClient}
                  onChange={(e) => setLogFilterClient(e.target.value)}
                />
              </div>
              <select 
                className="bg-cyber-bg border border-cyber-border rounded px-2 py-1 text-[10px] focus:outline-none focus:border-cyber-primary text-slate-400"
                value={logFilterDecision}
                onChange={(e) => setLogFilterDecision(e.target.value)}
              >
                <option value="">All Decisions</option>
                <option value="ALLOW">ALLOW</option>
                <option value="THROTTLE">THROTTLE</option>
                <option value="BLOCK">BLOCK</option>
              </select>
              <button 
                className="text-[10px] text-slate-500 hover:text-white"
                onClick={() => {
                  setLogFilterClient("")
                  setLogFilterDecision("")
                  setLogFilterPath("")
                }}
              >
                Reset
              </button>
            </div>
          </div>

          {/* Terminal Box */}
          <div className="flex-grow bg-black rounded p-3 overflow-y-auto font-mono text-[10px] text-emerald-400/90 border border-cyber-border">
            <div className="border-b border-emerald-950 pb-1 mb-2 text-slate-500 flex justify-between">
              <span>SENTINELGATE SYSLOG DEPLOYMENT v1.0.0</span>
              <span>STREAM: ACTIVE</span>
            </div>
            
            <div className="space-y-1">
              {filteredLogs.length > 0 ? (
                filteredLogs.map((log, index) => (
                  <div key={index} className="hover:bg-slate-900/50 py-0.5 rounded px-1 flex flex-wrap gap-1 leading-relaxed">
                    <span className="text-slate-500">[{log.timestamp}]</span>
                    <span className="text-sky-400 font-semibold">{log.client_id}</span>
                    <span className="text-slate-400">|</span>
                    <span className="text-yellow-500">{log.method}</span>
                    <span className="text-emerald-300 select-all">{log.path}</span>
                    <span className="text-slate-400">|</span>
                    <span className="text-slate-400">{log.status_code}</span>
                    <span className="text-slate-400">({log.latency_ms}ms)</span>
                    <span className="text-slate-400">|</span>
                    <span className="text-slate-400 font-bold">Threat: {log.risk_score}</span>
                    <span className="text-slate-400">|</span>
                    <span className={getDecisionColor(log.decision)}>{log.decision}</span>
                    {log.reason && log.reason !== "None" && (
                      <span className="text-red-400 text-[9px] italic">({log.reason})</span>
                    )}
                  </div>
                ))
              ) : (
                <div className="text-slate-600 italic py-4 terminal-cursor">
                  Waiting for requests. Simulated traffic must be started to stream live gateway filters...
                </div>
              )}
            </div>
          </div>
        </div>

        {/* Controls: Simulator & Gateway Configurations */}
        <div className="lg:col-span-5 flex flex-col gap-6">
          {/* Simulator Panel */}
          <div className="rounded-lg border border-cyber-border bg-cyber-card p-4 flex-grow">
            <div className="mb-3 flex items-center justify-between">
              <h2 className="text-sm font-semibold tracking-wide text-white uppercase flex items-center gap-2">
                <Flame className="h-4 w-4 text-cyber-danger" /> Local Attack Simulator Panel
              </h2>
              <span className={`px-2 py-0.5 rounded text-[10px] uppercase font-bold tracking-wide ${
                simulator.running ? "bg-cyber-danger/10 text-cyber-danger border border-cyber-danger/30 animate-pulse" : "bg-slate-800 text-slate-400 border border-slate-700"
              }`}>
                {simulator.running ? `ATTACK ACTIVE (${simulator.elapsed_seconds}s)` : "IDLE"}
              </span>
            </div>

            {/* Attack Types */}
            <div className="mb-4 grid grid-cols-5 gap-1.5">
              {[
                { name: "Normal", type: "NORMAL" },
                { name: "Burst", type: "BURST" },
                { name: "Scraper", type: "BOT" },
                { name: "Brute", type: "BRUTE_FORCE" },
                { name: "DDoS", type: "DDOS" }
              ].map((btn) => (
                <button
                  key={btn.type}
                  className={`py-1.5 rounded text-xs font-semibold border transition-all ${
                    simType === btn.type
                    ? "bg-cyber-danger/25 text-white border-cyber-danger shadow-[0_0_10px_rgba(239,68,68,0.15)]"
                    : "bg-cyber-bg hover:bg-cyber-cardlight text-slate-400 border-cyber-border"
                  }`}
                  onClick={() => {
                    setSimType(btn.type)
                    // Autofill suggestions
                    if (btn.type === "NORMAL") { setSimRps(2); setSimEndpoint("/backend/products"); }
                    else if (btn.type === "BURST") { setSimRps(20); setSimEndpoint("/backend/profile"); }
                    else if (btn.type === "BOT") { setSimRps(15); setSimEndpoint("/backend/products"); }
                    else if (btn.type === "BRUTE_FORCE") { setSimRps(10); setSimEndpoint("/backend/login"); }
                    else if (btn.type === "DDOS") { setSimRps(30); setSimEndpoint("/backend/search"); }
                  }}
                >
                  {btn.name}
                </button>
              ))}
            </div>

            {/* Inputs grid */}
            <div className="mb-4 grid grid-cols-2 gap-3 text-xs">
              <div>
                <label className="text-slate-400 block mb-1">Target Endpoint</label>
                <input 
                  type="text" 
                  className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono focus:outline-none focus:border-cyber-primary"
                  value={simEndpoint}
                  onChange={(e) => setSimEndpoint(e.target.value)}
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">Request Frequency (RPS)</label>
                <input 
                  type="number" 
                  min="1"
                  max="100"
                  className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono focus:outline-none focus:border-cyber-primary"
                  value={simRps}
                  onChange={(e) => setSimRps(parseInt(e.target.value) || 1)}
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">Duration (seconds)</label>
                <input 
                  type="number" 
                  min="5"
                  className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono focus:outline-none focus:border-cyber-primary"
                  value={simDuration}
                  onChange={(e) => setSimDuration(parseInt(e.target.value) || 30)}
                />
              </div>
              <div>
                <label className="text-slate-400 block mb-1">DDOS Bot Instances</label>
                <input 
                  type="number" 
                  min="1"
                  max="20"
                  disabled={simType !== "DDOS"}
                  className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono focus:outline-none focus:border-cyber-primary disabled:opacity-30"
                  value={simClientsCount}
                  onChange={(e) => setSimClientsCount(parseInt(e.target.value) || 1)}
                />
              </div>
            </div>

            {/* Simulator Live Stats */}
            {simulator.running && (
              <div className="mb-4 rounded bg-cyber-bg border border-cyber-border p-2.5 font-mono text-[10px] grid grid-cols-2 gap-2 text-slate-300">
                <div>Generated: <span className="text-white font-bold">{simulator.stats.requests_generated}</span></div>
                <div>Allowed: <span className="text-cyber-success font-bold">{simulator.stats.requests_allowed}</span></div>
                <div>Throttled: <span className="text-cyber-warning font-bold">{simulator.stats.requests_throttled}</span></div>
                <div>Blocked: <span className="text-cyber-danger font-bold">{simulator.stats.requests_blocked}</span></div>
              </div>
            )}

            {/* Trigger buttons */}
            <div className="flex gap-2">
              <button 
                className="flex-grow flex items-center justify-center gap-1.5 py-2 rounded text-xs font-semibold bg-cyber-danger text-white hover:bg-red-500 shadow-[0_0_15px_rgba(239,68,68,0.25)] transition-all"
                onClick={handleStartSimulation}
              >
                <Play className="h-3.5 w-3.5" /> DEPLOY ATTACK SEQUENCE
              </button>
              <button 
                className="flex-grow flex items-center justify-center gap-1.5 py-2 rounded text-xs font-semibold bg-slate-800 text-slate-300 border border-slate-700 hover:bg-slate-700 transition-all"
                onClick={handleStopSimulation}
              >
                <Square className="h-3.5 w-3.5" /> SHUTDOWN SIM
              </button>
            </div>
          </div>

          {/* Config Editor Panel */}
          <div className="rounded-lg border border-cyber-border bg-cyber-card p-4">
            <h2 className="text-sm font-semibold tracking-wide text-white uppercase mb-3 flex items-center gap-2">
              <SettingsIcon className="h-4 w-4 text-cyber-primary" /> Adaptive Rate-Limiter Thresholds
            </h2>
            
            <div className="space-y-3 text-xs">
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="text-slate-400 block mb-0.5">Capacity (Max tokens)</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono text-[11px]"
                    value={editableConfig.token_bucket_capacity}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, token_bucket_capacity: parseInt(e.target.value) || 100 }))}
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-0.5">Refill Base Limit</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-2 py-1 text-white font-mono text-[11px]"
                    value={editableConfig.base_rate_limit}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, base_rate_limit: parseInt(e.target.value) || 100 }))}
                  />
                </div>
              </div>

              <div className="grid grid-cols-4 gap-2">
                <div>
                  <label className="text-slate-400 block mb-0.5 text-[9px] uppercase">Monitored (&gt;)</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-1.5 py-1 text-white font-mono text-[11px] text-center"
                    value={editableConfig.risk_threshold_throttle}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, risk_threshold_throttle: parseInt(e.target.value) || 30 }))}
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-0.5 text-[9px] uppercase">Throttle 30 (&gt;)</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-1.5 py-1 text-white font-mono text-[11px] text-center"
                    value={editableConfig.risk_threshold_high_throttle}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, risk_threshold_high_throttle: parseInt(e.target.value) || 60 }))}
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-0.5 text-[9px] uppercase">Throttle 10 (&gt;)</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-1.5 py-1 text-white font-mono text-[11px] text-center"
                    value={editableConfig.risk_threshold_severe_throttle}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, risk_threshold_severe_throttle: parseInt(e.target.value) || 80 }))}
                  />
                </div>
                <div>
                  <label className="text-slate-400 block mb-0.5 text-[9px] uppercase">Block (&gt;)</label>
                  <input 
                    type="number" 
                    className="bg-cyber-bg border border-cyber-border rounded w-full px-1.5 py-1 text-white font-mono text-[11px] text-center"
                    value={editableConfig.risk_threshold_block}
                    onChange={(e) => setEditableConfig(prev => ({ ...prev, risk_threshold_block: parseInt(e.target.value) || 95 }))}
                  />
                </div>
              </div>

              {configSuccessMsg && (
                <div className="text-[11px] text-cyber-success text-center font-semibold bg-cyber-success/5 border border-cyber-success/15 py-1 rounded">
                  {configSuccessMsg}
                </div>
              )}

              <button 
                className="w-full py-1.5 rounded text-xs font-semibold bg-cyber-primary text-black hover:bg-sky-400 transition-all"
                onClick={handleSaveConfig}
              >
                APPLY DYNAMIC LIMIT POLICIES
              </button>
            </div>
          </div>
        </div>
      </section>
    </div>
  )
}
