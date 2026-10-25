/* First-party pure classification. Exclusions are observations, never targets. */
const SEARCH_CARD_SCOPE_V3 = Object.freeze({
  version: 'search-card-scope-v3',
  classify: function classify(raw, titleReady, containedAnchor) {
    if (titleReady !== true || containedAnchor !== true) throw Error('dom_unavailable');
    if (typeof raw !== 'string' || raw.length > 8192 || /[\s\\\u0000-\u001f\u007f]/u.test(raw))
      throw Error('target_mismatch');
    const url = raw.startsWith('//') ? 'https:' + raw : raw;
    const video = /^https:\/\/www\.bilibili\.com\/(?:en\/)?video\/(BV[0-9A-Za-z]{10})\/?$/.exec(url);
    if (video) return Object.freeze({kind:'video', url, bvid:video[1]});
    // Query bytes are opaque, never decoded, followed, or returned. Exact path
    // family is positive evidence of a non-video surface, not an allowlisted origin.
    if (/^https:\/\/cm\.bilibili\.com\/cm\/api\/fees\/pc\/sync\/v2(?:\?[^#]*)?$/.test(url))
      return Object.freeze({kind:'advertisement'});
    if (/^https:\/\/www\.bilibili\.com\/cheese\/play\/ss[1-9][0-9]{0,19}\/?(?:\?[^#]*)?$/.test(url))
      return Object.freeze({kind:'course'});
    throw Error('target_mismatch');
  }
});
if (typeof module !== 'undefined') module.exports = SEARCH_CARD_SCOPE_V3;
