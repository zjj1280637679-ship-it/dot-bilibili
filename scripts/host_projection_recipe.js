/* HOST-ONLY fixed recipe, not an SDK/module or bridge request input.
 * Paste into the supported cua_repl after docs + fresh target verification.
 * Requires existing host-owned perfTab bound to the approved results tab.
 * Never import this from the bridge; no caller-supplied selector/code.
 * Stop on target/context drift, login, challenge, denial or layout mismatch.
 */
var hostProjectionStartedAt = Date.now() / 1000;
var hostProjection = await perfTab.playwright.evaluate(() => {
  const start = Date.now();
  const visible = el => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && r.bottom > 0 && r.right > 0 &&
      r.top < innerHeight && r.left < innerWidth &&
      s.display !== 'none' && s.visibility !== 'hidden';
  };
  const read = el => visible(el) ? el.innerText.trim() : '';
  const cards = Array.from(document.querySelectorAll('.bili-video-card')).slice(0, 4);
  const items = cards.filter(visible).map(card => {
    const heading = card.querySelector('.bili-video-card__info--tit');
    if (!visible(heading)) throw Error('dom_unavailable');
    const link = heading.closest('a');
    let url = link.getAttribute('href');
    if (url.startsWith('//')) url = 'https:' + url;
    const match = /^https:\/\/www\.bilibili\.com\/(?:en\/)?video\/(BV[0-9A-Za-z]{10})\/$/.exec(url);
    if (!match) throw Error('target_mismatch');
    const counts = Array.from(card.querySelectorAll('.bili-video-card__stats--item')).filter(visible).map(read);
    return {title:read(heading),url,bvid:match[1],
      uploader:read(card.querySelector('.bili-video-card__info--author')),
      duration:read(card.querySelector('.bili-video-card__stats__duration')),
      displayed_counts:counts};
  });
  return {sourceURL:document.URL,items,read_code_ms:Date.now()-start,
    captured_at:Date.now()/1000};
});
var hostProjectionReturnedAt = Date.now() / 1000;
// Use hostProjection.captured_at from inside this read, never report-format time.
// Host validates actual sourceURL + tab + context against its claimed request,
// then validates items with the existing unchanged receipt contract.
// Do not print full card text in user reports; retain only hashes/lengths/parity.

