import type { DocumentOut, Review, ReviewComment } from '../api/client'

export const doc: DocumentOut = {
  id: 1,
  filename: 'report.md',
  doc_type: 'report',
  language: 'en',
  title: 'Order system migration',
  warnings: [],
  figure_count: 1,
  char_count: 100,
  created_at: '2026-10-28T10:00:00',
  duplicate: false,
  sections: [
    {
      id: 'S1',
      heading: '1 Approach',
      level: 1,
      paragraphs: [
        {
          id: 'S1.P1',
          text: 'We moved the order system to microservices.',
          page: null,
          kind: 'text',
          figure: null,
        },
      ],
    },
    {
      id: 'S2',
      heading: '2 Results',
      level: 1,
      paragraphs: [
        {
          id: 'S2.P1',
          text: 'Users are much happier now.',
          page: null,
          kind: 'text',
          figure: null,
        },
        {
          id: 'S2.P2',
          text: '[Figure] Figure 1 Deploy time',
          page: null,
          kind: 'figure',
          figure: {
            image_id: 'a'.repeat(32),
            file: 'a.png',
            source: 'embedded',
            caption: 'Figure 1 Deploy time',
            alt_text: null,
            chart_data: null,
            analysable: true,
          },
        },
      ],
    },
  ],
}

export function comment(over: Partial<ReviewComment>): ReviewComment {
  return {
    id: 1,
    section_id: 'S2',
    paragraph_id: 'S2.P1',
    quote: 'much happier',
    anchored: true,
    category: 'evidence',
    severity: 'high',
    problem: 'Happier is not measured.',
    suggestion: 'Add the survey result.',
    revision_steps: ['Run a survey', 'Report the score'],
    standard_refs: ['rubric.md: every claim needs data'],
    origin: 'ai',
    status: 'pending',
    mentor_text: null,
    ...over,
  }
}

const field = (text: string | null) => ({
  text,
  not_found: text === null,
  source_ids: text ? ['S1.P1'] : [],
})

export function review(over: Partial<Review> = {}): Review {
  const comments = over.comments ?? [
    comment({ id: 1 }),
    comment({
      id: 2,
      paragraph_id: 'S1.P1',
      section_id: 'S1',
      quote: null,
      severity: 'medium',
      problem: 'Why microservices?',
      category: 'logic',
    }),
    comment({
      id: 3,
      paragraph_id: null,
      section_id: null,
      anchored: false,
      quote: null,
      problem: 'No references section.',
      origin: 'rule',
      category: 'citation',
      severity: 'low',
    }),
    comment({
      id: 4,
      paragraph_id: 'S2.P2',
      quote: null,
      problem: 'Axis has no unit.',
      category: 'format',
      severity: 'low',
    }),
    comment({ id: 5, problem: 'Rejected idea.', status: 'rejected', severity: 'low' }),
  ]
  return {
    id: 10,
    document_id: 1,
    status: 'done',
    stage: 'done',
    model: 'm',
    errors: [],
    warnings: [],
    summary: {
      research_problem: field('Slow deploys of the order system.'),
      objectives: field('Deploy in minutes.'),
      technical_approach: field('Microservices.'),
      main_conclusions: field('Deploys take 6 minutes.'),
      innovations: field(null),
      limitations: field(null),
      outline: [],
      title: 'Order system migration',
      warnings: [],
    },
    figures_analysed: 1,
    overall_feedback: null,
    created_at: '2026-10-28T10:00:00',
    comment_count: comments.length,
    figures: {
      ['a'.repeat(32)]: {
        kind: 'chart',
        summary: 'Bar chart of deploy minutes',
        key_data: ['before: 45', 'after: 6'],
        readable: true,
        issues: [],
      },
    },
    ...over,
    comments,
  }
}
