import { useEffect, useMemo, useState } from 'react';
import { createSession } from '../api/sessions';
import { sendChat } from '../api/chat';
import { getAreaMetrics, getMapLayers } from '../api/areas';
import { getAreaWeather } from '../api/weather';
import { getRealtimeTransit } from '../api/transit';
import { DEBUG_MODE } from '../api/client';
import { AreaMetricsCards } from '../components/AreaMetricsCards';
import { ChatPanel } from '../components/ChatPanel';
import { DebugTracePanel } from '../components/DebugTracePanel';
import { MapPanel } from '../components/MapPanel';
import { ProfileStatePanel } from '../components/ProfileStatePanel';
import { TransitRealtimeCard } from '../components/TransitRealtimeCard';
import { WeatherCard } from '../components/WeatherCard';
import { WeightPanel } from '../components/WeightPanel';
import type { AreaMetricsResponse } from '../types/area';
import type { ChatMessage, TraceSummaryItem } from '../types/chat';
import type { MapLayer } from '../types/map';
import type { ProfileSnapshot } from '../types/profile';
import type { TransitRealtimeResponse } from '../types/transit';
import type { WeatherResponse } from '../types/weather';
import type { AreaOption } from '../types/area';
import type { DisplayRefs } from '../types/api';

const firstAssistantMessage: ChatMessage = {
  id: 'msg_initial_assistant',
  role: 'assistant',
  message_type: 'answer',
  content: '你好，我是 NYC 生活与租房决策助手。你可以告诉我你关心的区域，我会帮你查安全、租金、娱乐设施、天气或实时通勤。',
  created_at: new Date().toISOString(),
  cards: [],
  sources: []
};

const areaOptions: AreaOption[] = [
  { area_id: 'QN0101', area_name: 'Astoria', borough: 'Queens', latitude: 40.7644, longitude: -73.9235, median_rent: 3200 },
  { area_id: 'QN0102', area_name: 'Long Island City', borough: 'Queens', latitude: 40.7447, longitude: -73.9485, median_rent: 3600 },
  { area_id: 'BK0102', area_name: 'Williamsburg', borough: 'Brooklyn', latitude: 40.7081, longitude: -73.9571, median_rent: 3550 },
  { area_id: 'BK0101', area_name: 'Greenpoint', borough: 'Brooklyn', latitude: 40.7306, longitude: -73.9543, median_rent: 3400 }
];

export function Dashboard() {
  const [sessionId, setSessionId] = useState<string>('');
  const [profile, setProfile] = useState<ProfileSnapshot | null>(null);
  const [areaMetrics, setAreaMetrics] = useState<AreaMetricsResponse | null>(null);
  const [weather, setWeather] = useState<WeatherResponse | null>(null);
  const [transit, setTransit] = useState<TransitRealtimeResponse | null>(null);
  const [mapLayers, setMapLayers] = useState<MapLayer[]>([]);
  const [mapPoints, setMapPoints] = useState<NonNullable<DisplayRefs['map_points']>>([]);
  const [messages, setMessages] = useState<ChatMessage[]>([firstAssistantMessage]);
  const [trace, setTrace] = useState<TraceSummaryItem[]>([]);
  const [expandedCard, setExpandedCard] = useState<string>('metrics');
  const [isDebugOpen, setIsDebugOpen] = useState(DEBUG_MODE);
  const [isLoading, setIsLoading] = useState(false);

  const activeAreaId = profile?.target_area?.area_id ?? null;

  const areas = useMemo(() => areaOptions, []);
  const effectiveMapPoints = useMemo(() => {
    const points = [...mapPoints];
    const hasTargetPoint = points.some((point) => point.kind === 'target_area');
    const metricsMatchActiveArea = Boolean(
      activeAreaId &&
      areaMetrics?.area?.area_id &&
      areaMetrics.area.area_id === activeAreaId
    );
    if (
      !hasTargetPoint &&
      metricsMatchActiveArea &&
      areaMetrics?.area?.latitude != null &&
      areaMetrics?.area?.longitude != null
    ) {
      points.unshift({
        id: `target-area-${areaMetrics.area.area_id}`,
        kind: 'target_area',
        label: areaMetrics.area.area_name,
        latitude: Number(areaMetrics.area.latitude),
        longitude: Number(areaMetrics.area.longitude)
      });
    }
    return points;
  }, [mapPoints, areaMetrics, activeAreaId]);

  const activeAreaCenter = useMemo(() => {
    if (!activeAreaId) return null;
    if (areaMetrics?.area?.area_id === activeAreaId && areaMetrics.area.latitude != null && areaMetrics.area.longitude != null) {
      return {
        latitude: Number(areaMetrics.area.latitude),
        longitude: Number(areaMetrics.area.longitude)
      };
    }
    return null;
  }, [activeAreaId, areaMetrics]);

  useEffect(() => {
    let cancelled = false;
    createSession()
      .then((response) => {
        if (cancelled || !response.data) return;
        setSessionId(response.data.session_id);
        setProfile(response.data.profile_snapshot);
      })
      .catch((error) => {
        console.error('Failed to create session', error);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!sessionId || !activeAreaId) return;
    let cancelled = false;

    Promise.all([
      getAreaMetrics(activeAreaId, sessionId),
      getAreaWeather(activeAreaId, sessionId),
      getRealtimeTransit({ session_id: sessionId, origin: profile?.target_area?.area_name ?? 'Astoria', destination: profile?.target_destination ?? 'NYU', mode: 'subway' })
    ])
      .then(([metricsResponse, weatherResponse, transitResponse]) => {
        if (cancelled) return;
        setAreaMetrics(metricsResponse.data);
        setWeather(weatherResponse.data);
        setTransit(transitResponse.data);
      })
      .catch((error) => {
        console.error('Failed to load dashboard data', error);
      });

    return () => {
      cancelled = true;
    };
  }, [activeAreaId, profile?.target_area?.area_name, profile?.target_destination, sessionId]);

  const toggleCard = (id: string) => {
    setExpandedCard((current) => (current === id ? '' : id));
  };

  const handleSend = async (message: string) => {
    if (!sessionId) return;

    const userMessage: ChatMessage = {
      id: `msg_user_${Date.now()}`,
      role: 'user',
      message_type: 'answer',
      content: message,
      created_at: new Date().toISOString(),
      cards: [],
      sources: []
    };

    setMessages((current) => [...current, userMessage]);
    setIsLoading(true);

    try {
      const response = await sendChat({
        session_id: sessionId,
        message,
        debug: DEBUG_MODE,
        client_context: {
          active_area_id: activeAreaId,
          active_view: 'dashboard'
        }
      });

      if (!response.data) return;

      const assistantMessage: ChatMessage = {
        id: `msg_assistant_${Date.now()}`,
        role: 'assistant',
        message_type: response.data.message_type,
        content: response.data.answer,
        created_at: new Date().toISOString(),
        cards: response.data.cards,
        sources: response.data.sources
      };

      setMessages((current) => [...current, assistantMessage]);
      setProfile(response.data.profile_snapshot);
      setMapPoints(response.data.display_refs.map_points ?? []);
      const mapLayerIds = response.data.display_refs.map_layer_ids ?? [];
      const nextAreaId = response.data.profile_snapshot?.target_area?.area_id ?? activeAreaId;
      if (nextAreaId && mapLayerIds.length > 0) {
        const mapResponse = await getMapLayers(nextAreaId, sessionId);
        const layers = (mapResponse.data?.layers ?? []).filter((layer) => mapLayerIds.includes(layer.layer_id));
        setMapLayers(layers);
      } else {
        setMapLayers([]);
      }
      setTrace(response.data.debug?.trace_summary ?? []);
    } catch (error) {
      setMessages((current) => [
        ...current,
        {
          id: `msg_error_${Date.now()}`,
          role: 'assistant',
          message_type: 'error',
          content: error instanceof Error ? error.message : '请求失败，请稍后重试。',
          created_at: new Date().toISOString(),
          cards: [],
          sources: []
        }
      ]);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <main className="dashboard-shell">
      <MapPanel
        areas={areas}
        layers={mapLayers}
        activeAreaId={activeAreaId}
        activeAreaCenter={activeAreaCenter}
        points={effectiveMapPoints}
      />

      <div className="floating-brand">
        <span className="brand-mark">NYC</span>
        <div>
          <strong>CityMate Dashboard</strong>
          <small>A2A + MCP decision workspace</small>
        </div>
      </div>

      <div className="card-rail">
        <ProfileStatePanel profile={profile} isExpanded={expandedCard === 'profile'} onToggle={toggleCard} />
        <WeightPanel weights={profile?.weights ?? null} isExpanded={expandedCard === 'weights'} onToggle={toggleCard} />
        <AreaMetricsCards metrics={areaMetrics} isExpanded={expandedCard === 'metrics'} onToggle={toggleCard} />
        <WeatherCard weather={weather} isExpanded={expandedCard === 'weather'} onToggle={toggleCard} />
        <TransitRealtimeCard transit={transit} isExpanded={expandedCard === 'transit'} onToggle={toggleCard} />
      </div>

      <DebugTracePanel trace={trace} isOpen={isDebugOpen} onToggle={() => setIsDebugOpen((value) => !value)} />
      <ChatPanel messages={messages} isLoading={isLoading} onSend={handleSend} />
    </main>
  );
}
