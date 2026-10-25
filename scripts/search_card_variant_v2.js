/* Pure closed relationship: counts are saturated at 2 (meaning many).
 * No DOM, I/O, selectors, callbacks, or caller-defined variant names.
 */
const SEARCH_CARD_VARIANT_V2 = Object.freeze({
  version: 'search-card-variant-v2',
  select: function select(legacyCount, featuredCount, featuredShape) {
    if (![0, 1, 2].includes(legacyCount) || ![0, 1, 2].includes(featuredCount) ||
        typeof featuredShape !== 'boolean') throw Error('dom_unavailable');
    if (legacyCount === 1 && featuredCount === 0) return 'legacy';
    if (legacyCount === 0 && featuredCount === 1 && featuredShape) return 'featured';
    throw Error('dom_unavailable');
  }
});
if (typeof module !== 'undefined') module.exports = SEARCH_CARD_VARIANT_V2;
