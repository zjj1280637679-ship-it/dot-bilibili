/* v3 bounded mixed-card search. Trusted-host additive composition. Compose pinned files into ONE local DOM evaluation closure.
 * Only search layout changes. Metadata/comments delegate through the frozen v1
 * capture port; variant selection is a separate finite pure relation.
 * No caller-selected code, selectors, navigation, network, or hidden state.
 */
const HOST_CAPTURE_RECIPES_V3 = (() => {
  const legacyCapture = (typeof HOST_CAPTURE_RECIPES !== 'undefined' ? HOST_CAPTURE_RECIPES :
    require('./host_capture_recipes.js')).capture;
  const selectVariant = (typeof SEARCH_CARD_VARIANT_V2 !== 'undefined' ? SEARCH_CARD_VARIANT_V2 :
    require('./search_card_variant_v2.js')).select;
  const classify = (typeof SEARCH_CARD_SCOPE_V3 !== 'undefined' ? SEARCH_CARD_SCOPE_V3 :
    require('./search_card_scope_v3.js')).classify;
  return Object.freeze({
    version: 'host-capture-v3',
    capture: function capture({kind, limit = 3}) {
      if (!['search', 'video', 'comments'].includes(kind) ||
          !Number.isInteger(limit) || limit < 1 || limit > 3) throw Error('request_scope');
      if (kind !== 'search') {
        const result = legacyCapture({kind, limit});
        result.recipe_version = 'host-capture-v3';
        return result;
      }
    const started = Date.now();
    const initialURL = document.URL;
    const rendered = el => {
      if (!el) return false;
      const r = el.getBoundingClientRect(), s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.display !== 'none' &&
        s.visibility !== 'hidden' && s.visibility !== 'collapse';
    };
    const intersects = el => {
      if (!rendered(el)) return false;
      const r = el.getBoundingClientRect();
      return r.bottom > 0 && r.right > 0 && r.top < innerHeight && r.left < innerWidth;
    };
    const text = (el, bound, viewport = false) => {
      if (!(viewport ? intersects(el) : rendered(el))) return '';
      const value = el.innerText.replace(/\s+/gu, ' ').trim();
      if (Array.from(value).length > bound) throw Error('dom_unavailable');
      return value;
    };
    const geometry = el => {
      if (!el) return {present:false,rendered:false,intersects:false,rect:null};
      const r=el.getBoundingClientRect();
      return {present:true,rendered:rendered(el),intersects:intersects(el),
        rect:{top:r.top,left:r.left,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
    };
    const result = {recipe_version:'host-capture-v3', observed_url:initialURL,
      diagnostics:{viewport:{width:innerWidth,height:innerHeight}}};
    if (kind === 'search') {
      const cards = Array.from(document.querySelectorAll('.bili-video-card'));
      // Absence of a recognized result card is not proof of an empty page.
      // Empty-result DOM needs a separately verified versioned selector.
      if (!cards.length) throw Error('dom_unavailable');
      result.diagnostics.recognized_card_count=cards.length;
      result.diagnostics.selected_fields=[];
      result.raw_hrefs = [];
      const visible = cards.filter(intersects);
      const window = visible.slice(0, 10);
      result.diagnostics.coverage = {scope:'visible_subset', intersecting_card_count:visible.length,
        inspected_card_count:window.length, window_truncated:visible.length > 10,
        selected_source_indices:[], excluded:[]};
      result.items = [];
      for (const [sourceIndex, card] of window.entries()) {
        const legacy = Array.from(card.querySelectorAll('.bili-video-card__info--tit'));
        const featured = Array.from(card.querySelectorAll('.bili-video-card__av--tit'));
        const featuredShape = card.matches('.bili-video-card.bili-video-card-grid') &&
          featured.length === 1 && featured[0].matches('h3.bili-video-card__av--tit.text_ellipsis');
        const variant = selectVariant(Math.min(legacy.length, 2), Math.min(featured.length, 2), featuredShape);
        const heading = variant === 'legacy' ? legacy[0] : featured[0];
        const authorSelector = variant === 'legacy' ? '.bili-video-card__info--author' : '.bili-video-card__av--author';
        if (!intersects(heading)) throw Error('dom_unavailable');
        const anchor = heading.closest('a');
        const raw = anchor && anchor.getAttribute('href');
        if (typeof raw !== 'string') throw Error('target_mismatch');
        const title = text(heading, 500, true);
        const identity = classify(raw, !!title, !!anchor && card.contains(anchor));
        if (identity.kind !== 'video') {
          result.diagnostics.coverage.excluded.push({source_index:sourceIndex, reason:identity.kind});
          continue;
        }
        result.diagnostics.coverage.selected_source_indices.push(sourceIndex);
        result.raw_hrefs.push(raw);
        result.diagnostics.selected_fields.push({variant,card:geometry(card),title:geometry(heading),
          uploader:geometry(card.querySelector(authorSelector)),
          duration:geometry(card.querySelector('.bili-video-card__stats__duration'))});
        const displayed_counts = Array.from(card.querySelectorAll('.bili-video-card__stats--item'))
          .filter(intersects).map(el => text(el, 100, true)).filter(Boolean);
        if (displayed_counts.length > 5) throw Error('dom_unavailable');
        result.items.push({title, url:identity.url, bvid:identity.bvid,
          uploader:text(card.querySelector(authorSelector), 200, true),
          duration:text(card.querySelector('.bili-video-card__stats__duration'), 40, true), displayed_counts});
      }
    }
    if (document.URL !== initialURL) throw Error('target_mismatch');
    result.captured_at = Date.now()/1000;
    result.read_code_ms = Date.now()-started;
    return result;
    }
  });
})();
if (typeof module !== 'undefined') module.exports = HOST_CAPTURE_RECIPES_V3;
