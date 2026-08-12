import { getChartColors } from '../../theme/chartTokens';
import { MODEL_NAME_LABELS } from '../../shared/constants';

export const MODEL_ORDER = Object.keys(MODEL_NAME_LABELS);

export function modelOrderIndex(modelName: string): number {
  const index = MODEL_ORDER.indexOf(modelName);
  return index === -1 ? MODEL_ORDER.length : index;
}

function parseHexColor(color: string): [number, number, number] | null {
  const normalized = color.trim().replace(/^#/, '');
  const expanded = normalized.length === 3
    ? normalized.split('').map((character) => character.repeat(2)).join('')
    : normalized;
  if (!/^[0-9a-f]{6}$/i.test(expanded)) return null;
  return [
    Number.parseInt(expanded.slice(0, 2), 16),
    Number.parseInt(expanded.slice(2, 4), 16),
    Number.parseInt(expanded.slice(4, 6), 16),
  ];
}

function rgbHue([red, green, blue]: [number, number, number]): number {
  const [r, g, b] = [red, green, blue].map((value) => value / 255);
  const maximum = Math.max(r, g, b);
  const minimum = Math.min(r, g, b);
  const delta = maximum - minimum;
  if (delta === 0) return 0;
  if (maximum === r) return 60 * (((g - b) / delta) % 6);
  if (maximum === g) return 60 * ((b - r) / delta + 2);
  return 60 * ((r - g) / delta + 4);
}

function hslToHex(hue: number, saturation: number, lightness: number): string {
  const s = saturation / 100;
  const l = lightness / 100;
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const section = ((hue % 360) + 360) % 360 / 60;
  const x = chroma * (1 - Math.abs((section % 2) - 1));
  const rgb = section < 1 ? [chroma, x, 0]
    : section < 2 ? [x, chroma, 0]
      : section < 3 ? [0, chroma, x]
        : section < 4 ? [0, x, chroma]
          : section < 5 ? [x, 0, chroma]
            : [chroma, 0, x];
  const offset = l - chroma / 2;
  return `#${rgb.map((value) => Math.round((value + offset) * 255).toString(16).padStart(2, '0')).join('')}`;
}

function stableHash(value: string): number {
  let hash = 0;
  for (const character of value) hash = Math.imul(hash, 31) + character.charCodeAt(0) | 0;
  return Math.abs(hash);
}

export function getModelLineVisual(modelName: string): { color: string } {
  const colors = getChartColors();
  const primaryRgb = parseHexColor(colors.primary) ?? [255, 42, 61];
  const textRgb = parseHexColor(colors.text) ?? [245, 245, 247];
  const knownIndex = modelOrderIndex(modelName);
  const colorIndex = knownIndex < MODEL_ORDER.length ? knownIndex : stableHash(modelName);
  const baseHue = rgbHue(primaryRgb);
  const hue = baseHue + colorIndex * 137.508;
  const saturation = 66 + colorIndex % 3 * 6;
  const textBrightness = textRgb[0] * 0.299 + textRgb[1] * 0.587 + textRgb[2] * 0.114;
  const lightnessBase = textBrightness < 128 ? 43 : 58;
  const lightness = lightnessBase + Math.floor(colorIndex / 3) % 3 * 5;

  return { color: hslToHex(hue, saturation, lightness) };
}
