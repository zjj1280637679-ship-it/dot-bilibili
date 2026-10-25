/* Versioned trusted-host DOM capture only. Never request-supplied code.
 * Evaluate capture with {kind:'search'|'video'|'comments',limit:1..3} in the
 * already bound, freshly verified public tab. No navigation, network, storage,
 * hidden app state, closed roots, or consent decisions occur in this recipe.
 * Preserve observed_url/raw_hrefs through host evidence. Validate receipt with
 * unchanged Python contracts BEFORE submitting. Never strip semantic queries.
 */
const HOST_CAPTURE_RECIPES = Object.freeze({
  version: 'host-capture-v1',
  capture: function capture({kind, limit = 3}) {
    if (!['search', 'video', 'comments'].includes(kind) ||
        !Number.isInteger(limit) || limit < 1 || limit > 3) throw Error('request_scope');
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
    const field = (el, bound, viewport = false) => {
      const value = text(el, bound, viewport);
      return value ? {state:'visible', value} : {state:'not_visible', value:null};
    };
    const geometry = el => {
      if (!el) return {present:false,rendered:false,intersects:false,rect:null};
      const r=el.getBoundingClientRect();
      return {present:true,rendered:rendered(el),intersects:intersects(el),
        rect:{top:r.top,left:r.left,right:r.right,bottom:r.bottom,width:r.width,height:r.height}};
    };
    const result = {recipe_version:'host-capture-v1', observed_url:initialURL,
      diagnostics:{viewport:{width:innerWidth,height:innerHeight}}};
    if (kind === 'search') {
      const cards = Array.from(document.querySelectorAll('.bili-video-card'));
      // Absence of a recognized result card is not proof of an empty page.
      // Empty-result DOM needs a separately verified versioned selector.
      if (!cards.length) throw Error('dom_unavailable');
      result.diagnostics.recognized_card_count=cards.length;
      result.diagnostics.selected_fields=[];
      result.raw_hrefs = [];
      result.items = cards.filter(intersects).slice(0, 10).map(card => {
        const heading = card.querySelector('.bili-video-card__info--tit');
        if (!intersects(heading)) throw Error('dom_unavailable');
        const anchor = heading.closest('a');
        const raw = anchor && anchor.getAttribute('href');
        if (typeof raw !== 'string') throw Error('target_mismatch');
        // Only protocol-relative same-origin spelling is resolved; raw retained.
        const url = raw.startsWith('//') ? 'https:' + raw : raw;
        const match = /^https:\/\/www\.bilibili\.com\/(?:en\/)?video\/(BV[0-9A-Za-z]{10})\/?$/.exec(url);
        if (!match) throw Error('target_mismatch');
        result.raw_hrefs.push(raw);
        result.diagnostics.selected_fields.push({card:geometry(card),title:geometry(heading),
          uploader:geometry(card.querySelector('.bili-video-card__info--author')),
          duration:geometry(card.querySelector('.bili-video-card__stats__duration'))});
        const displayed_counts = Array.from(card.querySelectorAll('.bili-video-card__stats--item'))
          .filter(intersects).map(el => text(el, 100, true)).filter(Boolean);
        if (displayed_counts.length > 5) throw Error('dom_unavailable');
        const title = text(heading, 500, true);
        if (!title) throw Error('dom_unavailable');
        return {title, url, bvid:match[1],
          uploader:text(card.querySelector('.bili-video-card__info--author'), 200, true),
          duration:text(card.querySelector('.bili-video-card__stats__duration'), 40, true), displayed_counts};
      });
    } else if (kind === 'video') {
      const selectors = {title:'h1.video-title', uploader:'a.up-name',
        description:'.video-desc-container', duration:'.bpx-player-ctrl-time-duration'};
      const elements = Object.fromEntries(Object.entries(selectors).map(([k,s])=>[k, document.querySelector(s)]));
      const counts = document.querySelector('#arc_toolbar_report');
      if (!Object.values(elements).some(Boolean) && !counts) throw Error('dom_unavailable');
      result.diagnostics.metadata_geometry=Object.fromEntries(
        Object.entries(elements).map(([k,el])=>[k,geometry(el)]));
      result.diagnostics.metadata_geometry.displayed_counts=geometry(counts);
      result.metadata = Object.fromEntries(Object.entries(elements).map(([k,el])=>
        [k, field(el, {title:500,uploader:200,description:8000,duration:40}[k], true)]));
      const countText = text(counts, 100, true);
      result.metadata.displayed_counts = countText ? {state:'visible',value:[countText]} : {state:'not_visible',value:null};
    } else {
      const host = document.querySelector('bili-comments');
      if (!host || !host.shadowRoot) throw Error('dom_unavailable');
      const candidates = Array.from(host.shadowRoot.querySelectorAll('bili-comment-thread-renderer'));
      const rawField = (el, bound) => {
        const value = rendered(el) ? el.innerText : '';
        if (/[\u0000-\u001f\u007f-\u009f]/u.test(value) || Array.from(value).length > bound)
          throw Error('dom_unavailable');
        return value ? {state:'visible',value} : {state:'not_visible',value:null};
      };
      result.diagnostics.root_accessible=true;
      result.diagnostics.recognized_thread_count=candidates.length;
      result.diagnostics.rendered_thread_count=candidates.filter(rendered).length;
      result.diagnostics.intersecting_thread_count=candidates.filter(intersects).length;
      result.diagnostics.thread_geometry=candidates.slice(0,100).map(geometry);
      result.diagnostics.thread_geometry_truncated=candidates.length>100;
      result.extraction = 'open_shadow_dom'; result.complete = false;
      result.threads = candidates.filter(intersects).slice(0, limit).map((thread, index) => {
        if (!thread.shadowRoot) throw Error('dom_unavailable');
        const renderer = thread.shadowRoot.querySelector('bili-comment-renderer');
        if (!renderer || !renderer.shadowRoot) throw Error('dom_unavailable');
        const root = renderer.shadowRoot;
        const rich = root.querySelector('bili-rich-text');
        if (rich && !rich.shadowRoot) throw Error('dom_unavailable');
        const body = rich && rich.shadowRoot.querySelector('p#contents');
        const value = rendered(body) ? body.innerText : '';
        // Validate the whole original body BEFORE truncation; hidden invalid suffixes
        // must not be made acceptable by a 2,000-codepoint cut.
        if (/[\u0000-\u0009\u000b-\u001f\u007f-\u009f]/u.test(value)) throw Error('dom_unavailable');
        const points = Array.from(value), length = points.length;
        const textField = length ? {state:'visible',value:points.slice(0,2000).join(''),
          truncated:length > 2000,observed_original_length:length} :
          {state:'not_visible',value:null,truncated:false,observed_original_length:null};
        const r = thread.getBoundingClientRect();
        return {snapshot_position:index+1,
          visibility:r.top>=0 && r.left>=0 && r.bottom<=innerHeight && r.right<=innerWidth ? 'full':'partial',
          author:rawField(root.querySelector('#user-name'),200), text:textField,
          timestamp_display:rawField(root.querySelector('#pubdate'),100),
          like_count_display:rawField(root.querySelector('#like .count'),100)};
      });
    }
    if (document.URL !== initialURL) throw Error('target_mismatch');
    result.captured_at = Date.now()/1000;
    result.read_code_ms = Date.now()-started;
    return result;
  }
});
if (typeof module !== 'undefined') module.exports = HOST_CAPTURE_RECIPES;
