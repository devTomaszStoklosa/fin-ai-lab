// Categorical slots in fixed order, validated for colour-vision deficiency
// against this app's white card surface (dataviz validator, light mode).
// A portfolio keeps its slot by its position in the list, never by rank --
// hiding one never repaints the others. Past eight, a neutral grey: a
// generated ninth hue would be indistinguishable.
const SERIES_COLORS = ['#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#4a3aa7', '#e34948']
const OVERFLOW_COLOR = '#8a8478'

export function seriesColor(index: number): string {
  return SERIES_COLORS[index] ?? OVERFLOW_COLOR
}
