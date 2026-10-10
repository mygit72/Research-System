import { useNavigate, useSearchParams } from 'react-router-dom'
import { BookmarksList } from '@/components/organization/Bookmarks'
import { NotesList } from '@/components/organization/Notes'
import { PageContainer, PageHeader } from '@/components/ui/PageHeader'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/Tabs'
import { anchorLink } from '@/lib/organization'

/** Everything the user wrote down or saved, across the library. */
export function NotesPage() {
  const [params, setParams] = useSearchParams()
  const navigate = useNavigate()
  const tab = params.get('tab') === 'bookmarks' ? 'bookmarks' : 'notes'
  return (
    <PageContainer>
      <PageHeader
        title="Notes & bookmarks"
        description="Your notes on papers and collections, and the papers, passages, figures, tables and citations you saved."
      />
      <Tabs value={tab} onValueChange={(value) => setParams({ tab: value }, { replace: true })}>
        <TabsList className="mb-6">
          <TabsTrigger value="notes">Notes</TabsTrigger>
          <TabsTrigger value="bookmarks">Bookmarks</TabsTrigger>
        </TabsList>
        <TabsContent value="notes">
          {/* New notes are written on a paper or a collection; here they're read and edited. */}
          <NotesList
            showPaper
            composer={false}
            onOpenAnchor={(note) =>
              note.document_id && navigate(anchorLink(note.document_id, note.anchor), { state: { boxes: note.anchor?.boxes } })
            }
          />
        </TabsContent>
        <TabsContent value="bookmarks">
          <BookmarksList showPaper />
        </TabsContent>
      </Tabs>
    </PageContainer>
  )
}
