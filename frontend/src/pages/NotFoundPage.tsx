import { Compass } from 'lucide-react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/Feedback'
import { PageContainer } from '@/components/ui/PageHeader'

export function NotFoundPage() {
  const navigate = useNavigate()
  return (
    <PageContainer>
      <EmptyState
        icon={Compass}
        title="This page doesn't exist"
        description="The link may be outdated, or the page may have moved."
        actions={<Button onClick={() => navigate('/')}>Go to home</Button>}
      />
    </PageContainer>
  )
}
