import { useEffect, useRef, useState } from 'react';
import maplibregl, { type Map as MapLibreMap } from 'maplibre-gl';
import 'maplibre-gl/dist/maplibre-gl.css';
import { AlertCircle, Map as MapIcon, Navigation } from 'lucide-react';
import { MAPTILER_API_KEY } from '../api/client';
import type { AreaOption } from '../types/area';
import type { MapLayer } from '../types/map';

type Props = {
  areas: AreaOption[];
  layers: MapLayer[];
  activeAreaId: string | null;
};

const fallbackStyle = 'https://demotiles.maplibre.org/style.json';
const mapTilerStyle = MAPTILER_API_KEY
  ? `https://api.maptiler.com/maps/streets-v2/style.json?key=${MAPTILER_API_KEY}`
  : fallbackStyle;

function addBusinessLayer(map: MapLibreMap, layer: MapLayer) {
  const sourceId = `source-${layer.layer_id}`;
  const layerId = `layer-${layer.layer_id}`;

  if (map.getLayer(layerId)) map.removeLayer(layerId);
  if (map.getSource(sourceId)) map.removeSource(sourceId);

  map.addSource(sourceId, {
    type: 'geojson',
    data: layer.geojson as never
  });

  if (layer.layer_type === 'choropleth') {
    map.addLayer({
      id: layerId,
      type: 'fill',
      source: sourceId,
      paint: {
        'fill-color': '#ef4444',
        'fill-opacity': 0.28,
        'fill-outline-color': '#991b1b'
      }
    });
    return;
  }

  map.addLayer({
    id: layerId,
    type: 'circle',
    source: sourceId,
    paint: {
      'circle-radius': ['interpolate', ['linear'], ['zoom'], 10, 5, 14, 12],
      'circle-color': layer.metric_name === 'entertainment' ? '#2563eb' : '#10b981',
      'circle-stroke-color': '#ffffff',
      'circle-stroke-width': 2,
      'circle-opacity': 0.86
    }
  });
}

export function MapPanel({ areas, layers, activeAreaId }: Props) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapLibreMap | null>(null);
  const [status, setStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [error, setError] = useState<string>('');

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const activeArea = areas.find((area) => area.area_id === activeAreaId) ?? areas[0];

    try {
      const map = new maplibregl.Map({
        container: containerRef.current,
        style: mapTilerStyle,
        center: [activeArea?.longitude ?? -73.93, activeArea?.latitude ?? 40.755],
        zoom: 12.3,
        attributionControl: { compact: true },
        dragPan: true,
        scrollZoom: true,
        doubleClickZoom: true
      });
      mapRef.current = map;

      map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right');

      map.on('load', () => {
        setStatus('ready');
      });

      map.on('error', (event) => {
        console.warn('MapLibre non-fatal error', event);
      });

      map.on('click', (event) => {
        const businessLayerIds = (map.getStyle().layers ?? [])
          .map((layer) => layer.id)
          .filter((id) => id.startsWith('layer-map_'));
        if (!businessLayerIds.length) return;
        const features = map.queryRenderedFeatures(event.point, { layers: businessLayerIds });
        const feature = features[0];
        if (!feature) return;

        const title = String(feature.properties?.name ?? feature.properties?.area_name ?? 'Map feature');
        const detail = Object.entries(feature.properties ?? {})
          .slice(0, 4)
          .map(([key, value]) => `<div><b>${key}</b>: ${String(value)}</div>`)
          .join('');

        new maplibregl.Popup({ closeButton: true, closeOnClick: true })
          .setLngLat(event.lngLat)
          .setHTML(`<strong>${title}</strong>${detail}`)
          .addTo(map);
      });
    } catch (err) {
      setStatus('error');
      setError(err instanceof Error ? err.message : 'Map initialization failed');
    }

    return () => {
      mapRef.current?.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || status !== 'ready') return;
    layers.forEach((layer) => addBusinessLayer(map, layer));
  }, [layers, status]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || status !== 'ready') return;
    const activeArea = areas.find((area) => area.area_id === activeAreaId);
    if (!activeArea?.latitude || !activeArea.longitude) return;

    map.flyTo({
      center: [activeArea.longitude, activeArea.latitude],
      zoom: 12.8,
      speed: 0.8,
      essential: true
    });
  }, [activeAreaId, areas, status]);

  return (
    <section className="map-panel">
      <div ref={containerRef} className={`map-panel__canvas ${status === 'ready' ? 'map-panel__canvas--ready' : ''}`} />

      {status === 'loading' ? (
        <div className="map-panel__state">
          <MapIcon size={42} />
          <span>Initializing MapLibre map...</span>
        </div>
      ) : null}

      {status === 'error' ? (
        <div className="map-panel__state map-panel__state--error">
          <AlertCircle size={42} />
          <span>{error}</span>
        </div>
      ) : null}

      {!MAPTILER_API_KEY ? (
        <div className="map-panel__fallback-note">
          <AlertCircle size={14} /> 使用 MapLibre demo tiles；填写 VITE_MAPTILER_API_KEY 后切换 MapTiler。
        </div>
      ) : null}

      <div className="map-panel__brand">
        <Navigation size={18} />
        <strong>CITYMATE</strong>
        <span>MapLibre + MapTiler</span>
      </div>
    </section>
  );
}
