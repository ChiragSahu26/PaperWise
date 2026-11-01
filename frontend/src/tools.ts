// The tools that live on the sheets. Order matters: index 0 is the front sheet
// (bottom of the final stack); the last index is the sheet at the back (top).

export type ToolId = 'ask' | 'library' | 'reader' | 'check' | 'related' | 'notes' | 'connections' | 'similarity'

export interface ToolMeta {
  id: ToolId
  title: string
  blurb: string
  detail: string
  /** false while the tool is still to be wired to the backend */
  ready: boolean
}

export const TOOLS: ToolMeta[] = [
  {
    id: 'ask',
    title: 'Ask your papers',
    blurb: 'Answers come only from your documents',
    detail: 'Every claim carries a numbered source. If the papers do not say, PaperWise says so.',
    ready: true,
  },
  {
    id: 'library',
    title: 'Add papers',
    blurb: 'PDFs, slides, sheets and notes',
    detail: 'Drop files in. Scanned pages are read automatically and two-column layouts stay in order.',
    ready: true,
  },
  {
    id: 'reader',
    title: 'Read with highlights',
    blurb: 'Jump to the exact passage',
    detail: 'Open the cited page with the passage marked, right where the paper says it.',
    ready: true,
  },
  {
    id: 'check',
    title: 'Check a paper',
    blurb: 'Recent? Well backed? Still used?',
    detail: 'Age, citations, retractions and code activity, plus videos and articles to learn it.',
    ready: false,
  },
  {
    id: 'related',
    title: 'Related chats',
    blurb: 'Earlier questions on the same topic',
    detail: 'Chats are grouped by topic, and a repeated question points you back to its answer.',
    ready: false,
  },
  {
    id: 'notes',
    title: 'Notes',
    blurb: 'Pin a thought to a passage',
    detail: 'Write notes beside the text they come from, search them, and export them.',
    ready: false,
  },
  {
    id: 'connections',
    title: 'Connections',
    blurb: 'Datasets, methods, conflicts',
    detail: 'See how your papers link, and where two papers report different results.',
    ready: false,
  },
  {
    id: 'similarity',
    title: 'Similarity check',
    blurb: 'Compare writing with your sources',
    detail: 'Highlight sentences that closely match your papers, before you hand work in.',
    ready: false,
  },
]
