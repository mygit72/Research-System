import { useQuery } from '@tanstack/react-query'
import { systemApi } from '@/services/api'
import type { LLMStatus } from '@/types/api'

/** Where the model that answers runs, and so who receives the questions sent to it. */
function modelLine(llm: LLMStatus): string {
  if (llm.source === 'none')
    return 'None chosen yet, so nothing is sent to any model. Each choice in Settings → AI says where it runs.'
  if (llm.source === 'free')
    return `The free shared model runs at ${llm.host ?? 'another company'}: your questions and the passages needed to answer them are sent there, and a free service may keep them. Not for confidential work.`
  if (!llm.remote) return 'It runs on the same computer as this app. Nothing is sent anywhere else.'
  if (llm.source === 'user')
    return `Your questions and the passages needed to answer them go to ${llm.label ?? llm.provider} under your own key and its terms.`
  return `Your questions and the passages needed to answer them go to this server’s model provider (${llm.provider}).`
}

/** Settings → Privacy: who can and can't see a user's papers, questions and answers. */
export function PrivacyFacts() {
  const config = useQuery({ queryKey: ['config'], queryFn: systemApi.config, staleTime: Infinity })
  const status = useQuery({ queryKey: ['ai-status'], queryFn: systemApi.aiStatus })
  // A copy someone runs for themselves: "the server" is their own computer. A site with a
  // shared free model is a site for other people, whatever its environment is called.
  const ownCopy = config.data ? config.data.environment !== 'production' && !config.data.free_tier : false
  const facts: [string, string][] = [
    [
      'Other people',
      'Nobody. Nothing you add is public, there are no shared or public links, and no account can open another account’s papers, notes or chats.',
    ],
    ownCopy
      ? ['Where it is kept', 'On this computer, in the app’s own folder. This copy sends no usage data anywhere.']
      : [
          'This site',
          'Your papers, notes and chats are kept on its server so they can be searched and answered from. The app has no administrator view of them and never writes them to its logs. As with any website, though, whoever runs the server can technically reach what is stored on it. For work nobody else may ever see, run the app on your own computer.',
        ],
  ]
  if (status.data) facts.push(['The model that answers', modelLine(status.data.llm)])
  return (
    <div>
      <h3 className="text-small font-medium text-text">Who can see your work</h3>
      <dl className="mt-2 space-y-2">
        {facts.map(([who, what]) => (
          <div key={who} className="text-small">
            <dt className="font-medium text-text">{who}</dt>
            <dd className="text-muted">{what}</dd>
          </div>
        ))}
      </dl>
    </div>
  )
}
