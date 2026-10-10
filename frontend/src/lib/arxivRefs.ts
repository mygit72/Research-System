/** arXiv ids or links separated by lines, spaces or commas; repeats dropped. */
export const parseRefs = (text: string) => [...new Set(text.split(/[\s,]+/).filter(Boolean))]
