# Video-reference relationship gate

This additive implementation models both functionality and the relation
between modules; it adds no business primitive and no generalized URL router.

## Modules and explicit relation

| Module | Responsibility | Permitted relation |
|---|---|---|
| `bili_video_reference.contracts` | Pure literal grammar and normalization | reference → `{query=BVID, select=BVID, comments}` |
| `bili_video_reference.adapter` | Composition edge / relation adapter | normalized intent → one `facade.search_read` call |
| `bili_video_reference.cli` | Optional trusted transport binding | exact tool envelope + trusted profile/ID → adapter |
| Existing facade/workflow | Existing execution, projection, budgets and ledger | unchanged existing chain |

The adapter imports the narrow `search_read` function, not a whole kernel or
browser object. Python still initializes the facade package: this is a semantic
interface boundary, **not** a sandbox, isolated loader, or dependency-free module.
`envelope` is its second, pure formatting dependency. Host profile and invocation
ID pass through unchanged; model arguments cannot supply either. The composition
edge is already a separate tiny module, so a generic plugin registry, new class
hierarchy, second ledger, or additional dependency-injection framework would add
complexity without strengthening this contract.

### Edge contract

- Preconditions: trusted host context; grammar-valid video reference and boolean
  comments. The CLI checks trusted ID shape; the facade retains execution checks.
- Invalid arguments/reference: reject before the execution port.
- Accepted aliases: BVID, exact canonical HTTPS URL, and URL with final slash map
  to identical query/selection/comments intent under the same trusted host ID.
- Invoke exactly once, return the same port result without reinterpretation.
- An absent search selection, conflict, or unknown outcome has **no** direct URL
  fallback, implicit retry, new ID, or broader authority.
- Existing search port is assumed to enforce its documented exact-selection,
  budget, and ledger semantics. This gate does not re-prove those implementations.

## Minimal additive verification gate

Run `python scripts/check_video_reference_model.py` and
`python -m unittest tests.test_video_reference_relation`.

The independent pure model enumerates two abstract BVIDs, three alias forms,
valid/invalid grammar membership, two comments values, two host IDs and four
opaque port outcomes. It explores **193 reachable states**. Five injected defects
must each fail an invariant: accepting invalid input, changing host identity,
first-visible substitution, double invocation, and direct-navigation fallback.
Alias equivalence is separately checked across the complete abstract domain.

The checker reuses the existing bounded explorer with unchanged defaults:
10,000 states, 5 seconds, 32 MiB Python traced allocations **per exploration**.
Budget exhaustion is failure, not a partial pass. Reported elapsed time and memory
are measured each run; traced allocations are not process RSS. Mutant explorations
are separate from the base model, not claimed to share a five-second total budget.

Concrete correspondence tests cover 96 valid combinations (two BVIDs × three
aliases × two comments × two host IDs × four outcomes), unchanged result identity,
exact one-call arguments, and representative rejects. No browser or ledger is
created. These tests plus exhaustive finite abstraction checking are **not** an
implementation refinement proof, an exhaustive proof over all strings, or a proof
of browser behavior, concurrency, liveness, or the whole composed system.

### Revalidation boundary

Changing reference grammar requires contract/model correspondence review. Changing
the adapter edge requires relation model, mutations and delegation tests. Changing
the execution port's promises additionally requires the existing facade/workflow
gates; a passing local relation check cannot authorize such a change. Transport
changes require the existing new CLI tests. Host capture variants remain a
separate relation and are not silently folded into this model.
