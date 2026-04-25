import type { ApiEnvelope } from '../types/api';
import type { AreaMetricsResponse, AreaOption } from '../types/area';
import type { ChatResponseData } from '../types/chat';
import type { MapLayersResponse } from '../types/map';
import type { ProfileSnapshot, SessionCreateResponse } from '../types/profile';
import type { TransitRealtimeResponse } from '../types/transit';
import type { WeatherResponse } from '../types/weather';

const now = '2026-04-25T12:50:00-04:00';
const expires = '2026-04-25T13:20:00-04:00';

export const mockAreaOptions: AreaOption[] = [
  {
    area_id: 'QN0101',
    area_name: 'Astoria',
    borough: 'Queens',
    latitude: 40.7686,
    longitude: -73.9196,
    median_rent: 2850
  },
  {
    area_id: 'QN0102',
    area_name: 'Long Island City',
    borough: 'Queens',
    latitude: 40.7447,
    longitude: -73.9485,
    median_rent: 3600
  }
];

export const mockProfile: ProfileSnapshot = {
  session_id: 'sess_demo_001',
  target_area: {
    area_id: 'QN0101',
    area_name: 'Astoria',
    borough: 'Queens'
  },
  target_area_id: 'QN0101',
  budget: { min: 2500, max: 3800, currency: 'USD' },
  target_destination: 'NYU',
  max_commute_minutes: 40,
  preferences: ['安静', '少换乘'],
  weights: {
    safety: 0.35,
    commute: 0.25,
    rent: 0.2,
    convenience: 0.1,
    entertainment: 0.1
  },
  missing_required_fields: [],
  conversation_summary: '用户正在比较 Astoria 和 Long Island City，安全和通勤是主要考虑因素。',
  updated_at: now
};

export const mockAreaMetrics: AreaMetricsResponse = {
  area: {
    area_id: 'QN0101',
    area_name: 'Astoria',
    borough: 'Queens',
    latitude: 40.7686,
    longitude: -73.9196
  },
  metrics: {
    crime_count_30d: 42,
    crime_index_100: 63.5,
    entertainment_poi_count: 86,
    convenience_facility_count: 54,
    transit_station_count: 7,
    complaint_noise_30d: 19,
    rent_index_value: 2850
  },
  metric_cards: [
    {
      card_type: 'metric',
      title: '安全',
      subtitle: '近 30 天公开犯罪记录',
      score_label: '中等',
      metrics: [{ label: '犯罪记录数', value: 42, unit: '起' }],
      data_quality: 'reference',
      source: [{ name: 'NYPD Complaint Data', type: 'nyc_open_data', updated_at: now }]
    },
    {
      card_type: 'metric',
      title: '租金',
      subtitle: '区域租金参考',
      score_label: '$2,850 median',
      metrics: [{ label: '参考租金', value: 2850, unit: 'USD/月' }],
      data_quality: 'reference',
      source: [{ name: 'RentCast / ZORI cache', type: 'rental_data', updated_at: now }]
    },
    {
      card_type: 'metric',
      title: '通勤',
      subtitle: '站点覆盖',
      score_label: '较好',
      metrics: [{ label: '站点数', value: 7, unit: '个' }],
      data_quality: 'reference',
      source: [{ name: 'MTA GTFS static', type: 'transit_static', updated_at: now }]
    },
    {
      card_type: 'metric',
      title: '便利',
      subtitle: '生活设施',
      score_label: '54',
      metrics: [{ label: '便利设施', value: 54, unit: '个' }],
      data_quality: 'reference',
      source: [{ name: 'NYC Facilities / OSM', type: 'poi_data', updated_at: now }]
    },
    {
      card_type: 'metric',
      title: '娱乐',
      subtitle: '酒吧/餐厅/影院等',
      score_label: '86',
      metrics: [{ label: '娱乐 POI', value: 86, unit: '个' }],
      data_quality: 'reference',
      source: [{ name: 'OpenStreetMap Overpass', type: 'poi_data', updated_at: now }]
    }
  ],
  source_snapshot: {},
  updated_at: now
};

export const mockWeather: WeatherResponse = {
  area: mockAreaMetrics.area,
  weather: {
    mode: 'hourly_summary',
    target_time: null,
    periods: [
      {
        start_time: '2026-04-25T13:00:00-04:00',
        end_time: '2026-04-25T14:00:00-04:00',
        temperature: 62,
        temperature_unit: 'F',
        precipitation_probability: 20,
        wind_speed: '8 mph',
        wind_direction: 'NW',
        short_forecast: 'Mostly Sunny',
        detailed_forecast: 'Mostly sunny, with a high near 64.',
        is_daytime: true
      },
      {
        start_time: '2026-04-25T14:00:00-04:00',
        end_time: '2026-04-25T15:00:00-04:00',
        temperature: 64,
        temperature_unit: 'F',
        precipitation_probability: 15,
        wind_speed: '7 mph',
        wind_direction: 'NW',
        short_forecast: 'Sunny',
        detailed_forecast: 'Sunny conditions continue.',
        is_daytime: true
      }
    ]
  },
  data_quality: 'cached',
  source: [{ name: 'National Weather Service API', type: 'weather_api', url: 'https://api.weather.gov', updated_at: now }],
  updated_at: now,
  expires_at: expires
};

export const mockMapLayers: MapLayersResponse = {
  area_id: 'QN0101',
  layers: [
    {
      layer_id: 'map_astoria_safety',
      layer_type: 'choropleth',
      metric_name: 'crime_index',
      geojson: {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            geometry: {
              type: 'Polygon',
              coordinates: [[
                [-73.936, 40.755],
                [-73.895, 40.755],
                [-73.895, 40.785],
                [-73.936, 40.785],
                [-73.936, 40.755]
              ]]
            },
            properties: { area_id: 'QN0101', area_name: 'Astoria', crime_index_100: 63.5 }
          }
        ]
      },
      style_hint: { color_scale: 'red', value_field: 'crime_index_100' },
      data_quality: 'cached',
      updated_at: now,
      expires_at: null
    },
    {
      layer_id: 'map_astoria_poi',
      layer_type: 'marker',
      metric_name: 'entertainment',
      geojson: {
        type: 'FeatureCollection',
        features: [
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [-73.9196, 40.7686] },
            properties: { name: 'Astoria Entertainment Cluster', category: 'restaurant', count: 24 }
          },
          {
            type: 'Feature',
            geometry: { type: 'Point', coordinates: [-73.9235, 40.7644] },
            properties: { name: 'Convenience Cluster', category: 'supermarket', count: 8 }
          }
        ]
      },
      style_hint: { color: 'blue' },
      data_quality: 'cached',
      updated_at: now,
      expires_at: null
    }
  ]
};

export const mockTransit: TransitRealtimeResponse = {
  mode: 'subway',
  origin_stop: 'Astoria Blvd',
  destination: 'NYU',
  walking_to_stop_minutes: 7,
  waiting_minutes: 4,
  in_vehicle_minutes: 28,
  total_minutes: 39,
  recommended_leave_at: '2026-04-25T12:56:00-04:00',
  estimated_arrival_at: '2026-04-25T13:35:00-04:00',
  realtime_used: true,
  fallback_used: false,
  departures: [
    { route_id: 'N', stop_name: 'Astoria Blvd', departure_time: '2026-04-25T13:00:00-04:00', minutes_until_departure: 4, delay_seconds: 0 },
    { route_id: 'W', stop_name: 'Astoria Blvd', departure_time: '2026-04-25T13:07:00-04:00', minutes_until_departure: 11, delay_seconds: 30 }
  ],
  data_quality: 'realtime',
  source: [{ name: 'MTA GTFS Realtime', type: 'transit_realtime', updated_at: now }]
};

export function envelope<T>(data: T, sessionId = 'sess_demo_001'): ApiEnvelope<T> {
  return {
    success: true,
    trace_id: `trace_demo_${Date.now()}`,
    session_id: sessionId,
    data,
    error: null
  };
}

export function mockCreateSession(): ApiEnvelope<SessionCreateResponse> {
  return envelope({ session_id: mockProfile.session_id, profile_snapshot: mockProfile }, mockProfile.session_id);
}

export function mockChat(message: string): ApiEnvelope<ChatResponseData> {
  const lower = message.toLowerCase();
  const isWeather = lower.includes('weather') || message.includes('天气') || message.includes('下雨');
  const isMissingArea = lower.includes('where') || message.includes('附近怎么样');

  if (isMissingArea) {
    return envelope({
      message_type: 'follow_up',
      answer: '你想了解纽约哪个区域？例如 Astoria、LIC、Williamsburg。',
      next_action: 'ask_follow_up',
      profile_snapshot: { ...mockProfile, target_area: null, target_area_id: null, missing_required_fields: ['target_area'] },
      missing_slots: ['target_area'],
      cards: [],
      display_refs: { map_layer_ids: [], display_result_ids: [] },
      sources: [],
      data_quality: 'unknown',
      debug: null
    });
  }

  return envelope({
    message_type: 'answer',
    answer: isWeather
      ? 'Astoria 未来几小时以晴到多云为主，降水概率较低。天气数据来自 National Weather Service，并已使用短缓存。'
      : 'Astoria 当前适合继续作为候选区域：通勤覆盖较好，租金低于 LIC，安全指标处于中等水平。你可以继续问具体犯罪类型、娱乐设施分类或实时通勤。',
    next_action: 'respond_final',
    profile_snapshot: mockProfile,
    cards: isWeather ? [
      {
        card_type: 'weather',
        title: 'Astoria 天气',
        subtitle: '未来 6 小时',
        periods: mockWeather.weather.periods,
        data_quality: mockWeather.data_quality,
        source: mockWeather.source
      }
    ] : mockAreaMetrics.metric_cards,
    display_refs: { map_layer_ids: ['map_astoria_safety', 'map_astoria_poi'], display_result_ids: [] },
    sources: isWeather ? mockWeather.source : [{ name: 'NYPD Complaint Data', type: 'nyc_open_data', updated_at: now }],
    data_quality: isWeather ? 'cached' : 'reference',
    debug: {
      trace_summary: [
        { step: 'orchestrator.intent_detected', service: 'orchestrator-agent', status: 'success', latency_ms: 120 },
        { step: isWeather ? 'weather.current_query' : 'neighborhood.metrics_query', service: isWeather ? 'weather-agent' : 'neighborhood-agent', mcp: isWeather ? 'mcp-weather' : 'mcp-safety', status: 'success', latency_ms: 360 }
      ]
    }
  });
}
