# 可分块验证预算 / compositional verification budget

**结论：当前小模型可穷举，但尚未证明 Python 实现、真实浏览器或模块组合正确。**
`check_verification_budget.py` 是初始工程警戒线（engineering tripwire），不是复杂度定理。
不能把“最高维度 > X”解释为普遍成立的天文数字证明成本；符号化方法、状态约束、性质、
对称性、归约和硬件都会影响成本。不能用测试数量冒充证明。

## Reproduce, read-only

```sh
python scripts/check_verification_budget.py
python -m unittest discover -s tests -p test_verification_budget.py -v
# Deliberate failure, exit 1; never a truncated proof pass:
python scripts/check_verification_budget.py --max-states 1
# Whole-kernel plugin retention is now forbidden (default zero):
python scripts/check_verification_budget.py --max-wide-kernel-injections 0
```

No browser, authentication, network, dependency installation or production state changes.
JSON is emitted on stdout; Python may create normal bytecode caches. The checked-in
`verification-budget.json` is a dated single-run baseline with environment and model source hashes,
not a portable performance guarantee. The checker traverses existing model transition functions,
checking every reached state invariant. Only after exhaustive bounded completion does it rerun
the original enumerator and compare its state count. Original-enumerator timing is separately
reported without tracemalloc; it is not mixed with instrumented checker timing.

## What “dimension” means

For a block, declare an abstract state schema `S = S1 × … × Sn` with finite domain sizes
`d1,…,dn`. The Cartesian upper bound is `N_product = ∏di`, and its bit-equivalent dimension
is `D_product = log2(N_product) = Σlog2(di)`. This is **not** the number of independent
variables, nor a claim that every combination is reachable. Independence must be justified,
not inferred from distinct field names. For independent composition of blocks the product
can grow; with shared state or constraints it must be re-derived.

`R` is the number of distinct states actually reachable from the declared initial state under
all modeled transitions. `R ≤ N_product` when the declared schema covers all transitions.
`D_reachable = log2(R)` is a summary, not a predictive upper bound.
The checker reports **observed marginal** cardinalities, their product and bit sum: distinct
values of each flattened field across the explored states. This is NOT a pre-declared schema,
NOT a proof of independence, and NOT a bound on future model changes. It is an upper bound
for combinations of values observed in this completed run only. On incomplete searches even
these marginal domains are partial. Fixed model parameters (accounts/operations/resource count)
are part of scope, not extra state unless they can change during a transition.

A queue of capacity `q` over `m` message variants contributes at most `Σ(m^k), k=0..q`
ordered queue states. Multiple outstanding IDs, concurrent actors, local state, in-flight
messages and scheduling choices must be represented; a single-request model must not be
silently reused as proof for an unbounded queue. Interleavings can add paths even without
adding distinct states. Current BFS stores states and explores transitions, roughly `O(R+E)`
visits plus Python hashing/allocation and transition costs; no universal seconds-per-bit law.

## Initial enforceable limits and rationale

| Gate | Initial limit | Basis / status |
|---|---:|---|
| Reachable states per model instance | 10,000 | Largest measured 676: ~14.8× headroom; larger changes need review |
| Instrumented runtime per instance | 5 seconds | Baseline <0.2 seconds here; CI noise allowed, not a guaranteed throughput |
| Peak traced Python allocations per instance | 32 MiB | Baseline <0.4 MiB; generous interpreter/allocation margin |
| Unique local imported-module dependencies | 16 per module | Existing maximum CLI 15; small integration headroom, not state dimension |
| Retained whole-kernel injections in plugins | 0 | Narrow SelectionConsumer adapter implemented; callback provider dependency stays explicit |

These are suggested engineering policy values, **validated only as passing current models
and failing deliberately lowered limits**. They are not validated scaling laws or a claim that
10,001 states is astronomical. Budget failure means `budget_exceeded`/exit 1, never “safe”.
An invariant failure also fails. A dependency failure fails the overall report even if models pass.
Review model completeness and interface obligations before increasing any threshold.

Memory is `tracemalloc` peak traced allocations, **not process RSS, native memory, or OS enforced
limits**. It starts after model imports; earlier allocations are excluded. Limits are checked
at state/edge boundaries; one transition callback can overshoot/block before returning.
The existing small enumerators terminate here; this is not a sandbox for arbitrary hostile code.
State-limit detection may discover one excess state and then stops immediately. Tests exercise
state, runtime, memory, invariant and dependency failures; this is fail-closed gate evidence,
not proof of the checker itself.

## Measured baseline

Run on 2026-10-25, Python 3.12.14, Linux x86_64. Exact timing, platform string, allocations,
state counts, edges, timestamp and hashes are in the companion JSON. Single-process, sequential
runs with tracemalloc enabled; timings are not medians or isolated-host benchmarks.

| Model instance | Reachable states | Edges | Observed marginal product |
|---|---:|---:|---:|
| lifecycle, same account (00 / 11) | 532 each | 1,300 each | 150,528 |
| lifecycle, different accounts (01 / 10) | 676 each | 1,888 each | 150,528 |
| relay | 50 | 420 | 2,048 |
| browser relay | 40 | 151 | 320 |
| public search | 84 | 303 | 8,192 |
| video open | 102 | 324 | 9,216 |

Eight instances complete and agree with the original enumerators. Negative mutants remain
covered by existing `scripts/check_model.py`; this cost gate runs the safe instances only.
Lifecycle covers two operation IDs, two plugin/capability identities, one resource, budget two,
four fixed account assignments. Relay has two packets and global budget one. Browser models
have one request/host; video open abstracts a second open ID as a competing consume attempt,
not two full independent navigators. No unbounded queues, implementation threads, real DB
interleavings, DOM size, network behavior or arbitrary operation counts are exhaustively checked.

## Coupling findings: imports are insufficient

The static graph includes function-local imports. Current maximum fan-out: `cli` 15, `kernel` 6;
fan-in: `contracts` 11, `browser_contracts` / `browser_video_contracts` / `relays` 7.
High CLI fan-out is composition-root wiring; high contract fan-in is not itself shared mutable state.
The JSON includes the full graph and retained constructor-parameter method surfaces.

**Identified and repaired authority coupling:** the original `BrowserVideoOpenPlugin` retained
an entire kernel even though it only invoked `consume_browser_selection`. The plugin now retains
only a `SelectionConsumer` port. The CLI supplies `JournalSelectionConsumer` with the kernel's
bound atomic-consumption callback. The adapter exposes that one public method and returns a
copied read-only mapping; current selection values are scalar strings/timestamps. The plugin
materializes a fresh dictionary at the existing host boundary, preserving its schema.

The kernel still owns dispatch, grant, budget, journal, recovery and receipt consumption. None
of these policies or transactions changed. **The callback still retains its kernel provider**;
Python introspection can recover it. This is trusted first-party modularization, NOT a security
sandbox or an elimination of the semantic dependency. The checker explicitly records the
`selection_consumer → kernel` callback edge, verifies expected CLI wiring text is present, and
includes that edge in candidate revalidation frontiers. No dependency is hidden by renaming it.

The checker lists retained constructor parameters and called methods, including tuple assignment.
These are syntactic checks: aliases, arbitrary attributes, reflection and shared mutable state
are NOT ruled out. New whole-kernel plugin retention is budgeted at zero; manual review is still
mandatory. A renamed whole-kernel parameter can evade the name-based heuristic.

## Narrow ports and assume/guarantee contracts (implementation status explicit)

1. **SelectionConsumer (implemented; refinement unproved)**: expose only `consume_browser_selection(request) -> immutable selection`
   through a capability wrapper, not a type annotation over the same whole kernel.
   Assumes exact immutable request, one durable owner, honest clock/DB atomicity.
   Guarantees exact applied/latest/fresh source receipt, query/scope/BVID membership and
   atomic single-use consumption, or failure with no navigation authorization. Kernel retains
   transaction ownership. Wrapper must not export DB, dispatch, grant or mutable journal access.
2. **VideoOpenHost**: expose only `open_video(operation_id, correlation_id, target, selection)`.
   Assumes the consumed selection and trusted truthful host identity observations.
   Guarantees fresh preflight, durable begin before one semantic navigation, matched receipt,
   or blocked/unknown terminal result; unknown never automatically replays. Browser truth,
   crashes between actual side effect and receipt, and host honesty remain assumptions.
3. **Plugin/dispatch boundary**: immutable request/result plus verified relay envelope only.
   Kernel guarantees scoped grant/budget and durable intent before send under its single-owner
   assumptions. Plugin must not widen scope, fabricate success, call another dispatch, or retain
   mutable internal state. Shared budgets remain kernel-owned rather than copied per plugin.
4. **Workflow step port**: sequential request/result envelope (CLI subprocess boundary is an
   acceptable prototype), not business modules holding a full kernel. Explicit concurrency one,
   finite step count and queue bound; durable step intent before launch; stop on unknown/partial
   protocol outcome; no replay on ID reuse. Observed visible subsets retain `complete=false`;
   complete protocol evidence does not imply complete website data.

**Composition obligation:** for every directed interface A→B, prove `Guarantee(A) ⇒ Assumption(B)`
under shared rely conditions; show no other path writes either block's private state, define
interface-state projection/cardinalities, and discharge atomicity and crash boundaries.
Count imported dependencies, retained authorities, shared mutable owners, interface fields/domain
sizes, outstanding requests and queue capacities separately. A low import count is not sufficient.
Current models are separately checked safety abstractions: these cross-model implication and
noninterference/refinement obligations have **not** been proved.

Suggested next contract limits (review-only, not automated claims): one journal writer, one
in-flight workflow step, no implicit pending work queue, no new whole-kernel injections, and
explicit finite interface schemas for each new capability. Interface state cardinalities are not
yet fully enumerated: exact/mismatch abstractions collapse real IDs/URLs/query strings. Do not
invent a numeric interface dimension until abstraction coverage is reviewed.

The parent approved the minimal SelectionConsumer runtime refactor before the new live acceptance
freeze. Only CLI wiring, the video-open plugin and the new adapter changed; kernel dispatch and
shared policy remain unchanged. Offline tests exercise one-method fake ports, immutable detached
results, callback/error preservation and existing dispatch scenarios. Formal refinement remains
unproved; live evidence must use the new source hashes, not be inherited automatically.

## Proof dependency manifest / revalidation frontier

A whole-runtime hash is a useful integrity label but does not itself explain what evidence is
invalidated by a local edit. Preserve that label for the current five-capability live acceptance
snapshot; do not retroactively claim old evidence covers changed code. Future modular evidence
should carry a manifest per claim:

```json
{
  "claim_id": "selection_consumer.single_use",
  "status": "proposed_not_proved",
  "implementation_inputs": ["exact implementing file hashes"],
  "spec_inputs": ["model, property and finite domain hashes"],
  "boundary_contract_inputs": ["versioned immutable request/selection contract hashes"],
  "assumptions": ["single owner", "atomic commit", "truthful clock"],
  "depends_on_claims": ["journal.atomic_consume"],
  "evidence": ["checker/version/command/environment/bounds/output digest"],
  "implementation_refinement_evidence": null,
  "live_acceptance_scope": "separate versioned snapshot, not inherited automatically"
}
```

Define a directed proof-dependency graph `A → B` when claim A relies on B. For changed inputs
`Δ`, the revalidation frontier is the claims directly consuming Δ plus their reverse-reachable
dependents. Report its absolute size, fraction of all claims, maximum reverse fan-out, and the
specific assumptions/contracts that propagate invalidation. A numeric target needs an actual
claim manifest; current modules do not each have certified implementation claims.

The checker emits a **candidate implementation frontier** for each module using imports plus
the reviewed kernel callback dependency. This makes missed import-only coupling visible and
quantifies refactoring candidates, but it is neither a complete semantic graph nor a proof
manifest. Shared DB schema, CLI JSON schemas, environment assumptions and host behavior can
introduce additional edges and must be registered manually. Never use this approximate graph
to exempt evidence automatically.

After an interface-preserving internal edit, re-prove/refine the changed module against the
**same** boundary contract and establish preservation of all assumptions, timing/failure
semantics, side effects and private-state isolation. Only then may unchanged dependents reuse
their compositional claims. A matching signature/hash alone does not establish behavioral
substitutability. Changed contracts/assumptions propagate revalidation to dependents; absent
refinement/composition evidence, retain conservative full affected integration validation.
The implemented narrow SelectionConsumer wrapper reduces accidental authority and future proof premises; it does not
by itself prove equivalence or allow live evidence to be copied to the new implementation.
