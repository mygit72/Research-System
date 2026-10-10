import { useSearchParams } from 'react-router-dom'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { AuthorsView, EntitiesView } from './DirectoryViews'
import { GraphView } from './GraphView'
import { TimelineView } from './TimelineView'
import { TopicsView } from './TopicsView'

const VIEWS = ['graph', 'topics', 'timeline', 'entities', 'authors'] as const
type ViewName = (typeof VIEWS)[number]

export function KnowledgePage() {
  const [params, setParams] = useSearchParams()
  const requested = params.get('view') as ViewName | null
  const view: ViewName = requested && VIEWS.includes(requested) ? requested : 'graph'
  const setView = (value: string) =>
    setParams(value === 'graph' ? {} : { view: value })
  return (
    <PageContainer width="wide">
      <PageHeader
        title="Knowledge Graph"
        description="How your papers connect: topics, the datasets, models and methods they use and propose, who wrote them and what they cite."
      />
      <Tabs value={view} onValueChange={setView}>
        <TabsList className="mb-6">
          <TabsTrigger value="graph">Graph</TabsTrigger>
          <TabsTrigger value="topics">Topics</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
          <TabsTrigger value="entities">Datasets & methods</TabsTrigger>
          <TabsTrigger value="authors">Authors</TabsTrigger>
        </TabsList>
        <TabsContent value="graph">{view === 'graph' && <GraphView />}</TabsContent>
        <TabsContent value="topics">{view === 'topics' && <TopicsView />}</TabsContent>
        <TabsContent value="timeline">{view === 'timeline' && <TimelineView />}</TabsContent>
        <TabsContent value="entities">{view === 'entities' && <EntitiesView />}</TabsContent>
        <TabsContent value="authors">{view === 'authors' && <AuthorsView />}</TabsContent>
      </Tabs>
    </PageContainer>
  )
}
