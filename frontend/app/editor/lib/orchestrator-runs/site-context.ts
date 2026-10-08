/**
 * The site the conversation is about: set when the user saves a selection (site-map slice), read
 * when a typed question needs a parcel (the law artifact's 조문 tab, the Law Agent's context).
 * One per browser session, like the feed.
 */
export interface ConversationSite {
  pnu: string
  address: string
}

let current: ConversationSite | null = null

export const setConversationSite = (site: ConversationSite | null): void => {
  current = site
}

export const conversationSite = (): ConversationSite | null => current
