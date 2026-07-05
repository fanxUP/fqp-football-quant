/**
 * Team logo / flag utilities.
 *
 * National teams → flag images from flagcdn.com
 * Club teams    → colored circle with initials
 */

// ── National team detection ──────────────────────────────

/** Chinese country names that appear in team_name_cn */
const CN_COUNTRIES: Record<string, string> = {
  阿尔巴尼亚: 'al',
  阿尔及利亚: 'dz',
  阿富汗: 'af',
  阿根廷: 'ar',
  阿联酋: 'ae',
  埃及: 'eg',
  埃塞俄比亚: 'et',
  爱尔兰: 'ie',
  爱沙尼亚: 'ee',
  安哥拉: 'ao',
  奥地利: 'at',
  澳大利亚: 'au',
  巴拉圭: 'py',
  巴勒斯坦: 'ps',
  巴林: 'bh',
  巴拿马: 'pa',
  巴西: 'br',
  白俄罗斯: 'by',
  保加利亚: 'bg',
  北爱尔兰: 'gb-nir',
  北马其顿: 'mk',
  比利时: 'be',
  冰岛: 'is',
  波兰: 'pl',
  波黑: 'ba',
  玻利维亚: 'bo',
  伯利兹: 'bz',
  布基纳法索: 'bf',
  赤道几内亚: 'gq',
  丹麦: 'dk',
  德国: 'de',
  东帝汶: 'tl',
  多哥: 'tg',
  俄罗斯: 'ru',
  厄瓜多尔: 'ec',
  厄立特里亚: 'er',
  法国: 'fr',
  菲律宾: 'ph',
  佛得角: 'cv',
  芬兰: 'fi',
  冈比亚: 'gm',
  刚果: 'cg',
  哥伦比亚: 'co',
  哥斯达黎加: 'cr',
  格鲁吉亚: 'ge',
  古巴: 'cu',
  圭亚那: 'gy',
  哈萨克斯坦: 'kz',
  海地: 'ht',
  韩国: 'kr',
  荷兰: 'nl',
  黑山: 'me',
  洪都拉斯: 'hn',
  几内亚: 'gn',
  加拿大: 'ca',
  加纳: 'gh',
  加蓬: 'ga',
  柬埔寨: 'kh',
  捷克: 'cz',
  津巴布韦: 'zw',
  喀麦隆: 'cm',
  卡塔尔: 'qa',
  科特迪瓦: 'ci',
  科威特: 'kw',
  克罗地亚: 'hr',
  肯尼亚: 'ke',
  库拉索: 'cw',
  拉脱维亚: 'lv',
  黎巴嫩: 'lb',
  立陶宛: 'lt',
  利比里亚: 'lr',
  利比亚: 'ly',
  列支敦士登: 'li',
  卢森堡: 'lu',
  卢旺达: 'rw',
  罗马尼亚: 'ro',
  马达加斯加: 'mg',
  马尔代夫: 'mv',
  马耳他: 'mt',
  马拉维: 'mw',
  马来西亚: 'my',
  马里: 'ml',
  北马其顿: 'mk',
  毛里求斯: 'mu',
  毛里塔尼亚: 'mr',
  美国: 'us',
  民主刚果: 'cd',
  秘鲁: 'pe',
  摩尔多瓦: 'md',
  摩洛哥: 'ma',
  摩纳哥: 'mc',
  莫桑比克: 'mz',
  墨西哥: 'mx',
  纳米比亚: 'na',
  南非: 'za',
  南苏丹: 'ss',
  尼泊尔: 'np',
  尼加拉瓜: 'ni',
  尼日尔: 'ne',
  尼日利亚: 'ng',
  挪威: 'no',
  葡萄牙: 'pt',
  日本: 'jp',
  瑞典: 'se',
  瑞士: 'ch',
  萨尔瓦多: 'sv',
  塞尔维亚: 'rs',
  塞拉利昂: 'sl',
  塞内加尔: 'sn',
  塞浦路斯: 'cy',
  沙特: 'sa',
  圣马力诺: 'sm',
  斯洛伐克: 'sk',
  斯洛文尼亚: 'si',
  斯威士兰: 'sz',
  苏格兰: 'gb-sct',
  苏丹: 'sd',
  苏里南: 'sr',
  所罗门群岛: 'sb',
  塔希提: 'pf',
  塔吉克斯坦: 'tj',
  泰国: 'th',
  坦桑尼亚: 'tz',
  特立尼达和多巴哥: 'tt',
  突尼斯: 'tn',
  土耳其: 'tr',
  土库曼斯坦: 'tm',
  瓦努阿图: 'vu',
  危地马拉: 'gt',
  委内瑞拉: 've',
  乌干达: 'ug',
  乌克兰: 'ua',
  乌拉圭: 'uy',
  乌兹别克斯坦: 'uz',
  希腊: 'gr',
  新加坡: 'sg',
  新西兰: 'nz',
  匈牙利: 'hu',
  叙利亚: 'sy',
  牙买加: 'jm',
  亚美尼亚: 'am',
  也门: 'ye',
  伊拉克: 'iq',
  伊朗: 'ir',
  以色列: 'il',
  意大利: 'it',
  印度: 'in',
  印度尼西亚: 'id',
  英格兰: 'gb-eng',
  约旦: 'jo',
  越南: 'vn',
  赞比亚: 'zm',
  智利: 'cl',
  中国: 'cn',
  中华台北: 'tw',
  中国香港: 'hk',
  中国澳门: 'mo',
  中非共和国: 'cf',
};

/** English country names from the `country` column */
const EN_COUNTRIES: Record<string, string> = {
  Algeria: 'dz',
  Argentina: 'ar',
  Australia: 'au',
  Austria: 'at',
  Belgium: 'be',
  'Bosnia and Herzegovina': 'ba',
  'Cape Verde': 'cv',
  Colombia: 'co',
  Croatia: 'hr',
  Egypt: 'eg',
  Finland: 'fi',
  Ghana: 'gh',
  Portugal: 'pt',
  Senegal: 'sn',
  Spain: 'es',
  Switzerland: 'ch',
  'United States': 'us',
};

/** Try to get a flag CDN URL for a team. Returns null for club teams. */
export function getFlagUrl(
  nameCn?: string | null,
  nameEn?: string | null,
  country?: string | null,
): string | null {
  let code: string | undefined;

  // 1. Check if `country` is an English country name
  if (country && EN_COUNTRIES[country]) {
    code = EN_COUNTRIES[country];
  }

  // 2. Check if team_name_cn is a Chinese country name
  if (!code && nameCn && CN_COUNTRIES[nameCn]) {
    code = CN_COUNTRIES[nameCn];
  }

  // 3. Try shortened version (remove 男/女 suffix for youth teams)
  if (!code && nameCn) {
    const stripped = nameCn.replace(/[男女]$/, '');
    if (stripped !== nameCn && CN_COUNTRIES[stripped]) {
      code = CN_COUNTRIES[stripped];
    }
  }

  // 4. Check if team_name_en is an English country name
  if (!code && nameEn && EN_COUNTRIES[nameEn]) {
    code = EN_COUNTRIES[nameEn];
  }

  if (!code) return null;

  // Return SVG for crisp rendering at any size
  return `https://flagcdn.com/${code}.svg`;
}

/** Returns true if this team is a national team (has a flag) */
export function isNationalTeam(
  nameCn?: string | null,
  nameEn?: string | null,
  country?: string | null,
): boolean {
  return getFlagUrl(nameCn, nameEn, country) !== null;
}

// ── Club team colors ──────────────────────────────────────

const TEAM_GRADIENTS: [string, string][] = [
  ['#E50914', '#B00810'],   // Red
  ['#3B82F6', '#1D4ED8'],   // Blue
  ['#22C55E', '#15803D'],   // Green
  ['#F59E0B', '#D97706'],   // Amber
  ['#8B5CF6', '#6D28D9'],   // Purple
  ['#EC4899', '#BE185D'],   // Pink
  ['#06B6D4', '#0891B2'],   // Cyan
  ['#F97316', '#EA580C'],   // Orange
  ['#14B8A6', '#0D9488'],   // Teal
  ['#A855F7', '#7C3AED'],   // Violet
  ['#EF4444', '#B91C1C'],   // Dark red
  ['#6366F1', '#4338CA'],   // Indigo
  ['#84CC16', '#4D7C0F'],   // Lime
  ['#0EA5E9', '#0369A1'],   // Sky blue
  ['#F43F5E', '#BE123C'],   // Rose
];

/** Deterministic gradient from team name */
export function getTeamGradient(name: string): [string, string] {
  if (!name) return TEAM_GRADIENTS[0];
  let hash = 0;
  for (let i = 0; i < name.length; i++) {
    const ch = name.charCodeAt(i);
    hash = ((hash << 5) - hash) + ch;
    hash |= 0; // convert to 32-bit int
  }
  return TEAM_GRADIENTS[Math.abs(hash) % TEAM_GRADIENTS.length];
}

/** Extract initials (2 chars) from a team name */
export function getTeamInitials(nameCn?: string | null, shortName?: string | null, nameEn?: string | null): string {
  const src = shortName || nameCn || nameEn || '';
  // If short name is 2+ chars, use first 2
  if (src.length >= 2) return src.slice(0, 2);
  // If it's a single char, pad
  if (src.length === 1) return src;
  // Fallback
  return 'FC';
}

// ── Combined logo URL ──────────────────────────────────────

/**
 * Get the best possible logo URL for a team.
 * Returns flag CDN URL for national teams, null for club teams
 * (which should use the TeamLogo component's fallback rendering).
 */
export function getTeamLogoUrl(
  nameCn?: string | null,
  nameEn?: string | null,
  country?: string | null,
): string | null {
  return getFlagUrl(nameCn, nameEn, country);
}
