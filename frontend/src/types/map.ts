import type { DataQuality } from './api';

export type GeoJsonFeatureCollection = {
  type: 'FeatureCollection';
  features: Array<{
    type: 'Feature';
    geometry: {
      type: string;
      coordinates: unknown;
    };
    properties: Record<string, unknown>;
  }>;
};

export type MapLayerType = 'choropleth' | 'heatmap' | 'marker' | 'cluster' | 'route';

export type MapLayer = {
  layer_id: string;
  layer_type: MapLayerType;
  metric_name: string;
  geojson: GeoJsonFeatureCollection;
  style_hint: Record<string, unknown>;
  data_quality: DataQuality;
  updated_at: string;
  expires_at: string | null;
};

export type MapLayersResponse = {
  area_id: string;
  layers: MapLayer[];
};
