const OUTPUT_SIZE_SOURCE_URL = new URL('./output_sizes.json', import.meta.url);
const OUTPUT_SIZE_FALLBACK = {
  groups: [
    { label: '方图', sizes: [
      { value: '256x256', label: '256x256' },
      { value: '512x512', label: '512x512' },
      { value: '1024x1024', label: '1024x1024' },
      { value: '2048x2048', label: '2048x2048' },
      { value: '4096x4096', label: '4096x4096' },
    ]},
    { label: '横屏', sizes: [
      { value: '1024x576', label: '1024x576' },
      { value: '2048x1152', label: '2048x1152' },
      { value: '2560x1440', label: '2560x1440' },
      { value: '2048x1360', label: '2048x1360' },
      { value: '2048x1536', label: '2048x1536' },
    ]},
    { label: '竖屏', sizes: [
      { value: '576x1024', label: '576x1024' },
      { value: '768x1024', label: '768x1024' },
      { value: '1152x2048', label: '1152x2048' },
      { value: '1440x2560', label: '1440x2560' },
      { value: '1360x2048', label: '1360x2048' },
      { value: '1536x2048', label: '1536x2048' },
    ]},
  ],
};

let outputSizeData = OUTPUT_SIZE_FALLBACK;

const escapeHtml = value => String(value || '')
  .replace(/&/g, '&amp;')
  .replace(/</g, '&lt;')
  .replace(/>/g, '&gt;')
  .replace(/"/g, '&quot;');

export const normalizeOutputSize = value => {
  const raw = String(value || '').trim();
  if (!raw) return '';
  const compact = raw.replace(/\s+/g, '').replace(/[\u00d7\u8133]/g, 'x');
  const upper = compact.toUpperCase();
  if (upper === '1K') return '1024x1024';
  if (upper === '2K') return '2048x2048';
  if (upper === '4K') return '4096x4096';
  return compact.toLowerCase();
};

export const is16AlignedSize = value => {
  const match = /^(\d+)x(\d+)$/.exec(String(value || '').trim());
  if (!match) return false;
  return parseInt(match[1], 10) % 16 === 0 && parseInt(match[2], 10) % 16 === 0;
};

export const loadOutputSizeData = async () => {
  try {
    const resp = await fetch(OUTPUT_SIZE_SOURCE_URL, { cache: 'no-store' });
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    if (!data || !Array.isArray(data.groups)) throw new Error('invalid output size data');
    outputSizeData = data;
  } catch (e) {
    console.warn('[Settings] using fallback output sizes', e);
    outputSizeData = OUTPUT_SIZE_FALLBACK;
  }
};

const allOutputSizeEntries = () => {
  const groups = Array.isArray(outputSizeData.groups) ? outputSizeData.groups : [];
  return groups.flatMap(group => Array.isArray(group.sizes) ? group.sizes : []);
};

const allOutputSizeValues = () => allOutputSizeEntries()
  .map(item => normalizeOutputSize(item.value))
  .filter(value => value && is16AlignedSize(value));

export const sizeOptionsHtml = (value = '', { includeDefault = false, esc = escapeHtml } = {}) => {
  const selected = normalizeOutputSize(value);
  const groups = Array.isArray(outputSizeData.groups) ? outputSizeData.groups : [];
  const normalizeItem = item => {
    const itemValue = normalizeOutputSize(item?.value);
    return itemValue && is16AlignedSize(itemValue)
      ? { value: itemValue, label: String(item?.label || itemValue) }
      : null;
  };
  const groupHtml = groups.map(group => {
    const items = Array.isArray(group.sizes) ? group.sizes.map(normalizeItem).filter(Boolean) : [];
    if (!items.length) return '';
    return `<optgroup label="${esc(String(group.label || ''))}">${items.map(item => `<option value="${esc(item.value)}" ${item.value===selected?'selected':''}>${esc(item.label)}</option>`).join('')}</optgroup>`;
  }).join('');
  const known = new Set(allOutputSizeValues());
  const defaultOption = includeDefault ? `<option value="" ${selected===''?'selected':''}>服务商默认</option>` : '';
  const extraOption = selected && !known.has(selected) && is16AlignedSize(selected)
    ? `<option value="${esc(selected)}" selected>${esc(selected)}</option>`
    : '';
  return defaultOption + groupHtml + extraOption;
};
