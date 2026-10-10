/** Single source of truth for navigation: used by the sidebar, mobile drawer and ⌘K palette. */
import {
  BookOpen,
  FileText,
  FlaskConical,
  FolderOpen,
  Gauge,
  GitCompareArrows,
  HelpCircle,
  Lightbulb,
  Home,
  MessagesSquare,
  Network,
  NotebookPen,
  Search,
  Settings,
  type LucideIcon,
} from 'lucide-react'

export interface NavItem {
  label: string
  to: string
  icon: LucideIcon
  description: string
}

export const primaryNav: NavItem[] = [
  { label: 'Home', to: '/', icon: Home, description: 'Your research workspace' },
  {
    label: 'Papers',
    to: '/papers',
    icon: BookOpen,
    description: 'Upload, organize and read your research papers',
  },
  {
    label: 'Search',
    to: '/search',
    icon: Search,
    description: 'Find passages across your library by meaning or exact terms',
  },
  {
    label: 'Research Chat',
    to: '/chat',
    icon: MessagesSquare,
    description: 'Ask questions and get answers with citations to your papers',
  },
  {
    label: 'Compare',
    to: '/compare',
    icon: GitCompareArrows,
    description: 'Put 2 to 5 papers side by side: methods, data, results and limitations',
  },
  {
    label: 'Collections',
    to: '/collections',
    icon: FolderOpen,
    description: 'Group papers, notes and chats by project, thesis or course',
  },
  {
    label: 'Notes',
    to: '/notes',
    icon: NotebookPen,
    description: 'Your notes and bookmarks across papers and collections',
  },
  {
    label: 'Reviews & Research',
    to: '/reviews',
    icon: FileText,
    description: 'Literature reviews, research gaps, disagreements and deep research, with citations',
  },
  {
    label: 'Research Projects',
    to: '/projects',
    icon: Lightbulb,
    description: 'Plan a project from an idea: questions, background, gaps, methods and a paper outline',
  },
  {
    label: 'Knowledge Graph',
    to: '/graph',
    icon: Network,
    description: 'Topics, datasets, methods, authors and citations across your papers',
  },
  {
    label: 'Evaluation',
    to: '/evaluation',
    icon: FlaskConical,
    description: 'Measure retrieval and answer quality (for technical users)',
  },
]

export const secondaryNav: NavItem[] = [
  { label: 'Usage', to: '/usage', icon: Gauge, description: 'Model calls, tokens, cost and latency' },
  { label: 'Settings', to: '/settings', icon: Settings, description: 'Account, AI and appearance' },
  { label: 'Help', to: '/help', icon: HelpCircle, description: 'Guides and keyboard shortcuts' },
]

export const allNav = [...primaryNav, ...secondaryNav]
