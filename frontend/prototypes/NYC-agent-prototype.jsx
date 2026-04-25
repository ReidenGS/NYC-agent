import React, { useState, useEffect, useRef } from 'react';
import { 
  Map as MapIcon, 
  BarChart3, 
  Settings2, 
  ShieldCheck, 
  Train, 
  DollarSign, 
  Coffee, 
  ChevronRight,
  User,
  Navigation,
  MessageSquare,
  Maximize2,
  Minimize2,
  Activity,
  CloudSun,
  AlertCircle,
  Loader2
} from 'lucide-react';

/**
 * ==========================================
 * 1. Mock Data (同步 Schema Contract)
 * ==========================================
 */
const MOCK_PROFILE = {
  target_areas: ["Astoria", "Long Island City"],
  budget: { min: 2500, max: 3800, currency: "USD" },
  preferences: ["Safe", "Quiet"],
  weights: { safety: 0.85, rent: 0.6, transit: 0.9, amenities: 0.4, entertainment: 0.7 }
};

const MOCK_AREA_METRICS = [
  {
    area_id: "QN01",
    name: "Astoria",
    median_rent: 2850, 
    metrics: { safety: 85, rent_index: 70, transit_score: 90, amenities: 65 },
    coords: { lng: -73.9196, lat: 40.7686 } 
  },
  {
    area_id: "QN02",
    name: "Long Island City",
    median_rent: 3600,
    metrics: { safety: 75, rent_index: 40, transit_score: 95, amenities: 88 },
    coords: { lng: -73.9485, lat: 40.7447 }
  }
];

const MOCK_WEATHER = {
  temp: 64,
  unit: "F",
  condition: "多云 (Cloudy)",
  aqi: "Good (32)",
  activity: "繁忙"
};

/**
 * ==========================================
 * 2. Real MapLibre Component (带有健壮的加载器)
 * ==========================================
 */

const loadMapLibreResources = () => {
  return new Promise((resolve, reject) => {
    if (window.maplibregl) {
      resolve(window.maplibregl);
      return;
    }

    // 切换至更稳定的 cdnjs 节点
    if (!document.getElementById('maplibre-css')) {
      const link = document.createElement('link');
      link.id = 'maplibre-css';
      link.rel = 'stylesheet';
      link.href = 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/3.6.2/maplibre-gl.css';
      document.head.appendChild(link);
    }

    let script = document.getElementById('maplibre-js');
    if (!script) {
      script = document.createElement('script');
      script.id = 'maplibre-js';
      script.src = 'https://cdnjs.cloudflare.com/ajax/libs/maplibre-gl/3.6.2/maplibre-gl.js';
      // 移除 crossOrigin='anonymous' 防止沙盒环境下的严格拦截
      
      script.onload = () => {
        if (window.maplibregl) resolve(window.maplibregl);
        else reject(new Error("MapLibre 脚本已加载但未找到对象"));
      };
      
      script.onerror = () => reject(new Error("Failed to load MapLibre GL JS from CDN"));
      document.head.appendChild(script);
    } else {
      let attempts = 0;
      const interval = setInterval(() => {
        if (window.maplibregl) {
          clearInterval(interval);
          resolve(window.maplibregl);
        }
        if (attempts++ > 100) { // 延长至 10 秒超时
          clearInterval(interval);
          reject(new Error("MapLibre script injection timeout"));
        }
      }, 100);
    }
  });
};

const MapLibrePanel = ({ children }) => {
  const mapContainer = useRef(null);
  const [mapStatus, setMapStatus] = useState('loading'); 
  const [errorMsg, setErrorMsg] = useState('');

  useEffect(() => {
    let mapInstance = null;
    let isMounted = true;

    const initMap = async () => {
      try {
        const maplibregl = await loadMapLibreResources();
        
        if (!isMounted || !mapContainer.current) return;
        if (mapContainer.current.children.length > 0) return; 

        // 初始化地图
        mapInstance = new maplibregl.Map({
          container: mapContainer.current,
          style: 'https://basemaps.cartocdn.com/gl/positron-gl-style/style.json',
          center: [-73.93, 40.755], 
          zoom: 12.5,
          attributionControl: false
        });

        mapInstance.on('load', () => {
          if (isMounted) setMapStatus('ready');
          
          // 添加区域标记点
          MOCK_AREA_METRICS.forEach(area => {
            const el = document.createElement('div');
            el.className = 'bg-blue-600 text-white text-[10px] font-bold px-2 py-1 rounded-md shadow-lg whitespace-nowrap transform -translate-y-4 cursor-pointer hover:scale-110 transition-transform flex items-center gap-1 border border-white/20';
            el.innerHTML = `${area.name} <span class="opacity-80">|</span> <span class="font-mono text-blue-100">$${area.median_rent}</span>`;
            
            new maplibregl.Marker({ element: el })
              .setLngLat([area.coords.lng, area.coords.lat])
              .addTo(mapInstance);
          });
        });

        // 仅在控制台输出非致命错误，不阻断页面渲染
        mapInstance.on('error', (e) => {
          console.warn("MapLibre non-fatal error:", e);
        });

      } catch (err) {
        console.error("MapLibre Initialization Error:", err);
        if (isMounted) {
          setMapStatus('error');
          setErrorMsg(err.message || '地图引擎加载超时');
        }
      }
    };

    initMap();

    return () => {
      isMounted = false;
      if (mapInstance) mapInstance.remove();
    };
  }, []);

  return (
    <div className="relative flex-1 h-full overflow-hidden bg-[#e5e7eb]">
      <div 
        ref={mapContainer} 
        className={`absolute inset-0 transition-opacity duration-1000 ${mapStatus === 'ready' ? 'opacity-100' : 'opacity-0'}`} 
      />
      
      {mapStatus === 'loading' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-400 bg-[#e5e7eb]">
          <Loader2 size={32} className="animate-spin mb-4 text-blue-500" />
          <p className="text-xs font-bold uppercase tracking-widest">INITIALIZING MAP ENGINE...</p>
        </div>
      )}

      {mapStatus === 'error' && (
        <div className="absolute inset-0 flex flex-col items-center justify-center text-gray-500 bg-[#e5e7eb]">
          <MapIcon size={48} className="mb-4 opacity-50" />
          <div className="flex items-center gap-2 text-red-500 bg-red-50 px-3 py-1.5 rounded-lg border border-red-100 shadow-sm">
            <AlertCircle size={14} />
            <span className="text-xs font-bold">{errorMsg}</span>
          </div>
          <p className="text-[10px] mt-2 opacity-70">右侧业务功能不受影响，仍可继续使用</p>
        </div>
      )}

      <div className="absolute inset-0 pointer-events-none">
        {children}
      </div>
    </div>
  );
};

/**
 * ==========================================
 * 3. UI Panels
 * ==========================================
 */

const DashboardCard = ({ title, icon: Icon, isExpanded, onToggle, children, badge, variant = "light" }) => (
  <div 
    onClick={(e) => { e.stopPropagation(); onToggle(); }}
    onMouseDown={(e) => e.stopPropagation()} 
    onWheel={(e) => e.stopPropagation()}     
    className={`backdrop-blur-xl border shadow-2xl rounded-2xl p-4 pointer-events-auto cursor-pointer transition-all duration-500 ease-in-out transform flex-shrink-0 relative overflow-hidden group ${
      isExpanded 
        ? 'w-80 scale-100 z-30 shadow-blue-500/10' 
        : 'w-52 scale-[0.98] opacity-80 hover:opacity-100 hover:scale-100 hover:shadow-lg z-10'
    } ${
      variant === "dark" 
        ? 'bg-neutral-900/90 border-white/10 text-white' 
        : 'bg-white/80 border-white/40 text-gray-800'
    }`}
  >
    <div className="flex items-center justify-between mb-3 relative z-10">
      <div className="flex items-center gap-2">
        {Icon && <Icon size={14} className={variant === "dark" ? "text-blue-400" : "text-blue-600"} />}
        <h3 className="text-[10px] font-bold uppercase tracking-widest truncate">{title}</h3>
      </div>
      <div className="flex items-center gap-2">
        {badge && <span className="text-[8px] px-1.5 py-0.5 bg-blue-500/20 text-blue-600 rounded font-bold">{badge}</span>}
        {isExpanded ? <Minimize2 size={12} className="opacity-30 hover:opacity-100 transition-opacity" /> : <Maximize2 size={12} className="opacity-30 group-hover:opacity-100 transition-opacity" />}
      </div>
    </div>
    <div className={`transition-all duration-500 relative z-10 ${isExpanded ? 'opacity-100 max-h-[500px]' : 'opacity-0 max-h-0 overflow-hidden'}`}>
      {children}
    </div>
    {!isExpanded && <div className="mt-1 text-[9px] font-medium text-gray-500/70 truncate italic relative z-10">点击查看详细指标</div>}
    
    {variant === "light" && <div className="absolute -top-10 -right-10 w-24 h-24 bg-blue-500/5 rounded-full blur-xl pointer-events-none" />}
  </div>
);

const ProfileStatePanel = ({ profile, isExpanded, onToggle }) => (
  <DashboardCard title="已感知需求" icon={User} isExpanded={isExpanded} onToggle={onToggle}>
    <div className="space-y-4 pt-2">
      <div className="flex flex-wrap gap-1.5">
        {profile.target_areas.map(a => (<span key={a} className="text-[10px] bg-blue-50 text-blue-700 px-2.5 py-1 rounded-md border border-blue-100 font-bold shadow-sm">{a}</span>))}
      </div>
      <div className="grid grid-cols-2 gap-4 pt-3 border-t border-gray-100/50">
        <div><p className="text-[9px] text-gray-400 font-bold uppercase mb-1">预算范围</p><p className="text-xs font-mono font-black text-gray-900">${profile.budget.min}-${profile.budget.max}</p></div>
        <div><p className="text-[9px] text-gray-400 font-bold uppercase mb-1">核心偏好</p><p className="text-[10px] font-bold text-blue-600 truncate bg-blue-50/50 px-1 py-0.5 rounded">{profile.preferences.join(" / ")}</p></div>
      </div>
    </div>
  </DashboardCard>
);

const WeightPanel = ({ weights, isExpanded, onToggle }) => (
  <DashboardCard title="权重模型" icon={BarChart3} isExpanded={isExpanded} onToggle={onToggle}>
    <div className="space-y-3 pt-2">
      {Object.entries(weights).map(([key, val]) => (
        <div key={key} className="space-y-1">
          <div className="flex justify-between items-center text-[9px] font-bold">
            <span className="text-gray-500 uppercase tracking-tighter">{key}</span>
            <span className="font-mono text-gray-800">{(val * 100).toFixed(0)}%</span>
          </div>
          <div className="h-1.5 w-full bg-gray-100 rounded-full overflow-hidden">
            <div className="h-full bg-blue-600 transition-all duration-700" style={{ width: `${val * 100}%` }} />
          </div>
        </div>
      ))}
    </div>
  </DashboardCard>
);

const AreaMetricsCards = ({ areas, isExpanded, onToggle }) => (
  <DashboardCard title="区域指标对比" icon={Activity} isExpanded={isExpanded} onToggle={onToggle}>
    <div className="space-y-3 pt-2">
      {areas.map(area => (
        <div key={area.area_id} className="p-3 bg-white/50 rounded-xl border border-gray-100/80 shadow-sm hover:border-blue-200 transition-colors">
          <div className="flex justify-between items-center mb-2 pb-2 border-b border-gray-100">
            <span className="text-xs font-black text-gray-800">{area.name}</span>
            <div className="flex items-center gap-1 bg-green-50 px-2 py-0.5 rounded-md text-green-700 border border-green-100/50">
               <DollarSign size={10} /><span className="text-[11px] font-mono font-bold">${area.median_rent}</span>
            </div>
          </div>
          <div className="grid grid-cols-2 gap-x-4 gap-y-2">
            {Object.entries(area.metrics).map(([m, val]) => (
              <div key={m} className="flex justify-between items-center bg-gray-50/50 px-2 py-1 rounded">
                <span className="text-[9px] text-gray-500 capitalize">{m.replace('_', ' ')}</span>
                <span className={`text-[10px] font-mono font-bold ${val > 80 ? 'text-blue-600' : 'text-gray-700'}`}>{val}</span>
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  </DashboardCard>
);

const WeatherCard = ({ weather, isExpanded, onToggle }) => (
  <DashboardCard title="环境与天气实况" icon={CloudSun} variant="dark" isExpanded={isExpanded} onToggle={onToggle}>
    <div className="space-y-4 pt-2">
      <div className="flex justify-between items-end">
        <div>
          <p className="text-3xl font-black text-white tracking-tighter">{weather.temp}°<span className="text-xl text-white/50">{weather.unit}</span></p>
          <p className="text-[10px] text-white/60 font-medium mt-1">{weather.condition}</p>
        </div>
        <div className="text-right bg-white/5 px-2 py-1 rounded-lg">
           <p className="text-[9px] text-yellow-400 font-bold uppercase mb-1">Air Quality</p>
           <p className="text-xs font-bold text-white">{weather.aqi}</p>
        </div>
      </div>
      <div className="pt-3 border-t border-white/10 flex justify-between items-center bg-black/20 p-2 rounded-lg">
        <span className="text-[9px] text-white/60 uppercase font-bold">当前社区活跃度</span>
        <span className="text-[10px] text-green-400 font-bold flex items-center gap-1.5">
          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse shadow-[0_0_8px_rgba(74,222,128,0.5)]" /> {weather.activity}
        </span>
      </div>
    </div>
  </DashboardCard>
);

const TransitRealtimeCard = ({ isExpanded, onToggle }) => (
  <DashboardCard title="实时通勤" icon={Train} variant="dark" isExpanded={isExpanded} onToggle={onToggle} badge="LIVE">
    <div className="space-y-3 pt-2">
      <div className="flex justify-between items-center bg-white/5 p-2 rounded-lg">
        <div className="flex items-center gap-2">
          <span className="w-6 h-6 bg-yellow-400 text-black rounded-md flex items-center justify-center font-black text-[11px] shadow-sm">N</span>
          <span className="text-[11px] font-bold text-white/90">Astoria Blvd</span>
        </div>
        <span className="text-xs font-mono text-orange-400 font-bold bg-orange-400/10 px-2 py-0.5 rounded">2 min</span>
      </div>
      <div className="flex justify-between items-center bg-white/5 p-2 rounded-lg">
        <div className="flex items-center gap-2">
          <span className="w-6 h-6 bg-purple-600 text-white rounded-md flex items-center justify-center font-black text-[11px] shadow-sm">7</span>
          <span className="text-[11px] font-bold text-white/90">Vernon Blvd</span>
        </div>
        <span className="text-xs font-mono text-orange-400 font-bold bg-orange-400/10 px-2 py-0.5 rounded">6 min</span>
      </div>
    </div>
  </DashboardCard>
);

/**
 * ==========================================
 * 4. Main Application
 * ==========================================
 */

const App = () => {
  const [messages, setMessages] = useState([
    { role: 'agent', text: '你好！我已经优化了左侧卡片的布局排版。现在它们看起来更有呼吸感，并且严格按照要求排列在屏幕左上方。' }
  ]);
  const [expandedCard, setExpandedCard] = useState('metrics');
  const [isDebugOpen, setIsDebugOpen] = useState(false);
  const [isLoading, setIsLoading] = useState(false);

  const toggleExpand = (id) => setExpandedCard(expandedCard === id ? null : id);

  const handleSend = (val) => {
    if (!val.trim()) return;
    setMessages(prev => [...prev, { role: 'user', text: val }]);
    setIsLoading(true);
    setTimeout(() => {
      setIsLoading(false);
      setMessages(prev => [...prev, { role: 'agent', text: `针对你的反馈“${val}”，我已更新了底层的分析图层和环境实况数据。` }]);
    }, 800);
  };

  return (
    <div className="flex h-screen w-screen overflow-hidden bg-gray-50 font-sans text-gray-900 select-none">
      
      {/* 1. Map Area */}
      <MapLibrePanel>
        
        {/* Logo */}
        <div className="absolute top-6 left-8 z-30 flex items-center gap-3 bg-black/90 backdrop-blur-md text-white px-5 py-2.5 rounded-2xl shadow-xl pointer-events-auto border border-white/10">
          <Navigation size={18} fill="currentColor" className="text-yellow-400" />
          <h1 className="font-black text-sm tracking-tight italic">CITYMATE DASHBOARD</h1>
        </div>

        {/* 2. 左侧动态数据卡片组 (左上角垂直堆叠) */}
        <div className="absolute top-24 left-8 bottom-20 z-30 pointer-events-none overflow-y-auto w-[350px] hide-scrollbar">
          <div className="flex flex-col gap-3 pb-8 pt-2 items-start">
             <ProfileStatePanel profile={MOCK_PROFILE} isExpanded={expandedCard === 'profile'} onToggle={() => toggleExpand('profile')} />
             <WeightPanel weights={MOCK_PROFILE.weights} isExpanded={expandedCard === 'weights'} onToggle={() => toggleExpand('weights')} />
             <AreaMetricsCards areas={MOCK_AREA_METRICS} isExpanded={expandedCard === 'metrics'} onToggle={() => toggleExpand('metrics')} />
             <WeatherCard weather={MOCK_WEATHER} isExpanded={expandedCard === 'weather'} onToggle={() => toggleExpand('weather')} />
             <TransitRealtimeCard isExpanded={expandedCard === 'transit'} onToggle={() => toggleExpand('transit')} />
          </div>
        </div>

        {/* 9. DebugTracePanel */}
        <div 
          className={`absolute bottom-0 left-0 transition-all duration-300 z-50 ${isDebugOpen ? 'w-full h-48' : 'w-24 h-8'}`}
          onMouseDown={e => e.stopPropagation()}
          onWheel={e => e.stopPropagation()}
        >
          <button 
            onClick={() => setIsDebugOpen(!isDebugOpen)}
            className="w-full h-8 bg-neutral-900 text-white/40 px-4 flex items-center justify-between text-[10px] font-mono hover:text-white pointer-events-auto transition-colors"
          >
            DEBUG_TRACE {isDebugOpen ? '[-]' : '[+]'}
          </button>
          {isDebugOpen && (
            <div className="h-40 bg-neutral-950/95 backdrop-blur-md p-4 overflow-y-auto font-mono text-[10px] text-gray-500 space-y-1.5 border-t border-white/5 pointer-events-auto">
              <div className="text-blue-500 flex items-center gap-2"><span className="w-1.5 h-1.5 bg-blue-500 rounded-full"></span>[MAP] init: Safe resource loader executed.</div>
              <div className="text-yellow-500 flex items-center gap-2"><span className="w-1.5 h-1.5 bg-yellow-500 rounded-full"></span>[MCP] map_service: Positron Base Map active.</div>
              <div className="text-purple-400 flex items-center gap-2"><span className="w-1.5 h-1.5 bg-purple-400 rounded-full"></span>[WEATHER] fetch_current_conditions: OK</div>
              <div className="text-green-500 flex items-center gap-2"><span className="w-1.5 h-1.5 bg-green-500 rounded-full shadow-[0_0_5px_currentColor]"></span>[Agent] render: viewport synced with real GIS state.</div>
            </div>
          )}
        </div>
      </MapLibrePanel>

      {/* 4. ChatPanel */}
      <div className="w-[420px] h-full bg-white flex flex-col shadow-[-20px_0_50px_rgba(0,0,0,0.06)] z-40 shrink-0 relative">
        <div className="p-6 border-b border-gray-100 flex items-center gap-3 bg-white/80 backdrop-blur-md z-10">
          <div className="bg-blue-50 text-blue-600 p-2 rounded-xl">
             <MessageSquare size={18} />
          </div>
          <div>
            <h2 className="text-sm font-black text-gray-900 uppercase tracking-widest">决策咨询</h2>
            <p className="text-[10px] text-gray-400 font-medium">Session Active</p>
          </div>
        </div>

        <div className="flex-1 overflow-y-auto p-6 space-y-6 relative">
          {messages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
              <div className={`max-w-[85%] rounded-2xl px-5 py-3.5 text-sm leading-relaxed shadow-sm ${
                msg.role === 'user' 
                  ? 'bg-black text-white rounded-br-sm' 
                  : 'bg-gray-50 text-gray-800 rounded-bl-sm border border-gray-100'
              }`}>
                {msg.text}
              </div>
            </div>
          ))}
          {isLoading && (
            <div className="flex gap-1.5 justify-start">
              <div className="bg-gray-50 border border-gray-100 rounded-2xl px-5 py-4 flex gap-1.5 shadow-sm rounded-bl-sm">
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.2s]" />
                <span className="w-1.5 h-1.5 bg-gray-400 rounded-full animate-bounce [animation-delay:0.4s]" />
              </div>
            </div>
          )}
        </div>

        <div className="p-6 border-t border-gray-100 bg-white">
          <form 
            className="relative" 
            onSubmit={(e) => {
              e.preventDefault();
              const input = e.target.elements.chatInput;
              handleSend(input.value);
              input.value = '';
            }}
          >
            <input 
              name="chatInput"
              type="text"
              className="w-full pl-5 pr-14 py-4 bg-gray-50 border border-gray-200 rounded-xl text-sm focus:outline-none focus:ring-2 focus:ring-black/10 focus:border-black transition-all placeholder:text-gray-400"
              placeholder="询问区域详情或通勤..."
            />
            <button type="submit" className="absolute right-2 top-2 bottom-2 w-12 bg-black text-white rounded-lg flex items-center justify-center hover:bg-gray-800 transition-colors shadow-md active:scale-95">
              <ChevronRight size={20} />
            </button>
          </form>
        </div>
      </div>

      <style dangerouslySetInnerHTML={{__html: `
        /* 隐藏滚动条，保持布局纯净感 */
        .hide-scrollbar {
          -ms-overflow-style: none;
          scrollbar-width: none;
        }
        .hide-scrollbar::-webkit-scrollbar {
          display: none;
        }
      `}} />
    </div>
  );
};

export default App;