import { useMutation, useQueryClient } from '@tanstack/react-query'
import { FlaskConical } from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/Button'
import { demoApi } from '@/services/api'

/** Demo mode: adds the three synthetic sample papers so a new library has something to explore. */
export function SamplePapersButton() {
  const queryClient = useQueryClient()
  const add = useMutation({
    mutationFn: demoApi.samplePapers,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: ['documents'] })
      void queryClient.invalidateQueries({ queryKey: ['collections'] })
      toast.success(
        result.added
          ? `${result.added} sample papers added — they'll be ready to search in a moment.`
          : 'The sample papers are already in your library.',
        { description: 'Synthetic papers written for demonstrating the platform, in the “Sample papers” collection.' },
      )
    },
    onError: (error) => toast.error(error.message),
  })
  return (
    <Button variant="secondary" onClick={() => add.mutate()} loading={add.isPending}>
      <FlaskConical className="size-4" aria-hidden /> Try sample papers
    </Button>
  )
}
