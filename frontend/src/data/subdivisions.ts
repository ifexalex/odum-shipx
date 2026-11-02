/**
 * State / province / region lists, keyed by ISO 3166-1 alpha-2 country code.
 *
 * Deliberately NOT exhaustive for every country. A complete ISO 3166-2 dataset
 * is tens of thousands of entries, and most of it would never be selected by
 * this business. What is covered is the set ShipX actually operates in, led by
 * the two that matter operationally:
 *
 *   NG — the destination market. Warehouse addresses and release-note
 *        letterheads are Nigerian, so this is the list that gets used daily.
 *   CN — the origin market.
 *
 * For any country NOT listed here, `subdivisionsFor` returns undefined and the
 * caller must fall back to a free-text input. That is a deliberate, visible
 * degradation rather than an empty dropdown that blocks data entry — see
 * `StateSelect`.
 */

/** Country code → ordered subdivision names. Names are what gets stored. */
const SUBDIVISIONS: Readonly<Record<string, readonly string[]>> = {
  // 36 states + the Federal Capital Territory.
  NG: [
    'Abia', 'Adamawa', 'Akwa Ibom', 'Anambra', 'Bauchi', 'Bayelsa', 'Benue', 'Borno',
    'Cross River', 'Delta', 'Ebonyi', 'Edo', 'Ekiti', 'Enugu', 'Federal Capital Territory',
    'Gombe', 'Imo', 'Jigawa', 'Kaduna', 'Kano', 'Katsina', 'Kebbi', 'Kogi', 'Kwara',
    'Lagos', 'Nasarawa', 'Niger', 'Ogun', 'Ondo', 'Osun', 'Oyo', 'Plateau', 'Rivers',
    'Sokoto', 'Taraba', 'Yobe', 'Zamfara',
  ],
  // Mainland divisions: 22 provinces + 5 autonomous regions + 4 municipalities.
  // Hong Kong and Macao are separate entries in COUNTRIES, so they are not here.
  CN: [
    'Anhui', 'Beijing', 'Chongqing', 'Fujian', 'Gansu', 'Guangdong', 'Guangxi', 'Guizhou',
    'Hainan', 'Hebei', 'Heilongjiang', 'Henan', 'Hubei', 'Hunan', 'Inner Mongolia',
    'Jiangsu', 'Jiangxi', 'Jilin', 'Liaoning', 'Ningxia', 'Qinghai', 'Shaanxi', 'Shandong',
    'Shanghai', 'Shanxi', 'Sichuan', 'Tianjin', 'Tibet', 'Xinjiang', 'Yunnan', 'Zhejiang',
  ],
  GH: [
    'Ahafo', 'Ashanti', 'Bono', 'Bono East', 'Central', 'Eastern', 'Greater Accra',
    'North East', 'Northern', 'Oti', 'Savannah', 'Upper East', 'Upper West', 'Volta',
    'Western', 'Western North',
  ],
  ZA: [
    'Eastern Cape', 'Free State', 'Gauteng', 'KwaZulu-Natal', 'Limpopo', 'Mpumalanga',
    'North West', 'Northern Cape', 'Western Cape',
  ],
  GB: ['England', 'Northern Ireland', 'Scotland', 'Wales'],
  US: [
    'Alabama', 'Alaska', 'Arizona', 'Arkansas', 'California', 'Colorado', 'Connecticut',
    'Delaware', 'District of Columbia', 'Florida', 'Georgia', 'Hawaii', 'Idaho', 'Illinois',
    'Indiana', 'Iowa', 'Kansas', 'Kentucky', 'Louisiana', 'Maine', 'Maryland',
    'Massachusetts', 'Michigan', 'Minnesota', 'Mississippi', 'Missouri', 'Montana',
    'Nebraska', 'Nevada', 'New Hampshire', 'New Jersey', 'New Mexico', 'New York',
    'North Carolina', 'North Dakota', 'Ohio', 'Oklahoma', 'Oregon', 'Pennsylvania',
    'Rhode Island', 'South Carolina', 'South Dakota', 'Tennessee', 'Texas', 'Utah',
    'Vermont', 'Virginia', 'Washington', 'West Virginia', 'Wisconsin', 'Wyoming',
  ],
}

/**
 * Subdivisions for a country, or undefined when none are on file.
 *
 * Undefined is a meaningful answer, not an error: the caller should offer a
 * free-text input instead of an empty dropdown.
 */
export function subdivisionsFor(countryCode: string | null | undefined): readonly string[] | undefined {
  return countryCode ? SUBDIVISIONS[countryCode.toUpperCase()] : undefined
}

/** What a subdivision is called in a given country, for labels and placeholders. */
const SUBDIVISION_LABELS: Readonly<Record<string, string>> = {
  NG: 'State',
  CN: 'Province',
  GH: 'Region',
  ZA: 'Province',
  GB: 'Country',
  US: 'State',
}

export function subdivisionLabelFor(countryCode: string | null | undefined): string {
  return (countryCode && SUBDIVISION_LABELS[countryCode.toUpperCase()]) || 'State / province'
}

/** Case-insensitive match of a stored name against a country's list. */
export function matchSubdivision(
  countryCode: string | null | undefined,
  value: string | null | undefined,
): string | undefined {
  if (!value) return undefined
  const list = subdivisionsFor(countryCode)
  if (!list) return undefined
  const needle = value.trim().toLowerCase()
  return list.find((s) => s.toLowerCase() === needle)
}
