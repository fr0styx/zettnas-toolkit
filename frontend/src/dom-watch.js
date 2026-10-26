// One MutationObserver for the whole page (PERF-8).
//
// The icon converter, the accessibility pass, the dialog chrome and the phone shell each used to
// watch the whole page with an observer of their own. They now subscribe here: the page is
// observed once, and only for what the current subscribers need (attribute changes, for
// example, only while someone asks for those attributes).

const subscribers = new Set();
let observer = null;
let target = null;

function wanted() {
  let characterData = false;
  const attrs = new Set();
  for (const s of subscribers) {
    if (s.characterData) characterData = true;
    for (const a of s.attributes || []) attrs.add(a);
  }
  const options = { childList: true, subtree: true };
  if (characterData) options.characterData = true;
  if (attrs.size) {
    options.attributes = true;
    options.attributeFilter = [...attrs];
  }
  return options;
}

function dispatch(records) {
  for (const s of Array.from(subscribers)) {
    if (!subscribers.has(s)) continue; // unsubscribed by an earlier handler in this batch
    const mine = records.filter(
      (r) =>
        r.type === 'childList' ||
        (r.type === 'characterData' && s.characterData) ||
        (r.type === 'attributes' && s.attributes?.includes(r.attributeName)),
    );
    if (!mine.length) continue;
    try {
      s.onRecords(mine);
    } catch (err) {
      console.warn('[ZettNAS] page watcher', err);
    }
  }
}

function reobserve() {
  if (!subscribers.size) {
    observer?.disconnect();
    observer = null;
    target = null;
    return;
  }
  const body = typeof document !== 'undefined' ? document.body : null;
  if (!body) return;
  if (!observer) observer = new MutationObserver(dispatch);
  // observing the same node again replaces the options; a new body means a new target
  if (target && target !== body) observer.disconnect();
  target = body;
  observer.observe(body, wanted());
}

/**
 * Calls onRecords with the page's mutation records: added and removed nodes always, text
 * changes when characterData is set, and changes to the listed attributes. Returns a function
 * that stops it.
 */
export function watchDom({ onRecords, characterData = false, attributes = [] }) {
  const sub = { onRecords, characterData, attributes };
  subscribers.add(sub);
  reobserve();
  return () => {
    if (!subscribers.delete(sub)) return;
    // records already queued for the old options go to whoever is still subscribed
    const queued = observer?.takeRecords() || [];
    if (queued.length) dispatch(queued);
    reobserve();
  };
}

/** Each node added to the page, from a batch of records. */
export function addedNodes(records) {
  const out = [];
  for (const r of records) if (r.type === 'childList') r.addedNodes.forEach((n) => out.push(n));
  return out;
}

export const _test = {
  options: () => (observer ? wanted() : null),
  count: () => subscribers.size,
};
